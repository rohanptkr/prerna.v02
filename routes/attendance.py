from datetime import date
from functools import wraps

from flask import Blueprint, redirect, render_template, request, url_for, flash
from flask_login import current_user, login_required

from models.attendance import Attendance

attendance_bp = Blueprint("attendance", __name__, template_folder="../templates")


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
@admin_required
def index():
    filter_date_str = request.args.get("date", "")
    page = request.args.get("page", 1, type=int)

    try:
        filter_date = date.fromisoformat(filter_date_str) if filter_date_str else date.today()
    except ValueError:
        filter_date = date.today()

    query = (
        Attendance.query
        .filter_by(attendance_date=filter_date)
        .order_by(Attendance.login_time.asc())
    )
    pagination = query.paginate(page=page, per_page=20)
    return render_template(
        "attendance/index.html",
        pagination=pagination,
        filter_date=filter_date,
    )
