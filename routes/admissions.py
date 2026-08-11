from datetime import date, datetime, timedelta
import csv
import io
import re
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from openpyxl import Workbook
from sqlalchemy import and_, or_

from application import db
from models import Booking, DailySeatBooking, Member, MembershipHistory, Role, Seat, User
from services.access_control import privilege_required, privilege_required_any
from services.booking_service import enforce_booking_rules

admissions_bp = Blueprint("admissions", __name__, template_folder="../templates")


def _generate_member_code():
    count = Member.query.count() + 1
    return f"{count:04d}"


def _create_user_for_member(full_name, email, member_code):
    """Create a user with username = full_name (lowercase) and password = member_code."""
    username = full_name.strip().lower().replace("  ", " ")
    base = username
    suffix = 1
    while User.query.filter_by(username=username).first():
        username = f"{base}{suffix}"
        suffix += 1

    member_role = Role.query.filter_by(role_name="Member").first()
    if not member_role:
        member_role = Role(role_name="Member", description="Library member")
        db.session.add(member_role)
        db.session.flush()

    user = User(
        username=username,
        email=email.lower(),
        role_id=member_role.id,
        is_active=True,
    )
    user.set_password(member_code)
    db.session.add(user)
    db.session.flush()
    return user


def _calculate_age(dob):
    today = date.today()
    years = today.year - dob.year
    if (today.month, today.day) < (dob.month, dob.day):
        years -= 1
    return years


def _contains_digit(value):
    return any(character.isdigit() for character in value)


def _normalize_seat_number(value):
    return value.strip().upper()


def _seat_number_variants(seat_number):
    normalized = _normalize_seat_number(seat_number)
    if not normalized:
        return []

    variants = {normalized}
    compact = normalized.replace("-", "")
    variants.add(compact)

    if len(compact) >= 2 and compact[0].isalpha() and compact[1:].isdigit():
        prefix = compact[0]
        number = int(compact[1:])
        variants.add(f"{prefix}{number}")
        variants.add(f"{prefix}-{number}")
        variants.add(f"{prefix}{number:02d}")
        variants.add(f"{prefix}-{number:02d}")

    return list(variants)


def _canonical_seat_token(value):
    if value is None:
        return None
    normalized = re.sub(r"[^A-Z0-9]", "", str(value).upper())
    if not normalized:
        return None
    if len(normalized) >= 2 and normalized[0].isalpha() and normalized[1:].isdigit():
        return f"{normalized[0]}{int(normalized[1:])}"
    return normalized


def _is_valid_reservation_seat_format(seat_number, lab=None):
    token = _canonical_seat_token(seat_number)
    if not token or len(token) < 2 or not token[1:].isdigit():
        return False

    prefix = token[0]
    seat_index = int(token[1:])

    if lab == "Lab 1":
        return prefix == "A" and 1 <= seat_index <= 80
    if lab == "Lab 2":
        return prefix == "B" and 1 <= seat_index <= 85

    return (prefix == "A" and 1 <= seat_index <= 80) or (prefix == "B" and 1 <= seat_index <= 85)


def _find_seat_by_number(seat_number):
    input_token = _canonical_seat_token(seat_number)
    if not input_token:
        return None

    # Robust against DB formats like B1, B-1, B01, B-01, B001, B 01.
    seats = Seat.query.order_by(Seat.id.asc()).all()
    for seat in seats:
        if _canonical_seat_token(seat.seat_number) == input_token:
            return seat
    return None


def _create_missing_seat_for_reservation(seat_number):
    token = _canonical_seat_token(seat_number)
    if not token:
        return None
    if not _is_valid_reservation_seat_format(token):
        return None

    floor = "1" if token.startswith("A") else "2"

    seat = Seat(
        seat_number=token,
        seat_type="Standard",
        status="Available",
        monthly_fee=Decimal("0.00"),
        floor=floor,
        remarks="Auto-created from reserve seat entry",
    )
    db.session.add(seat)
    db.session.flush()
    return seat


