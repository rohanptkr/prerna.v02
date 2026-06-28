from datetime import date, datetime

from application import db
from models import DailySeatBooking, Member, Payment
from models.attendance import Attendance
from services.daily_seat_service import TOTAL_SEATS
from services.daily_seat_service import ist_today


def calculate_dashboard_metrics():
    today = ist_today()
    month_start = date(today.year, today.month, 1)
    if today.month == 12:
        next_month_start = date(today.year + 1, 1, 1)
    else:
        next_month_start = date(today.year, today.month + 1, 1)

    occupied_today = DailySeatBooking.query.filter_by(booking_date=today).count()
    monthly_revenue = db.session.query(
        db.func.coalesce(db.func.sum(Payment.amount), 0)
    ).filter(
        Payment.payment_date >= datetime.combine(month_start, datetime.min.time()),
        Payment.payment_date < datetime.combine(next_month_start, datetime.min.time()),
    ).scalar()

    return {
        "total_members": Member.query.count(),
        "active_members": Member.query.filter_by(membership_status="Active").count(),
        "expired_members": Member.query.filter_by(membership_status="Expired").count(),
        "occupied_seats": occupied_today,
        "available_seats": max(TOTAL_SEATS - occupied_today, 0),
        "today_attendance": db.session.query(db.func.count(db.distinct(Attendance.member_id))).filter_by(attendance_date=today).scalar() or 0,
        "monthly_revenue": monthly_revenue or 0,
    }
