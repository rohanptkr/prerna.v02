from datetime import date, datetime, timedelta
from functools import wraps
from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from io import StringIO
import csv
from sqlalchemy.exc import IntegrityError

from application import db
from forms.admin_forms import MemberForm, PaymentForm, RoleForm, SeatForm, BookingForm, UserForm, UserEditForm
from models import AuditLog, Booking, DailySeatBooking, Member, Payment, RenewalRequest, Role, Seat, User
from models.attendance import Attendance
from services.access_control import privilege_required
from services.booking_service import enforce_booking_rules, group_payments_by_month
from services.dashboard_service import (
    calculate_dashboard_metrics,
    get_dashboard_attendance_entries,
    get_dashboard_member_list,
)
from services.daily_seat_service import (
    build_booking_source_label,
    build_seat_layout,
    get_client_ip,
    mark_attendance_login,
    seat_label_from_storage,
    storage_seat_number_from_code,
)

admin_bp = Blueprint("admin", __name__, template_folder="../templates")


def _latest_seat_by_member(member_ids):
    seat_by_member = {}
    if not member_ids:
        return seat_by_member

    bookings = (
        Booking.query.join(Seat)
        .filter(
            Booking.member_id.in_(member_ids),
            Booking.booking_status == "Confirmed",
        )
        .order_by(Booking.end_date.desc(), Booking.id.desc())
        .all()
    )

    for booking in bookings:
        if booking.member_id in seat_by_member:
            continue
        seat_by_member[booking.member_id] = booking.seat.seat_number if booking.seat else "-"

    return seat_by_member


def _booking_seat_label(booking):
    if not booking or not booking.seat:
        return "-"

    seat_number = storage_seat_number_from_code(booking.seat.seat_number)
    if seat_number is None:
        return booking.seat.seat_number or "-"
    return seat_label_from_storage(seat_number)


def _latest_confirmed_booking_by_member(member_ids, today=None):
    today = today or date.today()
    latest_by_member = {}
    if not member_ids:
        return latest_by_member

    bookings = (
        Booking.query.join(Seat)
        .filter(
            Booking.member_id.in_(member_ids),
            Booking.booking_status == "Confirmed",
            Booking.end_date >= today,
        )
        .order_by(Booking.end_date.desc(), Booking.id.desc())
        .all()
    )

    for booking in bookings:
        if booking.member_id not in latest_by_member:
            latest_by_member[booking.member_id] = booking

    return latest_by_member


def _members_with_inactive_bookings(lab, report_date, today):
    rows = []
    seen_member_ids = set()

    # Primary source: attendance log for the selected report date.
    attendance_rows = (
        Attendance.query.join(Member)
        .filter(
            Attendance.attendance_date == report_date,
            Attendance.seat_label.isnot(None),
            Member.lab == lab,
            Member.membership_status == "Inactive",
        )
        .order_by(Attendance.login_time.desc(), Attendance.id.desc())
        .all()
    )
    for attendance in attendance_rows:
        if attendance.member_id in seen_member_ids:
            continue
        seen_member_ids.add(attendance.member_id)
        rows.append(
            {
                "member": attendance.member,
                "seat_label": attendance.seat_label or "-",
                "booked_on": attendance.attendance_date,
                "source": "Attendance Log",
            }
        )

    # Primary source: same-day booked seats by inactive members.
    daily_bookings = (
        DailySeatBooking.query.join(Member)
        .filter(
            DailySeatBooking.booking_date == report_date,
            Member.lab == lab,
            Member.membership_status == "Inactive",
        )
        .order_by(DailySeatBooking.created_at.desc(), DailySeatBooking.id.desc())
        .all()
    )
    for booking in daily_bookings:
        if booking.member_id in seen_member_ids:
            continue
        seen_member_ids.add(booking.member_id)
        rows.append(
            {
                "member": booking.member,
                "seat_label": seat_label_from_storage(booking.seat_number),
                "booked_on": booking.booking_date,
                "source": "Daily Booking",
            }
        )

    # Fallback source: inactive members still having confirmed reserved bookings.
    bookings = (
        Booking.query.join(Member).join(Seat)
        .filter(
            Member.lab == lab,
            Member.membership_status == "Inactive",
            Booking.booking_status == "Confirmed",
            Booking.end_date >= today,
        )
        .order_by(Booking.end_date.desc(), Booking.id.desc())
        .all()
    )
    for booking in bookings:
        if booking.member_id in seen_member_ids:
            continue
        seen_member_ids.add(booking.member_id)
        rows.append(
            {
                "member": booking.member,
                "seat_label": _booking_seat_label(booking),
                "booked_on": booking.start_date,
                "source": "Reserved Booking",
            }
        )

    return rows


