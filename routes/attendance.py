from datetime import date, timedelta
import csv
import io
import re
from decimal import Decimal
from openpyxl import Workbook

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from application import db
from models import Booking, Seat
from models.attendance import Attendance
from models.member import Member
from services.access_control import privilege_required
from services.daily_seat_service import cleanup_old_attendance, ist_today, storage_seat_number_from_code

attendance_bp = Blueprint("attendance", __name__, template_folder="../templates")


def _lab_from_attendance_record(record):
    fallback_lab = record.member.lab if record.member and record.member.lab else ""
    seat_label = (record.seat_label or "").strip().upper()
    if not seat_label:
        return fallback_lab

    if seat_label.startswith("A"):
        return "Lab 1"
    if seat_label.startswith("B"):
        return "Lab 2"

    match = re.search(r"\d+", seat_label)
    if not match:
        return fallback_lab

    seat_number = int(match.group(0))
    if 1 <= seat_number <= 80:
        return "Lab 1"
    if seat_number >= 1000:
        return "Lab 2"
    return fallback_lab


def _get_calendar_filters():
    filter_date_str = request.args.get("date", "")
    range_days = request.args.get("range_days", 30, type=int)
    search = request.args.get("q", "").strip()

    if range_days not in (30, 90, 180, 365):
        range_days = 30

    try:
        filter_date = date.fromisoformat(filter_date_str) if filter_date_str else ist_today()
    except ValueError:
        filter_date = ist_today()

    return filter_date, range_days, search


def _build_matrix_data(filter_date, range_days, search=""):
    range_start = filter_date - timedelta(days=range_days - 1)
    matrix_dates = [range_start + timedelta(days=idx) for idx in range(range_days)]
    members_query = Member.query
    if search:
        members_query = members_query.filter(
            Member.full_name.ilike(f"%{search}%") | Member.member_code.ilike(f"%{search}%")
        )
    members = members_query.order_by(Member.full_name.asc()).all()
    member_start_dates = {}
    for member in members:
        if member.membership_start_date:
            member_start_dates[member.id] = member.membership_start_date
        elif member.registration_date:
            member_start_dates[member.id] = member.registration_date.date()
        else:
            member_start_dates[member.id] = range_start

    attendance_rows = (
        db.session.query(Attendance.member_id, Attendance.attendance_date)
        .filter(Attendance.attendance_date >= range_start, Attendance.attendance_date <= filter_date)
        .distinct()
        .all()
    )

    matrix_presence = {}
    for member_id, attendance_date in attendance_rows:
        matrix_presence.setdefault(member_id, set()).add(attendance_date)

    return matrix_dates, members, matrix_presence, member_start_dates


def _canonical_seat_token(value):
    if value is None:
        return None
    normalized = re.sub(r"[^A-Z0-9]", "", str(value).upper())
    if not normalized:
        return None
    if len(normalized) >= 2 and normalized[0].isalpha() and normalized[1:].isdigit():
        return f"{normalized[0]}{int(normalized[1:])}"
    return normalized


def _find_seat_by_label(seat_label):
    input_token = _canonical_seat_token(seat_label)
    if not input_token:
        return None

    seats = Seat.query.order_by(Seat.id.asc()).all()
    for seat in seats:
        if _canonical_seat_token(seat.seat_number) == input_token:
            return seat
    return None


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
        remarks="Auto-created from attendance bulk reserve",
    )
    db.session.add(seat)
    db.session.flush()
    return seat


def _seat_candidate_tokens_from_attendance(seat_label, member_lab=None):
    raw = str(seat_label or "").strip().upper()
    if not raw:
        return []

    compact = re.sub(r"[^A-Z0-9]", "", raw)
    candidates = []

    def _add(token):
        canonical = _canonical_seat_token(token)
        if canonical and canonical not in candidates:
            candidates.append(canonical)

    _add(compact)

    if compact.isdigit():
        number = int(compact)
        if 1001 <= number <= 1085:
            _add(f"B{number - 1000}")
        elif 1 <= number <= 80:
            if member_lab == "Lab 2":
                _add(f"B{number}")
            _add(f"A{number}")
        elif 81 <= number <= 85:
            _add(f"B{number}")

    if compact.startswith("A") and compact[1:].isdigit():
        _add(f"A{int(compact[1:])}")
    if compact.startswith("B") and compact[1:].isdigit():
        _add(f"B{int(compact[1:])}")

    return [token for token in candidates if _is_valid_reservation_seat_format(token)]


