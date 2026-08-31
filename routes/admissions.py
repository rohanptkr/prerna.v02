from datetime import date, datetime, timedelta
import csv
import io
import re
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from openpyxl import Workbook
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError

from application import db
from models import Booking, DailySeatBooking, Member, MembershipHistory, RenewalRequest, Role, Seat, User
from services.access_control import privilege_required, privilege_required_any
from services.booking_service import enforce_booking_rules, sync_membership_statuses
from services.dashboard_service import _active_filter
from services.daily_seat_service import ist_today

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


def _subsequence_like_pattern(value):
    compact = re.sub(r"\s+", "", str(value or "")).lower()
    if not compact:
        return None
    return "%" + "%".join(compact) + "%"


def _canonical_seat_token(value):
    if value is None:
        return None
    normalized = re.sub(r"[^A-Z0-9]", "", str(value).upper())
    if not normalized:
        return None
    if len(normalized) >= 2 and normalized[0].isalpha() and normalized[1:].isdigit():
        return f"{normalized[0]}{int(normalized[1:])}"
    return normalized


def _normalize_aadhaar(value):
    return re.sub(r"\D", "", str(value or ""))


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
    sync_membership_statuses(expiry_days=15)

    query = Member.query
    if search:
        search_text = search.strip()
        compact_search = re.sub(r"\s+", "", search_text).lower()
        search_tokens = [token for token in re.split(r"\s+", search_text) if token]

        clauses = [
            Member.full_name.ilike(f"%{search_text}%"),
            Member.member_code.ilike(f"%{search_text}%"),
            Member.email.ilike(f"%{search_text}%"),
            Member.phone.ilike(f"%{search_text}%"),
            Member.aadhaar_number.ilike(f"%{search_text}%"),
            Member.school_name.ilike(f"%{search_text}%"),
        ]

        normalized_full_name = func.lower(func.replace(Member.full_name, " ", ""))
        if len(compact_search) >= 2:
            clauses.append(normalized_full_name.ilike(f"%{compact_search}%"))
            subseq_pattern = _subsequence_like_pattern(compact_search)
            if subseq_pattern:
                # Allows tolerant matching when one or more letters are missing (e.g. gpl -> gopal).
                clauses.append(normalized_full_name.ilike(subseq_pattern))

        for token in search_tokens:
            compact_token = re.sub(r"\s+", "", token).lower()
            if len(compact_token) < 2:
                continue
            clauses.append(normalized_full_name.ilike(f"%{compact_token}%"))
            token_subseq_pattern = _subsequence_like_pattern(compact_token)
            if token_subseq_pattern:
                clauses.append(normalized_full_name.ilike(token_subseq_pattern))

        seat_token = _canonical_seat_token(search_text)
        if seat_token and len(seat_token) >= 2 and seat_token[0].isalpha() and seat_token[1:].isdigit():
            seat_variants = _seat_number_variants(seat_token)
            seat_match_clauses = [Seat.seat_number.ilike(variant) for variant in seat_variants]
            member_ids_by_seat = (
                db.session.query(Booking.member_id)
                .join(Seat, Booking.seat_id == Seat.id)
                .filter(
                    Booking.booking_status == "Confirmed",
                    Booking.end_date >= date.today(),
                    or_(*seat_match_clauses),
                )
                .distinct()
            )
            clauses.append(Member.id.in_(member_ids_by_seat))

        query = query.filter(or_(*clauses))
    if status_filter:
        if status_filter == "Expiring Soon":
            today = ist_today()
            query = query.filter(
                Member.membership_status == "Active",
                Member.membership_end_date.isnot(None),
                Member.membership_end_date >= today,
                Member.membership_end_date <= today + timedelta(days=7),
            )
        elif status_filter == "Active":
            # Use date-aware active filter to match dashboard logic
            today = ist_today()
            query = query.filter(_active_filter(today))
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


def _apply_admissions_sort(query, sort_by):
    if sort_by == "oldest":
        return query.order_by(Member.registration_date.asc(), Member.id.asc())
    if sort_by == "name_asc":
        return query.order_by(func.lower(Member.full_name).asc(), Member.id.asc())
    if sort_by == "name_desc":
        return query.order_by(func.lower(Member.full_name).desc(), Member.id.desc())
    if sort_by == "expiry_soonest":
        return query.order_by(Member.membership_end_date.asc().nullslast(), Member.id.desc())
    if sort_by == "expiry_latest":
        return query.order_by(Member.membership_end_date.desc().nullslast(), Member.id.desc())

    return query.order_by(Member.registration_date.desc(), Member.id.desc())


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