def _lab2_booked_reserved_mismatches(today):
    daily_bookings = (
        DailySeatBooking.query.join(Member)
        .filter(
            DailySeatBooking.booking_date == today,
            Member.lab == "Lab 2",
        )
        .order_by(DailySeatBooking.created_at.desc(), DailySeatBooking.id.desc())
        .all()
    )

    reserved_by_member = _latest_confirmed_booking_by_member(
        [booking.member_id for booking in daily_bookings if booking.member_id],
        today=today,
    )

    mismatches = []
    seen_member_ids = set()
    for daily_booking in daily_bookings:
        if not daily_booking.member_id or daily_booking.member_id in seen_member_ids:
            continue
        seen_member_ids.add(daily_booking.member_id)
        reserved_booking = reserved_by_member.get(daily_booking.member_id)
        reserved_label = _booking_seat_label(reserved_booking)
        daily_label = seat_label_from_storage(daily_booking.seat_number)
        if not reserved_booking or daily_label != reserved_label:
            mismatches.append(
                {
                    "member": daily_booking.member,
                    "daily_seat": daily_label,
                    "reserved_seat": reserved_label,
                    "booking_start_date": reserved_booking.start_date if reserved_booking else None,
                    "booking_end_date": reserved_booking.end_date if reserved_booking else None,
                }
            )

    return mismatches


def _expired_members_without_bookings_after_expiry(lab_filter="all", status_filter="all", days=15):
    if status_filter not in {"all", "Expired"}:
        return []

    today = date.today()

    query = Member.query.filter(
        Member.membership_status == "Expired",
        Member.membership_end_date.isnot(None),
    )
    if lab_filter in {"Lab 1", "Lab 2"}:
        query = query.filter(Member.lab == lab_filter)

    members = query.order_by(Member.membership_end_date.asc(), Member.full_name.asc()).all()
    member_ids = [member.id for member in members]
    reserved_by_member = _latest_confirmed_booking_by_member(member_ids, today=today)
    bookings_by_member = {}

    if member_ids:
        bookings = (
            Booking.query.join(Seat)
            .filter(
                Booking.member_id.in_(member_ids),
                Booking.booking_status == "Confirmed",
            )
            .order_by(Booking.start_date.asc(), Booking.id.asc())
            .all()
        )
        for booking in bookings:
            bookings_by_member.setdefault(booking.member_id, []).append(booking)

    rows = []
    for member in members:
        expiry_date = member.membership_end_date
        if not expiry_date:
            continue

        reserved_booking = reserved_by_member.get(member.id)
        reserved_seat = _booking_seat_label(reserved_booking)
        if not reserved_booking or not reserved_seat or reserved_seat == "-":
            continue

        calendar_start = expiry_date + timedelta(days=1)
        calendar_days = [calendar_start + timedelta(days=offset) for offset in range(days)]
        member_bookings = [booking for booking in bookings_by_member.get(member.id, []) if booking.end_date >= calendar_start]
        has_booking_after_expiry = any(booking.start_date <= calendar_days[-1] and booking.end_date >= calendar_start for booking in member_bookings)
        if has_booking_after_expiry:
            continue

        day_cells = []
        for calendar_day in calendar_days:
            matching_booking = next(
                (booking for booking in member_bookings if booking.start_date <= calendar_day <= booking.end_date),
                None,
            )
            day_cells.append(
                {
                    "date": calendar_day,
                    "booked": matching_booking is not None,
                    "seat_label": _booking_seat_label(matching_booking) if matching_booking else None,
                }
            )

        rows.append(
            {
                "member": member,
                "reserved_seat": reserved_seat,
                "calendar_days": day_cells,
                "calendar_start": calendar_start,
                "calendar_end": calendar_days[-1],
            }
        )

    return rows


def _parse_report_date(value, fallback):
    if not value:
        return fallback
    try:
        return date.fromisoformat(value)
    except ValueError:
        return fallback


def _apply_member_report_filters(query, lab_filter=None, status_filter=None):
    if lab_filter in {"Lab 1", "Lab 2"}:
        query = query.filter(Member.lab == lab_filter)
    if status_filter in {"Active", "Expired", "Inactive", "Deleted", "Blacklisted"}:
        query = query.filter(Member.membership_status == status_filter)
    return query


def _month_bounds(month_value, year_value):
    today = date.today()
    try:
        month_int = int(month_value)
    except (TypeError, ValueError):
        month_int = today.month
    try:
        year_int = int(year_value)
    except (TypeError, ValueError):
        year_int = today.year

    if month_int < 1 or month_int > 12:
        month_int = today.month
    if year_int < 1:
        year_int = today.year

    month_start = date(year_int, month_int, 1)
    if month_int == 12:
        next_month_start = date(year_int + 1, 1, 1)
    else:
        next_month_start = date(year_int, month_int + 1, 1)
    month_end = next_month_start - timedelta(days=1)
    return month_int, year_int, month_start, month_end


def _seat_fee_by_code(seat_codes):
    normalized_codes = set()
    for seat_code in seat_codes:
        code = str(seat_code or "").strip()
        if not code:
            continue
        normalized_codes.add(code)
        storage_code = storage_seat_number_from_code(code)
        if storage_code is not None:
            normalized_codes.add(str(storage_code))
            normalized_codes.add(seat_label_from_storage(storage_code))

    if not normalized_codes:
        return {}

    seats = Seat.query.filter(Seat.seat_number.in_(normalized_codes)).all()
    fee_by_code = {}
    for seat in seats:
        seat_code = str(seat.seat_number or "").strip()
        if not seat_code:
            continue
        fee_by_code[seat_code] = seat.monthly_fee
        storage_code = storage_seat_number_from_code(seat_code)
        if storage_code is not None:
            fee_by_code[str(storage_code)] = seat.monthly_fee
            fee_by_code[seat_label_from_storage(storage_code)] = seat.monthly_fee

    return fee_by_code