def _build_admissions_query(search, status_filter, month=None, year=None, lab_filter=None):
    query = Member.query
    if search:
        query = query.filter(
            Member.full_name.ilike(f"%{search}%")
            | Member.member_code.ilike(f"%{search}%")
            | Member.email.ilike(f"%{search}%")
            | Member.phone.ilike(f"%{search}%")
            | Member.aadhaar_number.ilike(f"%{search}%")
            | Member.school_name.ilike(f"%{search}%")
        )
    if status_filter:
        if status_filter == "Expiring Soon":
            today = date.today()
            query = query.filter(
                Member.membership_status == "Active",
                Member.membership_end_date.isnot(None),
                Member.membership_end_date >= today,
                Member.membership_end_date <= today + timedelta(days=7),
            )
        else:
            query = query.filter_by(membership_status=status_filter)
    if month and year:
        try:
            month_int = int(month)
            year_int = int(year)
            if 1 <= month_int <= 12 and year_int > 0:
                start_of_month = date(year_int, month_int, 1)
                if month_int == 12:
                    end_of_month = date(year_int + 1, 1, 1) - timedelta(days=1)
                else:
                    end_of_month = date(year_int, month_int + 1, 1) - timedelta(days=1)
                query = query.filter(
                    Member.registration_date >= start_of_month,
                    Member.registration_date <= end_of_month
                )
        except (ValueError, TypeError):
            pass

    if lab_filter in ("Lab 1", "Lab 2"):
        query = query.filter(Member.lab == lab_filter)

    return query


def _record_membership_history(member_id, period_start_date, period_end_date, event_type, notes=None):
    if not member_id or not period_start_date or not period_end_date:
        return

    changed_by_user_id = current_user.id if current_user.is_authenticated else None
    db.session.add(
        MembershipHistory(
            member_id=member_id,
            period_start_date=period_start_date,
            period_end_date=period_end_date,
            event_type=event_type,
            notes=notes,
            changed_by_user_id=changed_by_user_id,
        )
    )


def _reservation_by_member_for_members(members):
    reservation_by_member = {}
    member_ids = [member.id for member in members]
    if not member_ids:
        return reservation_by_member

    active_bookings = (
        Booking.query.join(Seat)
        .filter(
            Booking.member_id.in_(member_ids),
            Booking.booking_status == "Confirmed",
            Booking.end_date >= date.today(),
        )
        .order_by(Booking.end_date.desc(), Booking.id.desc())
        .all()
    )
    for booking in active_bookings:
        if booking.member_id not in reservation_by_member:
            reservation_by_member[booking.member_id] = booking
    return reservation_by_member


@admissions_bp.route("/admissions")
@login_required
@privilege_required("admissions.manage", message="Admissions access is not assigned to this role.")
def index():
    search = request.args.get("q", "")
    status_filter = request.args.get("status", "")
    lab_filter = request.args.get("lab", "")
    month = request.args.get("month", "")
    year = request.args.get("year", "")
    page = request.args.get("page", 1, type=int)
    query = _build_admissions_query(search, status_filter, month, year, lab_filter)
    pagination = query.order_by(Member.registration_date.desc()).paginate(page=page, per_page=15)

    reservation_by_member = _reservation_by_member_for_members(pagination.items)

    return render_template(
        "admissions/index.html",
        pagination=pagination,
        search=search,
        status_filter=status_filter,
        lab_filter=lab_filter,
        month=month,
        year=year,
        reservation_by_member=reservation_by_member,
        page_mode="manage",
    )