def _default_renewal_start_date(member):
    if member and member.membership_end_date:
        return member.membership_end_date + timedelta(days=1)
    return date.today()


def _apply_member_renewal(member, duration_months, custom_start_date=None, custom_end_date=None):
    """Apply renewal with optional custom dates. If custom dates provided, use them; otherwise calculate from duration."""
    if custom_start_date and custom_end_date:
        # Use admin-specified dates
        base_date = custom_start_date
        new_end_date = custom_end_date
    else:
        # Use default renewal logic
        today = date.today()
        if member.membership_end_date and member.membership_end_date >= today:
            # Continue from next day after current expiry to avoid overlap.
            base_date = member.membership_end_date + timedelta(days=1)
        else:
            base_date = today
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
        f"Renewed until {new_end_date.isoformat()}",
    )

    if member.user:
        member.user.is_active = True
        if hasattr(member.user, "failed_login_attempts"):
            member.user.failed_login_attempts = 0
        if hasattr(member.user, "is_locked"):
            member.user.is_locked = False


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


def _latest_active_reservation_for_member(member_id):
    if not member_id:
        return None
    return (
        Booking.query.filter(
            Booking.member_id == member_id,
            Booking.booking_status == "Confirmed",
            Booking.end_date >= date.today(),
        )
        .order_by(Booking.end_date.desc(), Booking.id.desc())
        .first()
    )