def _membership_month_analysis(month_value=None, year_value=None, lab_filter="all", seat_filter="all"):
    month_int, year_int, month_start, month_end = _month_bounds(month_value, year_value)

    query = RenewalRequest.query.join(Member).filter(
        db.func.date(RenewalRequest.requested_at) >= month_start,
        db.func.date(RenewalRequest.requested_at) <= month_end,
    )
    if lab_filter in {"Lab 1", "Lab 2"}:
        query = query.filter(Member.lab == lab_filter)

    renewal_requests = query.order_by(RenewalRequest.requested_at.desc(), RenewalRequest.id.desc()).all()
    admissions_query = Member.query.filter(
        Member.registration_date.isnot(None),
        db.func.date(Member.registration_date) >= month_start,
        db.func.date(Member.registration_date) <= month_end,
    )
    if lab_filter in {"Lab 1", "Lab 2"}:
        admissions_query = admissions_query.filter(Member.lab == lab_filter)
    admissions = admissions_query.order_by(Member.registration_date.desc(), Member.id.desc()).all()

    member_ids = [renewal_request.member_id for renewal_request in renewal_requests if renewal_request.member_id]
    member_ids.extend([member.id for member in admissions])
    reserved_seat_by_member = _latest_seat_by_member(member_ids)

    def _has_reserved_seat(member_id):
        reserved = reserved_seat_by_member.get(member_id, "-")
        return bool(reserved and reserved != "-")

    if seat_filter in {"reserved", "unreserved"}:
        filtered_renewals = []
        for renewal_request in renewal_requests:
            has_reserved = _has_reserved_seat(renewal_request.member_id)
            if seat_filter == "reserved" and not has_reserved:
                continue
            if seat_filter == "unreserved" and has_reserved:
                continue
            filtered_renewals.append(renewal_request)
        renewal_requests = filtered_renewals

        filtered_admissions = []
        for member in admissions:
            has_reserved = _has_reserved_seat(member.id)
            if seat_filter == "reserved" and not has_reserved:
                continue
            if seat_filter == "unreserved" and has_reserved:
                continue
            filtered_admissions.append(member)
        admissions = filtered_admissions

    seat_codes = []
    for renewal_request in renewal_requests:
        if renewal_request.desired_seat_number:
            seat_codes.append(renewal_request.desired_seat_number)
        reserved_seat = reserved_seat_by_member.get(renewal_request.member_id)
        if reserved_seat and reserved_seat != "-":
            seat_codes.append(reserved_seat)
    for member in admissions:
        reserved_seat = reserved_seat_by_member.get(member.id)
        if reserved_seat and reserved_seat != "-":
            seat_codes.append(reserved_seat)
    fee_by_code = _seat_fee_by_code(seat_codes)

    rows = []
    total_estimated_amount = 0
    renewal_row_count = 0
    admission_row_count = 0

    for renewal_request in renewal_requests:
        member = renewal_request.member
        if not member:
            continue
        reserved_seat = reserved_seat_by_member.get(member.id, "-")
        fee_seat_code = renewal_request.desired_seat_number or reserved_seat
        monthly_fee = fee_by_code.get(fee_seat_code) if fee_seat_code and fee_seat_code != "-" else None
        estimated_amount = (monthly_fee * renewal_request.duration_months) if monthly_fee is not None else None
        if estimated_amount is not None:
            total_estimated_amount += estimated_amount
        renewal_row_count += 1
        rows.append(
            {
                "entry_type": "Renewal",
                "reference_id": renewal_request.id,
                "event_at": renewal_request.requested_at,
                "member": member,
                "reserved_seat": reserved_seat,
                "requested_seat": renewal_request.desired_seat_number or "-",
                "duration_months": renewal_request.duration_months,
                "status": renewal_request.status,
                "estimated_amount": estimated_amount,
            }
        )

    for member in admissions:
        reserved_seat = reserved_seat_by_member.get(member.id, "-")
        duration_months = 1
        if member.membership_start_date and member.membership_end_date and member.membership_end_date >= member.membership_start_date:
            total_days = (member.membership_end_date - member.membership_start_date).days + 1
            duration_months = max(1, (total_days + 29) // 30)
        monthly_fee = fee_by_code.get(reserved_seat) if reserved_seat and reserved_seat != "-" else None
        estimated_amount = (monthly_fee * duration_months) if monthly_fee is not None else None
        if estimated_amount is not None:
            total_estimated_amount += estimated_amount
        admission_row_count += 1
        rows.append(
            {
                "entry_type": "New Admission",
                "reference_id": member.member_code,
                "event_at": member.registration_date,
                "member": member,
                "reserved_seat": reserved_seat,
                "requested_seat": "-",
                "duration_months": duration_months,
                "status": member.membership_status,
                "estimated_amount": estimated_amount,
            }
        )

    rows.sort(key=lambda row: row["event_at"] or datetime.min, reverse=True)
    for index, row in enumerate(rows, start=1):
        row["sr_no"] = index

    return {
        "month": month_int,
        "year": year_int,
        "month_start": month_start,
        "month_end": month_end,
        "renewal_request_count": renewal_row_count,
        "new_admission_count": admission_row_count,
        "request_count": len(rows),
        "total_estimated_amount": total_estimated_amount,
        "rows": rows,
    }


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role.role_name != "Admin":
            flash("Admin access required.", "danger")
            return redirect(url_for("auth.login"))
        return func(*args, **kwargs)

    return wrapper


@admin_bp.route("/dashboard")
@login_required
@privilege_required("dashboard.view", message="Dashboard access is not assigned to this role.")
def dashboard():
    metrics = calculate_dashboard_metrics()
    return render_template("dashboard/admin_dashboard.html", metrics=metrics)


@admin_bp.route("/dashboard/member-list")
@login_required
@privilege_required("dashboard.view", message="Dashboard access is not assigned to this role.")
def dashboard_member_list():
    category = request.args.get("category", "").strip()
    lab = request.args.get("lab", "").strip() or None

    valid_categories = {
        "attendance": "Today's Total Attendance",
        "active": "Active Members",
        "expired": "Expired Members",
        "inactive": "Inactive Members",
        "expiring_soon": "Admissions Expiring Soon",
        "new_admissions": "New Admissions (Last 7 Days)",
    }
    if category not in valid_categories:
        flash("Invalid dashboard list selection.", "danger")
        return redirect(url_for("admin.dashboard"))

    if lab not in {None, "Lab 1", "Lab 2"}:
        flash("Invalid lab filter.", "danger")
        return redirect(url_for("admin.dashboard"))

    attendance_entries = []
    members = []
    member_seat_by_id = {}
    if category == "attendance":
        attendance_entries = get_dashboard_attendance_entries(lab=lab)
    else:
        members = get_dashboard_member_list(category, lab=lab)
        if category in {"active", "expired", "inactive", "expiring_soon", "new_admissions"}:
            member_seat_by_id = _latest_seat_by_member([member.id for member in members])

    heading = valid_categories[category]
    if lab:
        heading = f"{lab} {heading}"

    return render_template(
        "dashboard/member_names.html",
        heading=heading,
        members=members,
        attendance_entries=attendance_entries,
        show_seat=(category in {"attendance", "active", "expired", "inactive", "expiring_soon", "new_admissions"}),
        member_seat_by_id=member_seat_by_id,
        lab=lab,
        category=category,
        today=date.today(),
    )


@admin_bp.route("/members")
@login_required
@admin_required
def members():
    search = request.args.get("q", "")
    page = request.args.get("page", 1, type=int)
    query = Member.query
    if search:
        query = query.filter(Member.full_name.ilike(f"%{search}%"))
    pagination = query.order_by(Member.registration_date.desc()).paginate(page=page, per_page=12)
    return render_template("admin/members.html", pagination=pagination, search=search)


@admin_bp.route("/members/add", methods=["GET", "POST"])
@login_required
@admin_required
def add_member():
    form = MemberForm()
    if form.validate_on_submit():
        member = Member(
            member_code=f"MBR{Member.query.count()+1:04}",
            full_name=form.full_name.data,
            phone=form.phone.data,
            email=form.email.data.lower(),
            address=form.address.data,
            membership_start_date=form.membership_start_date.data,
            membership_end_date=form.membership_end_date.data,
            membership_status=form.membership_status.data,
            user_id=current_user.id,
        )
        db.session.add(member)
        db.session.commit()
        flash("Member added successfully.", "success")
        return redirect(url_for("admin.members"))
    return render_template("admin/member_form.html", form=form, action="Add")


@admin_bp.route("/seats")
@login_required
@admin_required
def seats():
    search = request.args.get("q", "")
    page = request.args.get("page", 1, type=int)
    query = Seat.query
    if search:
        query = query.filter(Seat.seat_number.ilike(f"%{search}%"))
    pagination = query.order_by(Seat.seat_number).paginate(page=page, per_page=12)
    return render_template("admin/seats.html", pagination=pagination, search=search)


@admin_bp.route("/seats/add", methods=["GET", "POST"])
@login_required
@admin_required
def add_seat():
    form = SeatForm()
    if form.validate_on_submit():
        seat = Seat(
            seat_number=form.seat_number.data,
            seat_type=form.seat_type.data,
            status=form.status.data,
            monthly_fee=form.monthly_fee.data,
            floor=form.floor.data,
            remarks=form.remarks.data,
        )
        db.session.add(seat)
        db.session.commit()
        flash("Seat created successfully.", "success")
        return redirect(url_for("admin.seats"))
    return render_template("admin/seat_form.html", form=form, action="Add")


@admin_bp.route("/bookings")
@login_required
@admin_required
def bookings():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", "")
    query = Booking.query.join(Member).join(Seat)
    if search:
        query = query.filter(
            Member.full_name.ilike(f"%{search}%") | Seat.seat_number.ilike(f"%{search}%")
        )
    pagination = query.order_by(Booking.created_at.desc()).paginate(page=page, per_page=12)
    return render_template("admin/bookings.html", pagination=pagination, search=search)


@admin_bp.route("/bookings/add", methods=["GET", "POST"])
@login_required
@admin_required
def add_booking():
    form = BookingForm()
    form.member_id.choices = [(m.id, m.full_name) for m in Member.query.order_by(Member.full_name).all()]
    form.seat_id.choices = [(s.id, s.seat_number) for s in Seat.query.filter_by(status="Available").order_by(Seat.seat_number).all()]
    if form.validate_on_submit():
        member = Member.query.get(form.member_id.data)
        seat = Seat.query.get(form.seat_id.data)
        validation_error = enforce_booking_rules(member.id, seat.id, form.start_date.data, form.end_date.data)
        if validation_error:
            flash(validation_error, "warning")
            return render_template("admin/booking_form.html", form=form, action="Add")
        booking = Booking(
            member_id=form.member_id.data,
            seat_id=form.seat_id.data,
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            booking_status="Confirmed",
        )
        seat.status = "Occupied"
        db.session.add(booking)
        db.session.commit()
        if form.start_date.data <= date.today() <= form.end_date.data:
            mark_attendance_login(
                member.id,
                seat_label=seat.seat_number,
                booked_by_email=build_booking_source_label(
                    actor_label=current_user.email,
                    client_ip=get_client_ip(request.headers, request.remote_addr),
                ),
            )
            db.session.commit()
        flash("Booking created successfully.", "success")
        return redirect(url_for("admin.bookings"))
    return render_template("admin/booking_form.html", form=form, action="Add")


@admin_bp.route("/payments")
@login_required
@privilege_required("payments.manage", message="Payments access is not assigned to this role.")
def payments():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", "")
    query = Payment.query.join(Member)
    if search:
        query = query.filter(Member.full_name.ilike(f"%{search}%"))
    pagination = query.order_by(Payment.payment_date.desc()).paginate(page=page, per_page=12)
    return render_template("admin/payments.html", pagination=pagination, search=search)


@admin_bp.route("/payments/add", methods=["GET", "POST"])
@login_required
@privilege_required("payments.manage", message="Payments access is not assigned to this role.")
def add_payment():
    form = PaymentForm()
    form.member_id.choices = [(m.id, m.full_name) for m in Member.query.order_by(Member.full_name).all()]
    form.booking_id.choices = [(b.id, f"{b.id} - {b.seat.seat_number}") for b in Booking.query.order_by(Booking.created_at.desc()).all()]
    if form.validate_on_submit():
        payment = Payment(
            member_id=form.member_id.data,
            booking_id=form.booking_id.data,
            amount=form.amount.data,
            payment_method=form.payment_method.data,
            payment_status=form.payment_status.data,
            transaction_reference=form.transaction_reference.data,
        )
        db.session.add(payment)
        db.session.commit()
        flash("Payment recorded successfully.", "success")
        return redirect(url_for("admin.payments"))
    return render_template("admin/payment_form.html", form=form, action="Add")


@admin_bp.route("/reports")
@login_required
@privilege_required("reports.view", message="Reports access is not assigned to this role.")
def reports():
    metrics = calculate_dashboard_metrics()
    revenue_summary = db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0)).scalar()
    monthly_collections = group_payments_by_month()
    membership_month_report = None
    report_lab_filter = request.args.get("report_lab", "all").strip()
    if report_lab_filter not in {"all", "Lab 1", "Lab 2"}:
        report_lab_filter = "all"
    report_seat_filter = request.args.get("report_seat_type", "all").strip().lower()
    if report_seat_filter not in {"all", "reserved", "unreserved"}:
        report_seat_filter = "all"

    if current_user.is_admin:
        membership_month_report = _membership_month_analysis(
            request.args.get("report_month", ""),
            request.args.get("report_year", ""),
            report_lab_filter,
            report_seat_filter,
        )

    return render_template(
        "admin/reports.html",
        active_members=metrics["active_members"],
        expired_members=metrics["expired_members"],
        occupied_seats=metrics["occupied_seats"],
        available_seats=metrics["available_seats"],
        revenue_summary=revenue_summary,
        monthly_collections=monthly_collections,
        membership_month_report=membership_month_report,
        report_lab_filter=report_lab_filter,
        report_seat_filter=report_seat_filter,
    )