@admissions_bp.route("/admissions/delete")
@login_required
@privilege_required("admissions.delete", message="Delete Admission access is not assigned to this role.")
def delete_admission_index():
    search = request.args.get("q", "")
    status_filter = request.args.get("status", "")
    lab_filter = request.args.get("lab", "")
    month = request.args.get("month", "")
    year = request.args.get("year", "")
    page = request.args.get("page", 1, type=int)
    query = _build_admissions_query(search, status_filter, month, year, lab_filter)
    pagination = query.order_by(Member.registration_date.desc()).paginate(page=page, per_page=15)

    return render_template(
        "admissions/index.html",
        pagination=pagination,
        search=search,
        status_filter=status_filter,
        lab_filter=lab_filter,
        month=month,
        year=year,
        reservation_by_member=_reservation_by_member_for_members(pagination.items),
        page_mode="delete",
    )


@admissions_bp.route("/admissions/<int:member_id>/history")
@login_required
@privilege_required("admissions.manage", message="Admissions access is not assigned to this role.")
def membership_history(member_id):
    member = Member.query.get_or_404(member_id)
    show_all = request.args.get("all", "0") == "1"
    since_date = date.today() - relativedelta(years=2)

    history_query = MembershipHistory.query.filter_by(member_id=member.id)
    if not show_all:
        since_timestamp = datetime.combine(since_date, datetime.min.time())
        history_query = history_query.filter(
            or_(
                MembershipHistory.period_end_date >= since_date,
                MembershipHistory.created_at >= since_timestamp,
            )
        )

    history_items = history_query.order_by(
        MembershipHistory.period_start_date.desc(), MembershipHistory.id.desc()
    ).all()

    return render_template(
        "admissions/history.html",
        member=member,
        history_items=history_items,
        since_date=since_date,
        show_all=show_all,
    )


@admissions_bp.route("/admissions/delete/<int:member_id>", methods=["POST"])
@login_required
@privilege_required("admissions.delete", message="Delete Admission access is not assigned to this role.")
def delete_admission(member_id):
    member = Member.query.get_or_404(member_id)
    user = member.user
    if member.membership_status == "Deleted":
        flash(f"Admission for {member.full_name} is already deleted.", "warning")
        return redirect(url_for("admissions.delete_admission_index"))

    affected_seat_ids = {booking.seat_id for booking in member.bookings if booking.seat_id}
    member_name = member.full_name
    member_code = member.member_code

    DailySeatBooking.query.filter_by(member_id=member.id).delete()

    for booking in list(member.bookings):
        db.session.delete(booking)

    if user:
        user.is_active = False
        user.is_locked = True

    member.membership_status = "Deleted"

    if affected_seat_ids:
        seats = Seat.query.filter(Seat.id.in_(list(affected_seat_ids))).all()
        for seat in seats:
            has_active_booking = (
                Booking.query.filter(
                    Booking.seat_id == seat.id,
                    Booking.booking_status == "Confirmed",
                    Booking.end_date >= date.today(),
                ).first()
                is not None
            )
            seat.status = "Occupied" if has_active_booking else "Available"

    db.session.commit()
    flash(f"Admission deleted for {member_name} ({member_code}) and kept in admission log.", "success")
    return redirect(url_for("admissions.delete_admission_index"))


def _active_reservations_query():
    return Booking.query.join(Member).join(Seat).filter(
        Booking.booking_status == "Confirmed",
        Booking.end_date >= date.today(),
    )


@admissions_bp.route("/admissions/reserve-seats")
@login_required
@privilege_required_any(("admissions.manage", "admissions.reserve"), message="Reserve Seat access is not assigned to this role.")
def reserve_seats():
    search = request.args.get("q", "").strip()
    query = _active_reservations_query()
    if search:
        query = query.filter(
            or_(
                Member.full_name.ilike(f"%{search}%"),
                Member.member_code.ilike(f"%{search}%"),
                Seat.seat_number.ilike(f"%{search}%"),
            )
        )

    reservations = query.order_by(Booking.end_date.asc(), Seat.seat_number.asc()).all()
    members = (
        Member.query.filter_by(membership_status="Active")
        .order_by(Member.full_name.asc())
        .all()
    )
    return render_template(
        "admissions/reserve_seats.html",
        reservations=reservations,
        members=members,
        search=search,
    )