@admissions_bp.route("/admissions")
@login_required
@privilege_required("admissions.manage", message="Admissions access is not assigned to this role.")
def index():
    search = request.args.get("q", "")
    status_filter = request.args.get("status", "")
    lab_filter = request.args.get("lab", "")
    month = request.args.get("month", "")
    year = request.args.get("year", "")
    sort_by = request.args.get("sort", "newest")
    page = request.args.get("page", 1, type=int)
    query = _build_admissions_query(search, status_filter, month, year, lab_filter)
    pagination = _apply_admissions_sort(query, sort_by).paginate(page=page, per_page=15)

    reservation_by_member = _reservation_by_member_for_members(pagination.items)

    return render_template(
        "admissions/index.html",
        pagination=pagination,
        search=search,
        status_filter=status_filter,
        lab_filter=lab_filter,
        month=month,
        year=year,
        sort_by=sort_by,
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
    sort_by = request.args.get("sort", "newest")
    page = request.args.get("page", 1, type=int)
    query = _build_admissions_query(search, status_filter, month, year, lab_filter)
    pagination = _apply_admissions_sort(query, sort_by).paginate(page=page, per_page=15)

    return render_template(
        "admissions/index.html",
        pagination=pagination,
        search=search,
        status_filter=status_filter,
        lab_filter=lab_filter,
        month=month,
        year=year,
        sort_by=sort_by,
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
            if seat.status != "Blocked":
                seat.status = "Occupied" if has_active_booking else "Available"

    db.session.commit()
    flash(f"Admission deleted for {member_name} ({member_code}) and kept in admission log.", "success")
    return redirect(url_for("admissions.delete_admission_index"))


def _active_reservations_query():
    return Booking.query.join(Member).join(Seat).filter(
        Booking.booking_status == "Confirmed",
        Booking.end_date >= date.today(),
    )


def _ensure_admin_for_block_seats():
    if current_user.is_admin:
        return None
    flash("Only admin users can block or unblock seats.", "danger")
    return redirect(url_for("admissions.reserve_seats"))


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


@admissions_bp.route("/admissions/block-seats")
@login_required
@privilege_required("admissions.manage", message="Block Seat access is not assigned to this role.")
def block_seats():
    admin_guard = _ensure_admin_for_block_seats()
    if admin_guard:
        return admin_guard

    search = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "Blocked").strip()

    query = Seat.query
    if search:
        query = query.filter(Seat.seat_number.ilike(f"%{search}%"))

    if status_filter in ("Blocked", "Available", "Occupied"):
        query = query.filter(Seat.status == status_filter)
    else:
        status_filter = "All"

    seats = query.order_by(Seat.seat_number.asc()).all()
    blocked_count = Seat.query.filter(Seat.status == "Blocked").count()

    return render_template(
        "admissions/block_seats.html",
        seats=seats,
        blocked_count=blocked_count,
        search=search,
        status_filter=status_filter,
    )


@admissions_bp.route("/admissions/block-seats/block", methods=["POST"])
@login_required
@privilege_required("admissions.manage", message="Block Seat access is not assigned to this role.")
def block_seat():
    admin_guard = _ensure_admin_for_block_seats()
    if admin_guard:
        return admin_guard

    seat_id = request.form.get("seat_id", type=int)
    seat_number_raw = (request.form.get("seat_number") or "").strip()

    seat = Seat.query.get(seat_id) if seat_id else None
    if not seat:
        seat_token = _canonical_seat_token(seat_number_raw)
        if not seat_token or not _is_valid_reservation_seat_format(seat_token):
            flash("Enter a valid seat number (A1-A80 or B1-B85).", "danger")
            return redirect(url_for("admissions.block_seats"))

        seat = _find_seat_by_number(seat_token)
        if not seat:
            seat = _create_missing_seat_for_reservation(seat_token)

    if not seat:
        flash("Seat not found.", "danger")
        return redirect(url_for("admissions.block_seats"))

    if seat.status == "Blocked":
        flash(f"Seat {seat.seat_number} is already blocked.", "warning")
        return redirect(url_for("admissions.block_seats"))

    if seat.status == "Occupied":
        flash(f"Seat {seat.seat_number} is currently occupied. Unreserve it before blocking.", "danger")
        return redirect(url_for("admissions.block_seats"))

    daily_storage_number = None
    seat_token = _canonical_seat_token(seat.seat_number)
    if seat_token and seat_token[0] == "A" and seat_token[1:].isdigit():
        daily_storage_number = int(seat_token[1:])
    elif seat_token and seat_token[0] == "B" and seat_token[1:].isdigit():
        daily_storage_number = 1000 + int(seat_token[1:])

    if daily_storage_number is not None:
        is_booked_today = (
            DailySeatBooking.query.filter_by(
                seat_number=daily_storage_number,
                booking_date=ist_today(),
            ).first()
            is not None
        )
        if is_booked_today:
            flash(f"Seat {seat.seat_number} is booked for today. Unbook it first, then block.", "danger")
            return redirect(url_for("admissions.block_seats"))

    seat.status = "Blocked"
    db.session.commit()
    flash(f"Seat {seat.seat_number} blocked successfully.", "success")
    return redirect(url_for("admissions.block_seats"))


@admissions_bp.route("/admissions/block-seats/unblock/<int:seat_id>", methods=["POST"])
@login_required
@privilege_required("admissions.manage", message="Block Seat access is not assigned to this role.")
def unblock_seat(seat_id):
    admin_guard = _ensure_admin_for_block_seats()
    if admin_guard:
        return admin_guard

    seat = Seat.query.get_or_404(seat_id)
    if seat.status != "Blocked":
        flash(f"Seat {seat.seat_number} is not blocked.", "warning")
        return redirect(url_for("admissions.block_seats"))

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
    flash(f"Seat {seat.seat_number} unblocked successfully.", "success")
    return redirect(url_for("admissions.block_seats"))


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
    if seat.status == "Blocked":
        flash(f"Seat {seat.seat_number} is blocked and cannot be reserved.", "danger")
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
        if booking.seat.status != "Blocked":
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
    sort_by = request.args.get("sort", "newest")
    export_format = request.args.get("format", "csv").lower()

    members = _apply_admissions_sort(
        _build_admissions_query(search, status_filter, month, year, lab_filter),
        sort_by,
    ).all()
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
        aadhaar_number = _normalize_aadhaar(request.form.get("aadhaar_number", "").strip())
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
        existing_member_by_aadhaar = Member.query.filter_by(aadhaar_number=aadhaar_number).first()
        if existing_member_by_aadhaar:
            errors.append(
                f"Admission already exists for this Aadhaar number (Member ID: {existing_member_by_aadhaar.member_code})."
            )

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

        # New admissions use fixed 30-day billing blocks; start date counts as day 1.
        end_date = start_date + timedelta(days=(30 * duration_months) - 1)

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
            elif selected_seat.status == "Blocked":
                errors.append(f"Seat {selected_seat.seat_number} is blocked and cannot be assigned.")
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

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Admission already exists for this Aadhaar number.", "danger")
            return render_template(
                "admissions/new.html",
                form=request.form,
                today=date.today(),
                available_seats=available_seats,
            )

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
        aadhaar_number = _normalize_aadhaar(request.form.get("aadhaar_number", "").strip())
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
        reserved_seat_number = request.form.get("reserved_seat_number", "").strip()

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
        if membership_status not in ("Active", "Expired", "Inactive", "Deleted"):
            errors.append("Please select a valid membership status.")

        existing_user = User.query.filter(User.email == email, User.id != member.user_id).first()
        if existing_user:
            errors.append("A user with this email already exists.")
        existing_member = Member.query.filter(Member.aadhaar_number == aadhaar_number, Member.id != member.id).first()
        if existing_member:
            errors.append(
                f"Admission already exists for this Aadhaar number (Member ID: {existing_member.member_code})."
            )

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

        selected_seat = None
        seat_token = None
        if reserved_seat_number:
            seat_token = _canonical_seat_token(reserved_seat_number)
            if not seat_token or not _is_valid_reservation_seat_format(seat_token, lab):
                errors.append("Invalid seat format. Use A1 to A80 for Lab 1 or B1 to B85 for Lab 2.")
            else:
                selected_seat = _find_seat_by_number(seat_token)
                if not selected_seat:
                    selected_seat = _create_missing_seat_for_reservation(seat_token)
                if not selected_seat:
                    errors.append("Reserved seat number is invalid.")
                elif selected_seat.status == "Blocked":
                    errors.append(f"Seat {selected_seat.seat_number} is blocked and cannot be assigned.")
                elif lab == "Lab 1" and not selected_seat.seat_number.upper().startswith("A"):
                    errors.append("Please enter a Lab 1 seat number (example: A12).")
                elif lab == "Lab 2" and not selected_seat.seat_number.upper().startswith("B"):
                    errors.append("Please enter a Lab 2 seat number (example: B12).")

            if not membership_start_date or not membership_end_date:
                errors.append("Membership start and end date are required to reserve/assign a seat.")

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

        if reserved_seat_number and selected_seat:
            released_seat_ids = set()

            conflicting_seat_bookings = (
                Booking.query.filter(
                    Booking.seat_id == selected_seat.id,
                    Booking.booking_status == "Confirmed",
                    Booking.member_id != member.id,
                    Booking.end_date >= membership_start_date,
                    Booking.start_date <= membership_end_date,
                ).all()
            )
            for booking in conflicting_seat_bookings:
                booking.booking_status = "Cancelled"
                released_seat_ids.add(booking.seat_id)

            member_other_bookings = (
                Booking.query.filter(
                    Booking.member_id == member.id,
                    Booking.booking_status == "Confirmed",
                    Booking.seat_id != selected_seat.id,
                    Booking.end_date >= membership_start_date,
                    Booking.start_date <= membership_end_date,
                ).all()
            )
            for booking in member_other_bookings:
                booking.booking_status = "Cancelled"
                released_seat_ids.add(booking.seat_id)

            existing_member_seat_booking = (
                Booking.query.filter(
                    Booking.member_id == member.id,
                    Booking.seat_id == selected_seat.id,
                    Booking.booking_status == "Confirmed",
                )
                .order_by(Booking.id.desc())
                .first()
            )
            if existing_member_seat_booking:
                existing_member_seat_booking.start_date = membership_start_date
                existing_member_seat_booking.end_date = membership_end_date
            else:
                db.session.add(
                    Booking(
                        member_id=member.id,
                        seat_id=selected_seat.id,
                        start_date=membership_start_date,
                        end_date=membership_end_date,
                        booking_status="Confirmed",
                    )
                )

            selected_seat.status = "Occupied"

            if released_seat_ids:
                released_seats = Seat.query.filter(Seat.id.in_(list(released_seat_ids))).all()
                for released_seat in released_seats:
                    has_active_booking = (
                        Booking.query.filter(
                            Booking.seat_id == released_seat.id,
                            Booking.booking_status == "Confirmed",
                            Booking.end_date >= date.today(),
                        ).first()
                        is not None
                    )
                    if released_seat.status != "Blocked":
                        released_seat.status = "Occupied" if has_active_booking else "Available"

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Admission already exists for this Aadhaar number.", "danger")
            form = dict(request.form)
            return render_template("admissions/edit.html", member=member, form=form)
        flash(f"Admission updated for {member.full_name}.", "success")
        return redirect(url_for("admissions.index"))

    current_reservation = _latest_active_reservation_for_member(member.id)
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
        "reserved_seat_number": current_reservation.seat.seat_number if current_reservation and current_reservation.seat else "",
    }
    return render_template("admissions/edit.html", member=member, form=form)