@admin_bp.route("/reports/membership-month-export")
@login_required
@admin_required
def export_membership_month_report():
    lab_filter = request.args.get("report_lab", "all").strip()
    if lab_filter not in {"all", "Lab 1", "Lab 2"}:
        lab_filter = "all"
    seat_filter = request.args.get("report_seat_type", "all").strip().lower()
    if seat_filter not in {"all", "reserved", "unreserved"}:
        seat_filter = "all"

    report = _membership_month_analysis(
        request.args.get("report_month", ""),
        request.args.get("report_year", ""),
        lab_filter,
        seat_filter,
    )
    rows = [
        (
            row["sr_no"],
            row["entry_type"],
            row["reference_id"],
            row["event_at"],
            row["member"].member_code,
            row["member"].full_name,
            row["member"].phone,
            row["member"].lab,
            row["reserved_seat"],
            row["requested_seat"],
            row["duration_months"],
            row["status"],
            row["estimated_amount"],
        )
        for row in report["rows"]
    ]
    filename = f"membership_month_report_{report['year']}_{report['month']:02d}.csv"
    headers = [
        "Sr No",
        "Type",
        "Reference ID",
        "Event At",
        "Member Code",
        "Full Name",
        "Phone",
        "Lab",
        "Reserved Seat",
        "Requested Seat",
        "Duration Months",
        "Status",
        "Estimated Amount",
    ]
    return csv_response(filename, rows, headers)


