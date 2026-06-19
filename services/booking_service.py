from collections import defaultdict
from datetime import date

from application import db
from models import Booking, Seat, Payment


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


def group_payments_by_month():
    monthly_collections = defaultdict(float)
    for payment in Payment.query.order_by(Payment.payment_date).all():
        if payment.payment_date:
            key = payment.payment_date.strftime("%Y-%m")
            monthly_collections[key] += float(payment.amount or 0)
    return sorted(monthly_collections.items())
