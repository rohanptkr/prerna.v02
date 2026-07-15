from datetime import date, timedelta
import csv
import io
import re
from openpyxl import Workbook

from flask import Blueprint, Response, render_template, request
from flask_login import login_required
from sqlalchemy.orm import joinedload

from application import db
from models.attendance import Attendance
from models.member import Member
from services.access_control import privilege_required
from services.daily_seat_service import cleanup_old_attendance, ist_today

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

    if range_days not in (30, 90, 180, 365):
        range_days = 30

    try:
        filter_date = date.fromisoformat(filter_date_str) if filter_date_str else ist_today()
    except ValueError:
        filter_date = ist_today()

    return filter_date, range_days


def _build_matrix_data(filter_date, range_days):
    range_start = filter_date - timedelta(days=range_days - 1)
    matrix_dates = [range_start + timedelta(days=idx) for idx in range(range_days)]
    members = Member.query.order_by(Member.full_name.asc()).all()
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


@attendance_bp.route("/attendance")
@login_required
@privilege_required("attendance.view", message="Attendance access is not assigned to this role.")
def index():
    cleanup_old_attendance(days=90)
    db.session.commit()

    filter_date, _ = _get_calendar_filters()
    page = request.args.get("page", 1, type=int)

    query = (
        Attendance.query.options(joinedload(Attendance.member).joinedload(Member.user))
        .filter_by(attendance_date=filter_date)
        .order_by(Attendance.login_time.asc())
    )
    pagination = query.paginate(page=page, per_page=20)
    lab_by_record_id = {record.id: _lab_from_attendance_record(record) for record in pagination.items}

    return render_template(
        "attendance/index.html",
        pagination=pagination,
        filter_date=filter_date,
        search="",
        lab_by_record_id=lab_by_record_id,
    )


@attendance_bp.route("/attendance/export")
@login_required
@privilege_required("attendance.view", message="Attendance access is not assigned to this role.")
def export_attendance_log():
    cleanup_old_attendance(days=90)
    db.session.commit()

    filter_date, _ = _get_calendar_filters()
    export_format = request.args.get("format", "csv").lower()
    records = (
        Attendance.query.options(joinedload(Attendance.member).joinedload(Member.user))
        .filter_by(attendance_date=filter_date)
        .order_by(Attendance.login_time.asc())
        .all()
    )

    header = [
        "Member Name", "Member Code", "Lab", "Booked By Email", "Seat", "Attendance Date",
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

    filter_date, range_days = _get_calendar_filters()
    matrix_dates, members, matrix_presence, member_start_dates = _build_matrix_data(filter_date, range_days)

    return render_template(
        "attendance/calendar.html",
        filter_date=filter_date,
        range_days=range_days,
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

    filter_date, range_days = _get_calendar_filters()
    matrix_dates, members, matrix_presence, member_start_dates = _build_matrix_data(filter_date, range_days)
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