@admin_bp.route("/sanity-report")
@login_required
@admin_required
def sanity_report():
    today = date.today()
    min_allowed_date = today - timedelta(days=14)
    filter_date = _parse_report_date(request.args.get("date", ""), today)
    if filter_date > today:
        filter_date = today
    if filter_date < min_allowed_date:
        filter_date = min_allowed_date
    end_date = filter_date
    start_date = max(min_allowed_date, filter_date - timedelta(days=14))

    lab_filter = request.args.get("lab", "all").strip()
    status_filter = request.args.get("status", "all").strip()
    if lab_filter not in {"all", "Lab 1", "Lab 2"}:
        lab_filter = "all"
    if status_filter not in {"all", "Active", "Expired", "Inactive", "Deleted", "Blacklisted"}:
        status_filter = "all"

    cutoff_date = start_date
    metrics = calculate_dashboard_metrics()

    new_admissions_query = Member.query.filter(
        Member.registration_date.isnot(None),
        db.func.date(Member.registration_date) >= start_date,
        db.func.date(Member.registration_date) <= end_date,
    )
    new_admissions_query = _apply_member_report_filters(new_admissions_query, None if lab_filter == "all" else lab_filter, status_filter if status_filter != "all" else None)
    new_admissions = new_admissions_query.order_by(Member.registration_date.desc(), Member.id.desc()).all()
    new_admissions_reserved_by_id = _latest_seat_by_member([member.id for member in new_admissions])

    lab1_expired_query = Member.query.filter(Member.lab == "Lab 1", Member.membership_status == "Expired")
    lab1_expired_query = _apply_member_report_filters(lab1_expired_query, None if lab_filter == "all" else lab_filter, status_filter if status_filter != "all" else None)
    lab1_expired_members = (
        lab1_expired_query
        .order_by(Member.full_name.asc())
        .all()
    )
    lab2_expired_query = Member.query.filter(Member.lab == "Lab 2", Member.membership_status == "Expired")
    lab2_expired_query = _apply_member_report_filters(lab2_expired_query, None if lab_filter == "all" else lab_filter, status_filter if status_filter != "all" else None)
    lab2_expired_members = (
        lab2_expired_query
        .order_by(Member.full_name.asc())
        .all()
    )
    lab1_inactive_bookings = _members_with_inactive_bookings("Lab 1", filter_date, today)
    lab1_inactive_bookings = [row for row in lab1_inactive_bookings if lab_filter in {"all", "Lab 1"}]
    if status_filter != "all":
        lab1_inactive_bookings = [row for row in lab1_inactive_bookings if row["member"].membership_status == status_filter]

    lab2_inactive_bookings = _members_with_inactive_bookings("Lab 2", filter_date, today)
    lab2_inactive_bookings = [row for row in lab2_inactive_bookings if lab_filter in {"all", "Lab 2"}]
    if status_filter != "all":
        lab2_inactive_bookings = [row for row in lab2_inactive_bookings if row["member"].membership_status == status_filter]

    lab2_booked_reserved_mismatches = _lab2_booked_reserved_mismatches(today)
    if lab_filter == "Lab 1":
        lab2_booked_reserved_mismatches = []
    elif status_filter != "all":
        lab2_booked_reserved_mismatches = [row for row in lab2_booked_reserved_mismatches if row["member"].membership_status == status_filter]

    expired_no_booking_after_expiry = _expired_members_without_bookings_after_expiry(lab_filter, status_filter, days=15)

    lab2_layout = build_seat_layout(lab=2, booking_date=today)
    lab2_empty_seats = [
        seat["seat_label"]
        for column in lab2_layout.values()
        for seat in column
        if seat["status"] == "Available" and not seat["is_reserved"]
    ]

    pending_renewals_query = RenewalRequest.query.filter_by(status="Pending")
    if lab_filter in {"Lab 1", "Lab 2"}:
        pending_renewals_query = pending_renewals_query.join(Member).filter(Member.lab == lab_filter)
    pending_renewals_query = pending_renewals_query.filter(
        db.func.date(RenewalRequest.requested_at) >= start_date,
        db.func.date(RenewalRequest.requested_at) <= end_date,
    )
    pending_renewals = pending_renewals_query.order_by(RenewalRequest.requested_at.desc(), RenewalRequest.id.desc()).all()

    return render_template(
        "admin/sanity_report.html",
        page_title="Sanity Report",
        page_description="Administrative health check across admissions, attendance, bookings, and renewals.",
        metrics=metrics,
        new_admissions=new_admissions,
        new_admissions_reserved_by_id=new_admissions_reserved_by_id,
        lab1_expired_members=lab1_expired_members,
        lab1_inactive_bookings=lab1_inactive_bookings,
        lab2_expired_members=lab2_expired_members,
        lab2_inactive_bookings=lab2_inactive_bookings,
        lab2_booked_reserved_mismatches=lab2_booked_reserved_mismatches,
        lab2_empty_seats=lab2_empty_seats,
        pending_renewals=pending_renewals,
        expired_no_booking_after_expiry=expired_no_booking_after_expiry,
        today=today,
        cutoff_date=cutoff_date,
        min_allowed_date=min_allowed_date,
        filter_date=filter_date,
        start_date=start_date,
        end_date=end_date,
        lab_filter=lab_filter,
        status_filter=status_filter,
    )