def _find_or_create_seat_from_attendance(seat_label, member_lab=None):
    candidate_tokens = _seat_candidate_tokens_from_attendance(seat_label, member_lab=member_lab)
    if not candidate_tokens:
        return None

    candidate_storage_numbers = {
        storage_seat_number_from_code(token)
        for token in candidate_tokens
    }
    candidate_storage_numbers.discard(None)

    seats = Seat.query.order_by(Seat.id.asc()).all()
    for seat in seats:
        seat_token = _canonical_seat_token(seat.seat_number)
        if seat_token in candidate_tokens:
            return seat

        seat_storage = storage_seat_number_from_code(seat.seat_number)
        if seat_storage is not None and seat_storage in candidate_storage_numbers:
            return seat

    # Fall back to creating canonical seat entry if it is valid but missing in seat master.
    return _create_missing_seat_for_reservation(candidate_tokens[0])


@attendance_bp.route("/attendance")
@login_required
@privilege_required("attendance.view", message="Attendance access is not assigned to this role.")
def index():
    cleanup_old_attendance(days=90)
    db.session.commit()

    filter_date, _, _ = _get_calendar_filters()
    lab_filter = request.args.get("lab", "").strip()
    search = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()
    if lab_filter not in ("", "Lab 1", "Lab 2"):
        lab_filter = ""
    if status_filter not in ("", "Active", "Expired", "Inactive", "Deleted"):
        status_filter = ""
    page = request.args.get("page", 1, type=int)

    query = Attendance.query.options(joinedload(Attendance.member).joinedload(Member.user)).filter_by(attendance_date=filter_date)
    needs_member_join = bool(search or lab_filter or status_filter)
    if needs_member_join:
        query = query.join(Member, Attendance.member_id == Member.id)
    if search:
        query = query.filter(Member.full_name.ilike(f"%{search}%"))
    if lab_filter:
        query = query.filter(Member.lab == lab_filter)
    if status_filter:
        query = query.filter(Member.membership_status == status_filter)
    query = query.order_by(Attendance.login_time.desc(), Attendance.id.desc())

    pagination = query.paginate(page=page, per_page=20)
    lab_by_record_id = {record.id: _lab_from_attendance_record(record) for record in pagination.items}

    return render_template(
        "attendance/index.html",
        pagination=pagination,
        filter_date=filter_date,
        lab_filter=lab_filter,
        status_filter=status_filter,
        search=search,
        lab_by_record_id=lab_by_record_id,
        today_ist=ist_today(),
    )