@admissions_bp.route("/admissions/reserve-seats/create", methods=["POST"])
@login_required
@privilege_required_any(("admissions.manage", "admissions.reserve"), message="Reserve Seat access is not assigned to this role.")
def create_reserved_seat():
    member_id = request.form.get("member_id", type=int)
    seat_number_raw = (request.form.get("seat_number") or "").strip()

    if not member_id or not seat_number_raw:
        flash("Member and seat number are required.", "danger")
        return redirect(url_for("admissions.reserve_seats"))

    seat_token = _canonical_seat_token(seat_number_raw)
    if not seat_token or not _is_valid_reservation_seat_format(seat_token):
        flash("Seat format must be A1 to A80 for Lab 1 or B1 to B85 for Lab 2.", "danger")
        return redirect(url_for("admissions.reserve_seats"))

    member = Member.query.get(member_id)
    seat = _find_seat_by_number(seat_token)
    if not seat:
        seat = _create_missing_seat_for_reservation(seat_token)
    if not member:
        flash("Selected member not found.", "danger")
        return redirect(url_for("admissions.reserve_seats"))
    if member.membership_status != "Active":
        flash("Only active members can reserve a seat.", "danger")
        return redirect(url_for("admissions.reserve_seats"))
    if not seat:
        flash("Seat not found. Enter a valid Lab 1 or Lab 2 seat number.", "danger")
        return redirect(url_for("admissions.reserve_seats"))

    start_date = member.membership_start_date
    end_date = member.membership_end_date
    if not start_date or not end_date:
        flash("Member admission start/end date is missing. Update admission details first.", "danger")
        return redirect(url_for("admissions.reserve_seats"))

    validation_error = enforce_booking_rules(member.id, seat.id, start_date, end_date)
    if validation_error:
        flash(validation_error, "danger")
        return redirect(url_for("admissions.reserve_seats"))

    booking = Booking(
        member_id=member.id,
        seat_id=seat.id,
        start_date=start_date,
        end_date=end_date,
        booking_status="Confirmed",
    )
    seat.status = "Occupied"
    db.session.add(booking)
    db.session.commit()
    flash(f"Reserved seat {seat.seat_number} for {member.full_name}.", "success")
    return redirect(url_for("admissions.reserve_seats"))