@admissions_bp.route("/admissions/renew/<int:member_id>", methods=["GET", "POST"])
@login_required
@privilege_required("admissions.manage", message="Admissions access is not assigned to this role.")
def renew(member_id):
    member = Member.query.get_or_404(member_id)
    if request.method == "POST":
        requested_duration = int(request.form.get("duration_months", 1))

        if not current_user.is_admin:
            pending_exists = RenewalRequest.query.filter_by(member_id=member.id, status="Pending").first()
            if pending_exists:
                flash("A renewal request is already pending for this member.", "warning")
                return redirect(url_for("admissions.renew", member_id=member.id))

            renewal_request = RenewalRequest(
                member_id=member.id,
                requested_by_user_id=current_user.id,
                duration_months=1,
                status="Pending",
            )
            db.session.add(renewal_request)
            db.session.commit()
            flash("Renewal request for 1 month submitted to admin for approval.", "info")
            return redirect(url_for("admissions.index"))

        duration_months = requested_duration if requested_duration in (1, 2, 3, 6, 12) else 1
        _apply_member_renewal(member, duration_months)
        db.session.commit()
        flash(f"Membership renewed until {member.membership_end_date}.", "success")
        return redirect(url_for("admissions.index"))

    pending_request = RenewalRequest.query.filter_by(member_id=member.id, status="Pending").first()
    return render_template(
        "admissions/renew.html",
        member=member,
        today=date.today(),
        pending_request=pending_request,
    )


