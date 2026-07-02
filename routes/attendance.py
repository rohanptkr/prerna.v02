from datetime import date, timedelta
from functools import wraps
import csv
import io
from openpyxl import Workbook

from flask import Blueprint, redirect, render_template, request, url_for, flash, Response
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from application import db
from models.attendance import Attendance
from models.member import Member
from services.daily_seat_service import cleanup_old_attendance, ist_today

attendance_bp = Blueprint("attendance", __name__, template_folder="../templates")


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

    attendance_rows = (
        db.session.query(Attendance.member_id, Attendance.attendance_date)
        .filter(Attendance.attendance_date >= range_start, Attendance.attendance_date <= filter_date)
        .distinct()
        .all()
    )

    matrix_presence = {}
    for member_id, attendance_date in attendance_rows:
        matrix_presence.setdefault(member_id, set()).add(attendance_date)

    return matrix_dates, members, matrix_presence


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role.role_name != "Admin":
            flash("Admin access required.", "danger")
            return redirect(url_for("auth.login"))
        return func(*args, **kwargs)
    return wrapper


@attendance_bp.route("/attendance")
@login_required
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

    return render_template(
        "attendance/index.html",
        pagination=pagination,
        filter_date=filter_date,
        search="",
    )


@attendance_bp.route("/attendance/calendar")
@login_required
@admin_required
def calendar_view():
    cleanup_old_attendance(days=90)
    db.session.commit()

    filter_date, range_days = _get_calendar_filters()
    matrix_dates, members, matrix_presence = _build_matrix_data(filter_date, range_days)

    return render_template(
        "attendance/calendar.html",
        filter_date=filter_date,
        range_days=range_days,
        matrix_dates=matrix_dates,
        members=members,
        matrix_presence=matrix_presence,
    )


@attendance_bp.route("/attendance/calendar/export")
@login_required
@admin_required
def calendar_export():
    cleanup_old_attendance(days=90)
    db.session.commit()

    filter_date, range_days = _get_calendar_filters()
    matrix_dates, members, matrix_presence = _build_matrix_data(filter_date, range_days)
    export_format = request.args.get("format", "csv").lower()

    header = ["Member Name", "Member Code"] + [d.strftime("%Y-%m-%d") for d in matrix_dates] + [
        "Present Days",
        "Attendance %",
    ]
    rows = []

    total_days = len(matrix_dates) or 1
    for member in members:
        member_presence = matrix_presence.get(member.id, set())
        row = [member.full_name, member.member_code]
        present_days = 0
        for matrix_date in matrix_dates:
            present = matrix_date in member_presence
            row.append("Present" if present else "Absent")
            if present:
                present_days += 1

        attendance_pct = round((present_days / total_days) * 100, 2)
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