@admissions_bp.route("/admissions/reserve-seats/unreserve/<int:booking_id>", methods=["POST"])
@login_required
@privilege_required_any(("admissions.manage", "admissions.reserve"), message="Reserve Seat access is not assigned to this role.")
def unreserve_seat(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    booking.booking_status = "Cancelled"

    has_other_active = (
        Booking.query.filter(
            Booking.id != booking.id,
            Booking.seat_id == booking.seat_id,
            Booking.booking_status == "Confirmed",
            Booking.end_date >= date.today(),
        )
        .first()
        is not None
    )
    if not has_other_active and booking.seat:
        booking.seat.status = "Available"

    db.session.commit()
    flash(f"Seat {booking.seat.seat_number if booking.seat else ''} unreserved successfully.", "success")
    return redirect(url_for("admissions.reserve_seats"))


@admissions_bp.route("/admissions/reserve-seats/reassign/<int:booking_id>", methods=["POST"])
@login_required
@privilege_required_any(("admissions.manage", "admissions.reserve"), message="Reserve Seat access is not assigned to this role.")
def reassign_reserved_seat(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    new_member_id = request.form.get("member_id", type=int)
    new_member = Member.query.get(new_member_id) if new_member_id else None

    if not new_member:
        flash("Please select a valid member.", "danger")
        return redirect(url_for("admissions.reserve_seats"))

    seat_overlap = Booking.query.filter(
        Booking.id != booking.id,
        Booking.seat_id == booking.seat_id,
        Booking.booking_status == "Confirmed",
        Booking.end_date >= booking.start_date,
        Booking.start_date <= booking.end_date,
    ).first()
    if seat_overlap:
        flash("Seat has an overlapping booking and cannot be reassigned.", "danger")
        return redirect(url_for("admissions.reserve_seats"))

    member_overlap = Booking.query.filter(
        Booking.id != booking.id,
        Booking.member_id == new_member.id,
        Booking.booking_status == "Confirmed",
        Booking.end_date >= booking.start_date,
        Booking.start_date <= booking.end_date,
    ).first()
    if member_overlap:
        flash("Selected member already has an overlapping reserved seat.", "danger")
        return redirect(url_for("admissions.reserve_seats"))

    booking.member_id = new_member.id
    db.session.commit()
    flash(f"Seat {booking.seat.seat_number if booking.seat else ''} reassigned to {new_member.full_name}.", "success")
    return redirect(url_for("admissions.reserve_seats"))


@admissions_bp.route("/admissions/export")
@login_required
@privilege_required("admissions.manage", message="Admissions access is not assigned to this role.")
def export_admissions():
    search = request.args.get("q", "")
    status_filter = request.args.get("status", "")
    lab_filter = request.args.get("lab", "")
    month = request.args.get("month", "")
    year = request.args.get("year", "")
    export_format = request.args.get("format", "csv").lower()

    members = _build_admissions_query(search, status_filter, month, year, lab_filter).order_by(Member.registration_date.desc()).all()
    header = [
        "Member Code",
        "Full Name",
        "Email",
        "Phone",
        "Aadhaar",
        "Gender",
        "School",
        "Emergency Contact Name",
        "Emergency Contact Number",
        "Lab",
        "Status",
        "Start Date",
        "End Date",
    ]
    rows = [
        [
            member.member_code,
            member.full_name,
            member.email,
            member.phone,
            member.aadhaar_number or "",
            member.gender or "",
            member.school_name or "",
            member.emergency_contact_name or "",
            member.emergency_contact_number or "",
            member.lab or "",
            member.membership_status,
            member.membership_start_date.isoformat() if member.membership_start_date else "",
            member.membership_end_date.isoformat() if member.membership_end_date else "",
        ]
        for member in members
    ]

    if export_format == "xlsx":
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Admissions"
        sheet.append(header)
        for row in rows:
            sheet.append(row)
        output = io.BytesIO()
        workbook.save(output)
        workbook.close()
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=admissions.xlsx"},
        )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(header)
    writer.writerows(rows)
    csv_data = output.getvalue()
    output.close()
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=admissions.csv"},
    )