@attendance_bp.route("/attendance/reserve-seats-from-log", methods=["POST"])
@login_required
@privilege_required("attendance.view", message="Attendance access is not assigned to this role.")
def reserve_seats_from_log():
    if not current_user.is_admin:
        flash("Only admin can use this action.", "danger")
        return redirect(url_for("attendance.index"))

    selected_date_str = (request.form.get("date") or "").strip()
    search = (request.form.get("q") or "").strip()
    lab_filter = (request.form.get("lab") or "").strip()
    status_filter = (request.form.get("status") or "").strip()

    if lab_filter not in ("", "Lab 1", "Lab 2"):
        lab_filter = ""
    if status_filter not in ("", "Active", "Expired", "Inactive", "Deleted"):
        status_filter = ""

    try:
        selected_date = date.fromisoformat(selected_date_str) if selected_date_str else ist_today()
    except ValueError:
        selected_date = ist_today()

    records_query = Attendance.query.options(joinedload(Attendance.member)).filter_by(attendance_date=selected_date)
    if search or lab_filter or status_filter:
        records_query = records_query.join(Member, Attendance.member_id == Member.id)
    if search:
        records_query = records_query.filter(Member.full_name.ilike(f"%{search}%"))
    if lab_filter:
        records_query = records_query.filter(Member.lab == lab_filter)
    if status_filter:
        records_query = records_query.filter(Member.membership_status == status_filter)

    records = records_query.order_by(Attendance.login_time.desc(), Attendance.id.desc()).all()
    if not records:
        flash("No attendance records found for the selected filters.", "warning")
        return redirect(url_for("attendance.index", date=selected_date.isoformat(), q=search, lab=lab_filter, status=status_filter))

    created_count = 0
    skipped_existing = 0
    skipped_invalid = 0
    skipped_conflict = 0

    for record in records:
        member = record.member
        if not member or not member.membership_end_date:
            skipped_invalid += 1
            continue
        if member.membership_status in ("Inactive", "Deleted"):
            skipped_invalid += 1
            continue

        seat = _find_or_create_seat_from_attendance(record.seat_label, member_lab=member.lab if member else None)
        if not seat:
            skipped_invalid += 1
            continue
        if seat.status == "Blocked":
            skipped_invalid += 1
            continue

        reservation_start = selected_date
        reservation_end = member.membership_end_date + timedelta(days=15)
        if reservation_end < reservation_start:
            skipped_invalid += 1
            continue

        already_reserved_same = Booking.query.filter(
            Booking.member_id == member.id,
            Booking.seat_id == seat.id,
            Booking.booking_status == "Confirmed",
            Booking.end_date >= reservation_start,
            Booking.start_date <= reservation_end,
        ).first()
        if already_reserved_same:
            skipped_existing += 1
            continue

        seat_overlap = Booking.query.filter(
            Booking.seat_id == seat.id,
            Booking.booking_status == "Confirmed",
            Booking.end_date >= reservation_start,
            Booking.start_date <= reservation_end,
        ).first()
        if seat_overlap:
            skipped_conflict += 1
            continue

        member_overlap = Booking.query.filter(
            Booking.member_id == member.id,
            Booking.booking_status == "Confirmed",
            Booking.end_date >= reservation_start,
            Booking.start_date <= reservation_end,
        ).first()
        if member_overlap:
            skipped_conflict += 1
            continue

        db.session.add(
            Booking(
                member_id=member.id,
                seat_id=seat.id,
                start_date=reservation_start,
                end_date=reservation_end,
                booking_status="Confirmed",
            )
        )
        if seat.status != "Blocked":
            seat.status = "Occupied"
        created_count += 1

    if created_count:
        db.session.commit()

    if created_count:
        flash(
            (
                f"Bulk reserve complete for {selected_date.isoformat()}: "
                f"{created_count} created, {skipped_existing} already reserved, "
                f"{skipped_conflict} conflicts, {skipped_invalid} skipped."
            ),
            "success",
        )
    else:
        flash(
            (
                "No new reservations were created. "
                f"Already reserved: {skipped_existing}, conflicts: {skipped_conflict}, skipped: {skipped_invalid}."
            ),
            "warning",
        )

    return redirect(url_for("attendance.index", date=selected_date.isoformat(), q=search, lab=lab_filter, status=status_filter))