@admin_bp.route("/logs")
@login_required
@admin_required
def audit_logs():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", "").strip()
    method = request.args.get("method", "").strip().upper()

    query = AuditLog.query.join(User)
    if search:
        query = query.filter(
            User.username.ilike(f"%{search}%")
            | User.email.ilike(f"%{search}%")
            | AuditLog.endpoint.ilike(f"%{search}%")
            | AuditLog.path.ilike(f"%{search}%")
        )
    if method in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        query = query.filter(AuditLog.method == method)

    pagination = query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).paginate(page=page, per_page=25)
    return render_template("admin/audit_logs.html", pagination=pagination, search=search, method=method)


def csv_response(filename, rows, headers):
    csv_file = StringIO()
    writer = csv.writer(csv_file)
    writer.writerow(headers)
    writer.writerows(rows)
    csv_file.seek(0)
    return send_file(
        csv_file,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
    )


@admin_bp.route("/export/members")
@login_required
@admin_required
def export_members():
    rows = [(m.member_code, m.full_name, m.email, m.phone, m.address, m.membership_status, m.registration_date) for m in Member.query.order_by(Member.id).all()]
    return csv_response("members.csv", rows, ["Member Code", "Full Name", "Email", "Phone", "Address", "Status", "Registered At"])


@admin_bp.route("/export/seats")
@login_required
@admin_required
def export_seats():
    rows = [(s.seat_number, s.seat_type, s.status, s.monthly_fee, s.floor, s.remarks) for s in Seat.query.order_by(Seat.id).all()]
    return csv_response("seats.csv", rows, ["Seat Number", "Type", "Status", "Monthly Fee", "Floor", "Remarks"])