@admissions_bp.route("/admissions/new", methods=["GET", "POST"])
@login_required
@privilege_required("admissions.manage", message="Admissions access is not assigned to this role.")
def new_admission():
    available_seats = Seat.query.filter_by(status="Available").order_by(Seat.seat_number.asc()).all()

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip().lower()
        aadhaar_number = request.form.get("aadhaar_number", "").strip()
        dob_str = request.form.get("date_of_birth", "").strip()
        gender = request.form.get("gender", "").strip()
        school_name = request.form.get("school_name", "").strip()
        lab = request.form.get("lab", "").strip()
        emergency_contact_name = request.form.get("emergency_contact_name", "").strip()
        emergency_contact_number = request.form.get("emergency_contact_number", "").strip()
        address = request.form.get("address", "").strip()
        reserved_seat_number = request.form.get("reserved_seat_number", "").strip()
        start_date_str = request.form.get("membership_start_date", "")
        duration_months = int(request.form.get("duration_months", 1))

        errors = []
        if not full_name:
            errors.append("Full name is required.")
        elif _contains_digit(full_name):
            errors.append("Full name cannot contain digits.")
        if not phone:
            errors.append("Phone is required.")
        elif not phone.isdigit():
            errors.append("Phone number must contain digits only.")
        if not email:
            errors.append("Email is required.")
        if not aadhaar_number:
            errors.append("Aadhaar number is required.")
        elif not (aadhaar_number.isdigit() and len(aadhaar_number) == 12):
            errors.append("Aadhaar number must be exactly 12 digits.")
        if not dob_str:
            errors.append("Date of birth is required.")
        if not gender:
            errors.append("Gender is required.")
        if not school_name:
            errors.append("School name is required.")
        if lab not in ("Lab 1", "Lab 2"):
            errors.append("Please select a valid lab.")
        if not emergency_contact_name:
            errors.append("Emergency contact name is required.")
        elif _contains_digit(emergency_contact_name):
            errors.append("Emergency contact name cannot contain digits.")
        if not emergency_contact_number:
            errors.append("Emergency contact number is required.")
        elif not emergency_contact_number.isdigit():
            errors.append("Emergency contact number must contain digits only.")
        if not address:
            errors.append("Address is required.")
        if User.query.filter_by(email=email).first():
            errors.append("A user with this email already exists.")
        if Member.query.filter_by(aadhaar_number=aadhaar_number).first():
            errors.append("A member with this Aadhaar number already exists.")

        dob = None
        if dob_str:
            try:
                dob_input = dob_str.replace(".", "/")
                dob = datetime.strptime(dob_input, "%d/%m/%Y").date()
                if dob > date.today():
                    errors.append("Date of birth cannot be in the future.")
            except ValueError:
                errors.append("Date of birth is invalid. Use format dd.mm.yyyy.")

        try:
            start_date = date.fromisoformat(start_date_str) if start_date_str else date.today()
        except ValueError:
            start_date = date.today()

        end_date = start_date + relativedelta(months=duration_months)

        selected_seat = None
        if reserved_seat_number:
            seat_token = _canonical_seat_token(reserved_seat_number)
            if not seat_token or not _is_valid_reservation_seat_format(seat_token, lab):
                errors.append("Invalid seat format. Use A1 to A80 for Lab 1 or B1 to B85 for Lab 2.")

            selected_seat = _find_seat_by_number(seat_token)
            if not selected_seat:
                selected_seat = _create_missing_seat_for_reservation(seat_token)
            if not selected_seat:
                errors.append("Reserved seat number is invalid.")
            elif lab == "Lab 1" and not selected_seat.seat_number.upper().startswith("A"):
                errors.append("Please enter a Lab 1 seat number (example: A12).")
            elif lab == "Lab 2" and not selected_seat.seat_number.upper().startswith("B"):
                errors.append("Please enter a Lab 2 seat number (example: B12).")

        if errors:
            for err in errors:
                flash(err, "danger")
            return render_template(
                "admissions/new.html",
                form=request.form,
                today=date.today(),
                available_seats=available_seats,
            )

        age = _calculate_age(dob)

        member_code = _generate_member_code()
        user = _create_user_for_member(full_name, email, member_code)

        member = Member(
            member_code=member_code,
            full_name=full_name,
            phone=phone,
            email=email,
            aadhaar_number=aadhaar_number,
            date_of_birth=dob,
            age=age,
            gender=gender,
            school_name=school_name,
            lab=lab,
            emergency_contact_name=emergency_contact_name,
            emergency_contact_number=emergency_contact_number,
            address=address,
            membership_start_date=start_date,
            membership_end_date=end_date,
            membership_status="Active",
            user_id=user.id,
        )

        db.session.add(member)
        db.session.flush()

        _record_membership_history(
            member.id,
            start_date,
            end_date,
            "Admission",
            "Initial admission",
        )

        if selected_seat:
            validation_error = enforce_booking_rules(member.id, selected_seat.id, start_date, end_date)
            if validation_error:
                db.session.rollback()
                flash(validation_error, "danger")
                return render_template(
                    "admissions/new.html",
                    form=request.form,
                    today=date.today(),
                    available_seats=available_seats,
                )

            booking = Booking(
                member_id=member.id,
                seat_id=selected_seat.id,
                start_date=start_date,
                end_date=end_date,
                booking_status="Confirmed",
            )
            selected_seat.status = "Occupied"
            db.session.add(booking)

        db.session.commit()

        if selected_seat:
            flash(
                f"Admission successful! Member ID: {member_code} | "
                f"Username: {user.username} | Password: {member_code} | "
                f"Reserved Seat: {selected_seat.seat_number}",
                "success",
            )
        else:
            flash(
                f"Admission successful! Member ID: {member_code} | "
                f"Username: {user.username} | Password: {member_code}",
                "success",
            )
        return redirect(url_for("admissions.index"))

    return render_template("admissions/new.html", form={}, today=date.today(), available_seats=available_seats)