@attendance_bp.route("/attendance/export")
@login_required
@privilege_required("attendance.view", message="Attendance access is not assigned to this role.")
def export_attendance_log():
    cleanup_old_attendance(days=90)
    db.session.commit()

    filter_date, _, _ = _get_calendar_filters()
    lab_filter = request.args.get("lab", "").strip()
    search = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()
    if lab_filter not in ("", "Lab 1", "Lab 2"):
        lab_filter = ""
    if status_filter not in ("", "Active", "Expired", "Inactive", "Deleted"):
        status_filter = ""
    export_format = request.args.get("format", "csv").lower()
    records_query = Attendance.query.options(joinedload(Attendance.member).joinedload(Member.user)).filter_by(attendance_date=filter_date)
    needs_member_join = bool(search or lab_filter or status_filter)
    if needs_member_join:
        records_query = records_query.join(Member, Attendance.member_id == Member.id)
    if search:
        records_query = records_query.filter(Member.full_name.ilike(f"%{search}%"))
    if lab_filter:
        records_query = records_query.filter(Member.lab == lab_filter)
    if status_filter:
        records_query = records_query.filter(Member.membership_status == status_filter)
    records = records_query.order_by(Attendance.login_time.desc(), Attendance.id.desc()).all()

    header = [
        "Member Name", "Member Code", "Lab", "Booked By", "Seat", "Attendance Date",
        "Login Time", "Logout Time", "Duration",
    ]
    rows = []
    for record in records:
        duration = ""
        if record.login_time and record.logout_time:
            diff = int((record.logout_time - record.login_time).total_seconds())
            hrs = diff // 3600
            mins = (diff % 3600) // 60
            duration = f"{hrs}h {mins}m"
        elif record.login_time:
            duration = "Ongoing"

        rows.append([
            record.member.full_name if record.member else "Member Not Found",
            record.member.member_code if record.member else "",
            _lab_from_attendance_record(record),
            record.booked_by_email or "",
            record.seat_label or "",
            record.attendance_date.isoformat() if record.attendance_date else "",
            record.login_time.isoformat(sep=" ", timespec="minutes") if record.login_time else "",
            record.logout_time.isoformat(sep=" ", timespec="minutes") if record.logout_time else "",
            duration,
        ])

    if export_format == "xlsx":
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Attendance Log"
        sheet.append(header)
        for row in rows:
            sheet.append(row)
        output = io.BytesIO()
        workbook.save(output)
        workbook.close()
        output.seek(0)
        filename = f"attendance_log_{filter_date.isoformat()}.xlsx"
        return Response(
            output.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(header)
    writer.writerows(rows)
    csv_data = output.getvalue()
    output.close()
    filename = f"attendance_log_{filter_date.isoformat()}.csv"
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@attendance_bp.route("/attendance/calendar")
@login_required
@privilege_required("attendance.calendar.view", message="Attendance calendar access is not assigned to this role.")
def calendar_view():
    cleanup_old_attendance(days=90)
    db.session.commit()

    filter_date, range_days, search = _get_calendar_filters()
    matrix_dates, members, matrix_presence, member_start_dates = _build_matrix_data(filter_date, range_days, search)

    return render_template(
        "attendance/calendar.html",
        filter_date=filter_date,
        range_days=range_days,
        search=search,
        matrix_dates=matrix_dates,
        members=members,
        matrix_presence=matrix_presence,
        member_start_dates=member_start_dates,
    )


@attendance_bp.route("/attendance/calendar/export")
@login_required
@privilege_required("attendance.calendar.view", message="Attendance calendar access is not assigned to this role.")
def calendar_export():
    cleanup_old_attendance(days=90)
    db.session.commit()

    filter_date, range_days, search = _get_calendar_filters()
    matrix_dates, members, matrix_presence, member_start_dates = _build_matrix_data(filter_date, range_days, search)
    export_format = request.args.get("format", "csv").lower()

    header = ["Member Name", "Member Code"] + [d.strftime("%Y-%m-%d") for d in matrix_dates] + [
        "Present Days",
        "Attendance %",
    ]
    rows = []

    for member in members:
        member_presence = matrix_presence.get(member.id, set())
        member_start_date = member_start_dates.get(member.id)
        row = [member.full_name, member.member_code]
        present_days = 0
        eligible_days = 0
        for matrix_date in matrix_dates:
            if member_start_date and matrix_date < member_start_date:
                row.append("")
                continue
            eligible_days += 1
            present = matrix_date in member_presence
            row.append("Present" if present else "Absent")
            if present:
                present_days += 1

        attendance_pct = round((present_days / eligible_days) * 100, 2) if eligible_days else 0
        row.extend([present_days, attendance_pct])
        rows.append(row)

    if export_format == "xlsx":
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Attendance Calendar"
        sheet.append(header)
        for row in rows:
            sheet.append(row)

        output = io.BytesIO()
        workbook.save(output)
        workbook.close()
        output.seek(0)
        filename = f"attendance_calendar_{filter_date.isoformat()}_{range_days}d.xlsx"
        return Response(
            output.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(header)
    writer.writerows(rows)

    csv_data = output.getvalue()
    output.close()

    filename = f"attendance_calendar_{filter_date.isoformat()}_{range_days}d.csv"
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
