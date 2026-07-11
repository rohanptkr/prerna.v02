from datetime import date, datetime
import re

from application import db
from models import DailySeatBooking, Member, Payment
from models.attendance import Attendance
from services.daily_seat_service import (
    TOTAL_SEATS,
    TOTAL_SEATS_LAB_1,
    TOTAL_SEATS_LAB_2,
    VALID_SEAT_NUMBERS_LAB_1,
    VALID_SEAT_NUMBERS_LAB_2,
    ist_today,
)


def calculate_dashboard_metrics():
    today = ist_today()
    month_start = date(today.year, today.month, 1)
    if today.month == 12:
        next_month_start = date(today.year + 1, 1, 1)
    else:
        next_month_start = date(today.year, today.month + 1, 1)

    occupied_today = DailySeatBooking.query.filter_by(booking_date=today).count()
    occupied_lab_1 = DailySeatBooking.query.filter(
        DailySeatBooking.booking_date == today,
        DailySeatBooking.seat_number.in_(list(VALID_SEAT_NUMBERS_LAB_1)),
    ).count()
    occupied_lab_2 = DailySeatBooking.query.filter(
        DailySeatBooking.booking_date == today,
        DailySeatBooking.seat_number.in_(list(VALID_SEAT_NUMBERS_LAB_2)),
    ).count()
    today_attendance_total = (
        db.session.query(db.func.count(db.distinct(Attendance.member_id)))
        .filter_by(attendance_date=today)
        .scalar()
        or 0
    )
    today_attendance_rows = (
        db.session.query(Attendance.member_id, Attendance.seat_label)
        .filter(Attendance.attendance_date == today)
        .all()
    )
    attendance_member_ids_lab_1 = set()
    attendance_member_ids_lab_2 = set()
    for member_id, seat_label in today_attendance_rows:
        if not seat_label:
            continue
        match = re.search(r"\d+", seat_label)
        if not match:
            continue
        seat_number = int(match.group(0))
        if seat_number in VALID_SEAT_NUMBERS_LAB_1:
            attendance_member_ids_lab_1.add(member_id)
        elif seat_number in VALID_SEAT_NUMBERS_LAB_2:
            attendance_member_ids_lab_2.add(member_id)

    today_attendance_lab_1 = len(attendance_member_ids_lab_1)
    today_attendance_lab_2 = len(attendance_member_ids_lab_2)
    active_members_lab_1 = Member.query.filter_by(membership_status="Active", lab="Lab 1").count()
    active_members_lab_2 = Member.query.filter_by(membership_status="Active", lab="Lab 2").count()
    expired_members_lab_1 = Member.query.filter_by(membership_status="Expired", lab="Lab 1").count()
    expired_members_lab_2 = Member.query.filter_by(membership_status="Expired", lab="Lab 2").count()
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
        "occupied_seats_lab_1": occupied_lab_1,
        "available_seats_lab_1": max(TOTAL_SEATS_LAB_1 - occupied_lab_1, 0),
        "occupied_seats_lab_2": occupied_lab_2,
        "available_seats_lab_2": max(TOTAL_SEATS_LAB_2 - occupied_lab_2, 0),
        "today_attendance": today_attendance_total,
        "today_attendance_lab_1": today_attendance_lab_1,
        "today_attendance_lab_2": today_attendance_lab_2,
        "active_members_lab_1": active_members_lab_1,
        "active_members_lab_2": active_members_lab_2,
        "expired_members_lab_1": expired_members_lab_1,
        "expired_members_lab_2": expired_members_lab_2,
        "monthly_revenue": monthly_revenue or 0,
    }
