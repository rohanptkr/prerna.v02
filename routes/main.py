from datetime import date
from flask import Blueprint, render_template
from flask_login import current_user, login_required

from application import db
from models import Member, Seat
from models.attendance import Attendance

main_bp = Blueprint("main", __name__, template_folder="../templates")


def calculate_metrics():
    today = date.today()
    return {
        "active_members": Member.query.filter_by(membership_status="Active").count(),
        "expired_members": Member.query.filter_by(membership_status="Expired").count(),
        "occupied_seats": Seat.query.filter_by(status="Occupied").count(),
        "available_seats": Seat.query.filter_by(status="Available").count(),
        "today_attendance": Attendance.query.filter_by(attendance_date=today).count(),
    }


@main_bp.route("/")
@login_required
def index():
    metrics = calculate_metrics()
    if current_user.role.role_name == "Admin":
        return render_template("dashboard/admin_dashboard.html", metrics=metrics)
    return render_template("dashboard/member_dashboard.html", metrics=metrics)
