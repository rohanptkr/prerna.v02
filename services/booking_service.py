from collections import defaultdict
from datetime import date, timedelta

from application import db
from models import Booking, Seat, Payment, Member


def enforce_booking_rules(member_id, seat_id, start_date, end_date):
    if end_date < start_date:
        return "End date must be after start date."

    overlapping_seat = Booking.query.filter(
        Booking.seat_id == seat_id,
        Booking.booking_status == "Confirmed",
        Booking.end_date >= start_date,
        Booking.start_date <= end_date,
    ).first()
    if overlapping_seat:
        return "The selected seat already has an active or overlapping booking."

    overlapping_member = Booking.query.filter(
        Booking.member_id == member_id,
        Booking.booking_status == "Confirmed",
        Booking.end_date >= start_date,
        Booking.start_date <= end_date,
    ).first()
    if overlapping_member:
        return "This member already has an active or overlapping booking."

    return None


def refresh_seat_availability():
    today = date.today()
    expired_bookings = Booking.query.filter(
        Booking.booking_status == "Confirmed",
        Booking.end_date < today,
    ).all()
    expired_seat_ids = {booking.seat_id for booking in expired_bookings}
    if expired_seat_ids:
        seats = Seat.query.filter(Seat.id.in_(expired_seat_ids)).all()
        for seat in seats:
            seat.status = "Available"
        db.session.commit()


def cleanup_long_expired_members(expiry_days=10):
    """Exclude members expired longer than expiry_days and release their occupied seats.

    A member remains visible as expired for the grace window after membership_end_date.
    After that window, their seat is released if it is still assigned to them.
    """
    today = date.today()
    cutoff_date = today - timedelta(days=expiry_days)

    stale_members = Member.query.filter(
        Member.membership_status != "Deleted",
        Member.membership_end_date.isnot(None),
        Member.membership_end_date < cutoff_date,
    ).all()

    if not stale_members:
        return 0

    stale_member_ids = [member.id for member in stale_members]
    stale_bookings = Booking.query.filter(
        Booking.member_id.in_(stale_member_ids),
        Booking.booking_status == "Confirmed",
        Booking.seat_id.isnot(None),
    ).all()

    released_seat_ids = set()
    for booking in stale_bookings:
        booking.booking_status = "Cancelled"
        if booking.seat and booking.seat.status != "Available":
            booking.seat.status = "Available"
            released_seat_ids.add(booking.seat_id)

    if stale_bookings or released_seat_ids:
        db.session.commit()

    return len(stale_members)


def group_payments_by_month():
    monthly_collections = defaultdict(float)
    for payment in Payment.query.order_by(Payment.payment_date).all():
        if payment.payment_date:
            key = payment.payment_date.strftime("%Y-%m")
            monthly_collections[key] += float(payment.amount or 0)
    return sorted(monthly_collections.items())