@admin_bp.route("/export/bookings")
@login_required
@admin_required
def export_bookings():
    rows = [
        (b.id, b.member.full_name, b.seat.seat_number, b.start_date, b.end_date, b.booking_status, b.created_at)
        for b in Booking.query.order_by(Booking.id).all()
    ]
    return csv_response("bookings.csv", rows, ["Booking ID", "Member", "Seat", "Start Date", "End Date", "Status", "Created At"])


@admin_bp.route("/users")
@login_required
@privilege_required("users.manage", message="User management access is not assigned to this role.")
def users():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", "")
    query = User.query.join(Role)
    if search:
        query = query.filter(User.username.ilike(f"%{search}%") | User.email.ilike(f"%{search}%") | Role.role_name.ilike(f"%{search}%"))
    pagination = query.order_by(User.created_at.desc()).paginate(page=page, per_page=12)
    return render_template("admin/users.html", pagination=pagination, search=search)


def _get_or_create_archived_member_user():
    archived = User.query.filter_by(email="archived-member@local.invalid").first()
    if archived:
        return archived

    member_role = Role.query.filter_by(role_name="Member").first()
    if not member_role:
        member_role = Role(role_name="Member", description="Library member")
        db.session.add(member_role)
        db.session.flush()

    archived = User(
        username="archived_member_user",
        email="archived-member@local.invalid",
        role_id=member_role.id,
        is_active=False,
        is_locked=True,
    )
    archived.set_password("archived-member")
    db.session.add(archived)
    db.session.flush()
    return archived


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@privilege_required("users.manage", message="User management access is not assigned to this role.")
def delete_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash("You cannot delete your own account.", "warning")
        return redirect(url_for("admin.users"))

    if user.role and user.role.is_admin:
        admin_count = User.query.join(Role).filter(Role.role_name == "Admin").count()
        if admin_count <= 1:
            flash("Cannot delete the last admin user.", "warning")
            return redirect(url_for("admin.users"))

    linked_members = Member.query.filter_by(user_id=user.id).all()
    if linked_members:
        non_deleted_members = [member for member in linked_members if member.membership_status != "Deleted"]
        if non_deleted_members:
            flash(
                "This user is linked to an active admission record. Delete admission first or disable login from admissions.",
                "warning",
            )
            return redirect(url_for("admin.users"))

        archived_user = _get_or_create_archived_member_user()
        if archived_user.id == user.id:
            flash("Archived user cannot be deleted.", "warning")
            return redirect(url_for("admin.users"))

        for member in linked_members:
            member.user_id = archived_user.id

    # Keep booking history but detach user reference so deletion is possible.
    DailySeatBooking.query.filter_by(booked_by_user_id=user.id).update(
        {DailySeatBooking.booked_by_user_id: None},
        synchronize_session=False,
    )

    try:
        db.session.delete(user)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("User cannot be deleted because related records still exist.", "danger")
        return redirect(url_for("admin.users"))

    flash("User deleted successfully.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/add", methods=["GET", "POST"])
