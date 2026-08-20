from datetime import date, datetime, timedelta

from application import db
from models import DailySeatBooking, Member, Payment
from models.attendance import Attendance
from sqlalchemy import and_, or_
from services.daily_seat_service import (
    TOTAL_SEATS,
    TOTAL_SEATS_LAB_1,
    TOTAL_SEATS_LAB_2,
    VALID_SEAT_NUMBERS_LAB_1,
    VALID_SEAT_NUMBERS_LAB_2,
    ist_today,
)


def _expiring_soon_filter(today):
    return (
        Member.membership_status == "Active",
        Member.membership_end_date.isnot(None),
        Member.membership_end_date >= today,
        Member.membership_end_date <= today + timedelta(days=7),
    )


def _expired_filter(today):
    return or_(
        Member.membership_status == "Expired",
        and_(
            Member.membership_status != "Deleted",
            Member.membership_end_date.isnot(None),
            Member.membership_end_date < today,
        ),
    )


def _active_filter(today):
    return and_(
        Member.membership_status == "Active",
        or_(Member.membership_end_date.is_(None), Member.membership_end_date >= today),
    )


def _new_admissions_filter(today):
    cutoff_date = today - timedelta(days=6)
    return (
        Member.registration_date.isnot(None),
        db.func.date(Member.registration_date) >= cutoff_date,
        db.func.date(Member.registration_date) <= today,
    )


def _attendance_member_ids_by_lab(today):
    attendance_member_ids = {
        member_id
        for (member_id,) in db.session.query(Attendance.member_id)
        .filter(
            Attendance.attendance_date == today,
            Attendance.member_id.isnot(None),
            Attendance.login_time.isnot(None),
        )
        .distinct()
        .all()
    }

    attendance_member_ids_lab_1 = {
        member_id
        for (member_id,) in db.session.query(Attendance.member_id)
        .join(Member, Attendance.member_id == Member.id)
        .filter(
            Attendance.attendance_date == today,
            Attendance.member_id.isnot(None),
            Attendance.login_time.isnot(None),
            Member.lab == "Lab 1",
        )
        .distinct()
        .all()
    }

    attendance_member_ids_lab_2 = {
        member_id
        for (member_id,) in db.session.query(Attendance.member_id)
        .join(Member, Attendance.member_id == Member.id)
        .filter(
            Attendance.attendance_date == today,
            Attendance.member_id.isnot(None),
            Attendance.login_time.isnot(None),
            Member.lab == "Lab 2",
        )
        .distinct()
        .all()
    }

    return attendance_member_ids, attendance_member_ids_lab_1, attendance_member_ids_lab_2


def get_dashboard_member_list(category, lab=None):
    today = ist_today()

    if category == "attendance":
        attendance_member_ids, attendance_member_ids_lab_1, attendance_member_ids_lab_2 = _attendance_member_ids_by_lab(today)
        if lab == "Lab 1":
            member_ids = attendance_member_ids_lab_1
        elif lab == "Lab 2":
            member_ids = attendance_member_ids_lab_2
        else:
            member_ids = attendance_member_ids
        if not member_ids:
            return []
        return Member.query.filter(Member.id.in_(member_ids)).order_by(Member.full_name.asc()).all()

    query = Member.query
    if category == "active":
        query = query.filter(_active_filter(today))
    elif category == "expired":
        query = query.filter(_expired_filter(today))
    elif category == "expiring_soon":
        query = query.filter(*_expiring_soon_filter(today))
    elif category == "new_admissions":
        query = query.filter(*_new_admissions_filter(today))
        query = query.order_by(Member.registration_date.desc(), Member.id.desc())
    else:
        return []

    if category != "new_admissions":
        query = query.order_by(Member.full_name.asc())

    if lab in {"Lab 1", "Lab 2"}:
        query = query.filter(Member.lab == lab)

    return query.all()


def get_dashboard_attendance_entries(lab=None):
    """Return unique members with their latest seat label for today's attendance."""
    today = ist_today()

    query = (
        db.session.query(Attendance.member_id, Member.full_name, Attendance.seat_label, Attendance.login_time, Attendance.id)
        .join(Member, Attendance.member_id == Member.id)
        .filter(
            Attendance.attendance_date == today,
            Attendance.member_id.isnot(None),
            Attendance.login_time.isnot(None),
        )
        .order_by(Attendance.login_time.desc(), Attendance.id.desc())
    )

    if lab in {"Lab 1", "Lab 2"}:
        query = query.filter(Member.lab == lab)

    latest_by_member = {}
    for member_id, full_name, seat_label, _login_time, _id in query.all():
        if member_id not in latest_by_member:
            latest_by_member[member_id] = {
                "full_name": full_name,
                "seat_label": seat_label or "-",
            }

    return sorted(latest_by_member.values(), key=lambda row: row["full_name"].lower())


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
    attendance_member_ids, attendance_member_ids_lab_1, attendance_member_ids_lab_2 = _attendance_member_ids_by_lab(today)
    today_attendance_total = len(attendance_member_ids)

    today_attendance_lab_1 = len(attendance_member_ids_lab_1)
    today_attendance_lab_2 = len(attendance_member_ids_lab_2)
    active_members_lab_1 = Member.query.filter(_active_filter(today), Member.lab == "Lab 1").count()
    active_members_lab_2 = Member.query.filter(_active_filter(today), Member.lab == "Lab 2").count()
    expired_members_lab_1 = Member.query.filter(_expired_filter(today), Member.lab == "Lab 1").count()
    expired_members_lab_2 = Member.query.filter(_expired_filter(today), Member.lab == "Lab 2").count()
    expiring_soon_members = Member.query.filter(*_expiring_soon_filter(today)).count()
    expiring_soon_members_lab_1 = Member.query.filter(*_expiring_soon_filter(today), Member.lab == "Lab 1").count()
    expiring_soon_members_lab_2 = Member.query.filter(*_expiring_soon_filter(today), Member.lab == "Lab 2").count()
    new_admissions_members = Member.query.filter(*_new_admissions_filter(today)).count()
    monthly_revenue = db.session.query(
        db.func.coalesce(db.func.sum(Payment.amount), 0)
    ).filter(
        Payment.payment_date >= datetime.combine(month_start, datetime.min.time()),
        Payment.payment_date < datetime.combine(next_month_start, datetime.min.time()),
    ).scalar()

    return {
        "total_members": Member.query.count(),
        "active_members": Member.query.filter(_active_filter(today)).count(),
        "expired_members": Member.query.filter(_expired_filter(today)).count(),
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
        "expiring_soon_members": expiring_soon_members,
        "expiring_soon_members_lab_1": expiring_soon_members_lab_1,
        "expiring_soon_members_lab_2": expiring_soon_members_lab_2,
        "new_admissions_members": new_admissions_members,
        "monthly_revenue": monthly_revenue or 0,
    }