@admissions_bp.route("/admissions/edit/<int:member_id>", methods=["GET", "POST"])
@login_required
@privilege_required("admissions.manage", message="Admissions access is not assigned to this role.")
def edit_admission(member_id):
    if not current_user.is_admin:
        flash("Only admin user can edit admissions.", "danger")
        return redirect(url_for("admissions.index"))

    member = Member.query.get_or_404(member_id)

    if request.method == "POST":
        previous_start_date = member.membership_start_date
        previous_end_date = member.membership_end_date

        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip().lower()
        aadhaar_number = request.form.get("aadhaar_number", "").strip()
        dob_str = request.form.get("date_of_birth", "").strip()
        gender = request.form.get("gender", "").strip()
        school_name = request.form.get("school_name", "").strip()
        lab = request.form.get("lab", "").strip()
        emergency_contact_name = request.form.get("emergency_contact_name", "").strip()
        emergency_contact_number = request.form.get("emergency_contact_number", "").strip()
        address = request.form.get("address", "").strip()
        membership_start_date_str = request.form.get("membership_start_date", "").strip()
        membership_end_date_str = request.form.get("membership_end_date", "").strip()
        membership_status = request.form.get("membership_status", "").strip()

        errors = []
        if not full_name:
            errors.append("Full name is required.")
        elif _contains_digit(full_name):
            errors.append("Full name cannot contain digits.")
        if not phone:
            errors.append("Phone is required.")
        elif not phone.isdigit():
            errors.append("Phone number must contain digits only.")
        if not email:
            errors.append("Email is required.")
        if not aadhaar_number:
            errors.append("Aadhaar number is required.")
        elif not (aadhaar_number.isdigit() and len(aadhaar_number) == 12):
            errors.append("Aadhaar number must be exactly 12 digits.")
        if not dob_str:
            errors.append("Date of birth is required.")
        if not gender:
            errors.append("Gender is required.")
        if not school_name:
            errors.append("School name is required.")
        if lab not in ("Lab 1", "Lab 2"):
            errors.append("Please select a valid lab.")
        if not emergency_contact_name:
            errors.append("Emergency contact name is required.")
        elif _contains_digit(emergency_contact_name):
            errors.append("Emergency contact name cannot contain digits.")
        if not emergency_contact_number:
            errors.append("Emergency contact number is required.")
        elif not emergency_contact_number.isdigit():
            errors.append("Emergency contact number must contain digits only.")
        if not address:
            errors.append("Address is required.")
        if membership_status not in ("Active", "Expired", "Deleted"):
            errors.append("Please select a valid membership status.")

        existing_user = User.query.filter(User.email == email, User.id != member.user_id).first()
        if existing_user:
            errors.append("A user with this email already exists.")
        existing_member = Member.query.filter(Member.aadhaar_number == aadhaar_number, Member.id != member.id).first()
        if existing_member:
            errors.append("A member with this Aadhaar number already exists.")

        dob = None
        if dob_str:
            try:
                dob_input = dob_str.replace(".", "/")
                dob = datetime.strptime(dob_input, "%d/%m/%Y").date()
                if dob > date.today():
                    errors.append("Date of birth cannot be in the future.")
            except ValueError:
                errors.append("Date of birth is invalid. Use format dd.mm.yyyy.")

        membership_start_date = None
        membership_end_date = None
        if membership_start_date_str:
            try:
                membership_start_date = datetime.strptime(membership_start_date_str, "%Y.%m.%d").date()
            except ValueError:
                errors.append("Membership start date is invalid. Use format yyyy.mm.dd.")
        if membership_end_date_str:
            try:
                membership_end_date = datetime.strptime(membership_end_date_str, "%Y.%m.%d").date()
            except ValueError:
                errors.append("Membership end date is invalid. Use format yyyy.mm.dd.")

        if membership_start_date and membership_end_date and membership_end_date < membership_start_date:
            errors.append("Membership end date cannot be before start date.")

        if errors:
            for err in errors:
                flash(err, "danger")
            form = dict(request.form)
            return render_template("admissions/edit.html", member=member, form=form)

        member.full_name = full_name
        member.phone = phone
        member.email = email
        member.aadhaar_number = aadhaar_number
        member.date_of_birth = dob
        member.age = _calculate_age(dob)
        member.gender = gender
        member.school_name = school_name
        member.lab = lab
        member.emergency_contact_name = emergency_contact_name
        member.emergency_contact_number = emergency_contact_number
        member.address = address
        member.membership_start_date = membership_start_date
        member.membership_end_date = membership_end_date
        member.membership_status = membership_status

        if (
            membership_start_date
            and membership_end_date
            and (
                previous_start_date != membership_start_date
                or previous_end_date != membership_end_date
            )
        ):
            _record_membership_history(
                member.id,
                membership_start_date,
                membership_end_date,
                "Manual Update",
                "Membership dates updated from edit admission",
            )

        if member.user:
            member.user.email = email
            if membership_status == "Deleted":
                member.user.is_active = False
                if hasattr(member.user, "is_locked"):
                    member.user.is_locked = True
            else:
                member.user.is_active = True
                if hasattr(member.user, "is_locked"):
                    member.user.is_locked = False

        db.session.commit()
        flash(f"Admission updated for {member.full_name}.", "success")
        return redirect(url_for("admissions.index"))

    form = {
        "full_name": member.full_name or "",
        "phone": member.phone or "",
        "email": member.email or "",
        "aadhaar_number": member.aadhaar_number or "",
        "date_of_birth": member.date_of_birth.strftime("%d.%m.%Y") if member.date_of_birth else "",
        "gender": member.gender or "",
        "school_name": member.school_name or "",
        "lab": member.lab or "",
        "emergency_contact_name": member.emergency_contact_name or "",
        "emergency_contact_number": member.emergency_contact_number or "",
        "address": member.address or "",
        "membership_start_date": member.membership_start_date.strftime("%Y.%m.%d") if member.membership_start_date else "",
        "membership_end_date": member.membership_end_date.strftime("%Y.%m.%d") if member.membership_end_date else "",
        "membership_status": member.membership_status or "Active",
    }
    return render_template("admissions/edit.html", member=member, form=form)


@admissions_bp.route("/admissions/renew/<int:member_id>", methods=["GET", "POST"])
@login_required
@privilege_required("admissions.manage", message="Admissions access is not assigned to this role.")
def renew(member_id):
    member = Member.query.get_or_404(member_id)
    if request.method == "POST":
        duration_months = int(request.form.get("duration_months", 1))
        base_date = member.membership_end_date or date.today()
        if base_date < date.today():
            base_date = date.today()
        new_end_date = base_date + relativedelta(months=duration_months)
        if not member.membership_start_date:
            member.membership_start_date = base_date
        member.membership_end_date = new_end_date
        member.membership_status = "Active"

        _record_membership_history(
            member.id,
            base_date,
            new_end_date,
            "Renewal",
            f"Renewed for {duration_months} month(s)",
        )

        if member.user:
            member.user.is_active = True
            if hasattr(member.user, "failed_login_attempts"):
                member.user.failed_login_attempts = 0
            if hasattr(member.user, "is_locked"):
                member.user.is_locked = False
        db.session.commit()
        flash(f"Membership renewed until {member.membership_end_date}.", "success")
        return redirect(url_for("admissions.index"))
    return render_template("admissions/renew.html", member=member, today=date.today())