@admissions_bp.route("/admissions/renewal-requests")
@login_required
@privilege_required("admissions.manage", message="Admissions access is not assigned to this role.")
def renewal_requests():
    if not current_user.is_admin:
        flash("Only admin can review renewal requests.", "danger")
        return redirect(url_for("admissions.index"))

    requests = (
        RenewalRequest.query.filter_by(status="Pending")
        .order_by(RenewalRequest.requested_at.desc(), RenewalRequest.id.desc())
        .all()
    )
    return render_template("admissions/renewal_requests.html", requests=requests, now=datetime.utcnow())


@admissions_bp.route("/admissions/renewal-requests/<int:request_id>/edit", methods=["GET", "POST"])
@login_required
@privilege_required("admissions.manage", message="Admissions access is not assigned to this role.")
def edit_renewal_request(request_id):
    if not current_user.is_admin:
        flash("Only admin can edit renewal requests.", "danger")
        return redirect(url_for("admissions.index"))

    renewal_request = RenewalRequest.query.get_or_404(request_id)
    if renewal_request.status != "Pending":
        flash("This renewal request is already processed and cannot be edited.", "warning")
        return redirect(url_for("admissions.renewal_requests"))

    member = renewal_request.member
    if not member:
        flash("Member not found for this renewal request.", "danger")
        return redirect(url_for("admissions.renewal_requests"))

    if request.method == "POST":
        action = request.form.get("action", "save").strip().lower()
        proposed_start_date_str = request.form.get("proposed_start_date", "").strip()
        proposed_end_date_str = request.form.get("proposed_end_date", "").strip()

        if action == "reject":
            if _process_renewal_request_action(renewal_request, "reject"):
                flash(f"Renewal request rejected for {member.full_name}. No changes made to membership.", "warning")
            return redirect(url_for("admissions.renewal_requests"))

        errors = []
        proposed_start_date = None
        proposed_end_date = None

        if proposed_start_date_str:
            try:
                proposed_start_date = datetime.strptime(proposed_start_date_str, "%d/%m/%Y").date()
            except ValueError:
                errors.append("Proposed start date is invalid. Use format dd/mm/yyyy.")

        if proposed_end_date_str:
            try:
                proposed_end_date = datetime.strptime(proposed_end_date_str, "%d/%m/%Y").date()
            except ValueError:
                errors.append("Proposed end date is invalid. Use format dd/mm/yyyy.")

        if proposed_start_date and proposed_end_date:
            if proposed_end_date < proposed_start_date:
                errors.append("Proposed end date cannot be before start date.")

        if errors:
            for err in errors:
                flash(err, "danger")
            form = {
                "proposed_start_date": proposed_start_date_str or _default_renewal_start_date(member).strftime('%d/%m/%Y'),
                "proposed_end_date": proposed_end_date_str or "",
            }
            return render_template("admissions/edit_renewal_request.html", renewal_request=renewal_request, member=member, form=form, today=date.today())

        renewal_request.proposed_start_date = proposed_start_date
        renewal_request.proposed_end_date = proposed_end_date
        db.session.commit()

        if action == "approve":
            if _process_renewal_request_action(renewal_request, "approve"):
                flash(f"Renewal approved for {member.full_name}. Membership valid until {member.membership_end_date}.", "success")
            return redirect(url_for("admissions.renewal_requests"))

        flash(f"Renewal details updated for {member.full_name}. Ready to approve.", "success")
        return redirect(url_for("admissions.renewal_requests"))

    form = {
        "proposed_start_date": renewal_request.proposed_start_date.strftime('%d/%m/%Y') if renewal_request.proposed_start_date else _default_renewal_start_date(member).strftime('%d/%m/%Y'),
        "proposed_end_date": renewal_request.proposed_end_date.strftime('%d/%m/%Y') if renewal_request.proposed_end_date else "",
    }
    return render_template("admissions/edit_renewal_request.html", renewal_request=renewal_request, member=member, form=form, today=date.today())