@login_required
@privilege_required("users.manage", message="User management access is not assigned to this role.")
def add_user():
    form = UserForm()
    form.role_id.choices = [(r.id, r.role_name) for r in Role.query.order_by(Role.role_name).all()]
    if form.validate_on_submit():
        if User.query.filter((User.username == form.username.data) | (User.email == form.email.data.lower())).first():
            flash("Username or email already exists.", "warning")
            return render_template("admin/user_form.html", form=form, action="Add")
        user = User(username=form.username.data, email=form.email.data.lower(), role_id=form.role_id.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash("User created successfully.", "success")
        return redirect(url_for("admin.users"))
    return render_template("admin/user_form.html", form=form, action="Add")


@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@privilege_required("users.manage", message="User management access is not assigned to this role.")
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    form = UserEditForm()
    form.role_id.choices = [(r.id, r.role_name) for r in Role.query.order_by(Role.role_name).all()]

    if request.method == "GET":
        form.username.data = user.username
        form.email.data = user.email
        form.role_id.data = user.role_id
        form.is_active.data = "true" if user.is_active else "false"

    if form.validate_on_submit():
        existing_username = User.query.filter(User.username == form.username.data, User.id != user.id).first()
        if existing_username:
            flash("Username already exists.", "warning")
            return render_template("admin/user_form.html", form=form, action="Edit")

        existing_email = User.query.filter(User.email == form.email.data.lower(), User.id != user.id).first()
        if existing_email:
            flash("Email already exists.", "warning")
            return render_template("admin/user_form.html", form=form, action="Edit")

        user.username = form.username.data
        user.email = form.email.data.lower()
        user.role_id = form.role_id.data
        user.is_active = form.is_active.data == "true"

        if form.password.data:
            user.set_password(form.password.data)
            if hasattr(user, "failed_login_attempts"):
                user.failed_login_attempts = 0
            if hasattr(user, "is_locked"):
                user.is_locked = False

        db.session.commit()
        flash("User updated successfully.", "success")
        return redirect(url_for("admin.users"))

    return render_template("admin/user_form.html", form=form, action="Edit")


@admin_bp.route("/roles")
@login_required
@privilege_required("roles.manage", message="Role management access is not assigned to this role.")
def roles():
    roles = Role.query.order_by(Role.role_name).all()
    return render_template("admin/roles.html", roles=roles)


@admin_bp.route("/roles/add", methods=["GET", "POST"])
@login_required
@privilege_required("roles.manage", message="Role management access is not assigned to this role.")
def add_role():
    form = RoleForm()
    if form.validate_on_submit():
        if Role.query.filter_by(role_name=form.role_name.data).first():
            flash("Role already exists.", "warning")
            return render_template("admin/role_form.html", form=form, action="Add")
        selected_privileges = sorted(set(form.privileges.data or []))
        role = Role(
            role_name=form.role_name.data,
            description=form.description.data,
            privileges=",".join(selected_privileges),
        )
        db.session.add(role)
        db.session.commit()
        flash("Role created successfully.", "success")
        return redirect(url_for("admin.roles"))
    return render_template("admin/role_form.html", form=form, action="Add")


@admin_bp.route("/roles/<int:role_id>/delete", methods=["POST"])
@login_required
@privilege_required("roles.manage", message="Role management access is not assigned to this role.")
def delete_role(role_id):
    role = Role.query.get_or_404(role_id)

    if User.query.filter_by(role_id=role.id).count():
        flash("Cannot delete a role that is assigned to users. Reassign those users first.", "warning")
        return redirect(url_for("admin.roles"))

    db.session.delete(role)
    db.session.commit()
    flash("Role deleted successfully.", "success")
    return redirect(url_for("admin.roles"))


@admin_bp.route("/export/payments")
@login_required
@privilege_required("payments.manage", message="Payments access is not assigned to this role.")
def export_payments():
    rows = [
        (p.transaction_reference, p.member.full_name, p.booking.id, p.amount, p.payment_method, p.payment_date, p.payment_status)
        for p in Payment.query.order_by(Payment.id).all()
    ]
    return csv_response("payments.csv", rows, ["Transaction", "Member", "Booking ID", "Amount", "Method", "Date", "Status"])