@admissions_bp.route("/admissions/renewal-requests/<int:request_id>/approve", methods=["POST"])
@login_required
@privilege_required("admissions.manage", message="Admissions access is not assigned to this role.")
def approve_renewal_request(request_id):
    if not current_user.is_admin:
        flash("Only admin can approve renewal requests.", "danger")
        return redirect(url_for("admissions.index"))

    renewal_request = RenewalRequest.query.get_or_404(request_id)
    if _process_renewal_request_action(renewal_request, "approve"):
        member = renewal_request.member
        flash(f"Renewal approved for {member.full_name}. Membership valid until {member.membership_end_date}.", "success")

    return redirect(url_for("admissions.renewal_requests"))


@admissions_bp.route("/renewal-request/<int:request_id>/reject", methods=["POST"])
@login_required
@privilege_required("admissions.manage", message="Admissions access is not assigned to this role.")
def reject_renewal_request(request_id):
    if not current_user.is_admin:
        flash("Only admin can reject renewal requests.", "danger")
        return redirect(url_for("admissions.index"))

    renewal_request = RenewalRequest.query.get_or_404(request_id)
    if _process_renewal_request_action(renewal_request, "reject"):
        member = renewal_request.member
        flash(f"Renewal request rejected for {member.full_name}. No changes made to membership.", "warning")

    return redirect(url_for("admissions.renewal_requests"))


@admissions_bp.route("/admissions/renewal-requests/bulk-action", methods=["POST"])
@login_required
@privilege_required("admissions.manage", message="Admissions access is not assigned to this role.")
def bulk_renewal_request_action():
    if not current_user.is_admin:
        flash("Only admin can manage renewal requests.", "danger")
        return redirect(url_for("admissions.index"))

    action = request.form.get("bulk_action", "").strip().lower()
    request_ids = request.form.getlist("request_ids")

    if action not in {"approve", "reject"}:
        flash("Please choose approve or reject for the selected renewal requests.", "danger")
        return redirect(url_for("admissions.renewal_requests"))

    if not request_ids:
        flash("Please select at least one renewal request.", "warning")
        return redirect(url_for("admissions.renewal_requests"))

    processed = 0
    skipped = 0
    for request_id in request_ids:
        renewal_request = RenewalRequest.query.get(request_id)
        if not renewal_request:
            skipped += 1
            continue
        if _process_renewal_request_action(renewal_request, action):
            processed += 1
        else:
            skipped += 1

    flash(f"{action.title()}d {processed} renewal request(s).", "success" if action == "approve" else "warning")
    if skipped:
        flash(f"Skipped {skipped} request(s) that were missing or already processed.", "info")

    return redirect(url_for("admissions.renewal_requests"))


def _process_renewal_request_action(renewal_request, action):
    if renewal_request.status != "Pending":
        flash("This renewal request is already processed.", "warning")
        return False

    member = renewal_request.member
    if not member:
        flash("Member not found for this renewal request.", "danger")
        return False

    if action == "approve":
        if renewal_request.proposed_start_date and renewal_request.proposed_end_date:
            _apply_member_renewal(member, 1, renewal_request.proposed_start_date, renewal_request.proposed_end_date)
        else:
            _apply_member_renewal(member, renewal_request.duration_months)
        renewal_request.status = "Approved"
    elif action == "reject":
        renewal_request.status = "Rejected"
    else:
        flash("Invalid renewal request action.", "danger")
        return False

    renewal_request.reviewed_at = datetime.utcnow()
    renewal_request.reviewed_by_user_id = current_user.id
    db.session.commit()
    return True
