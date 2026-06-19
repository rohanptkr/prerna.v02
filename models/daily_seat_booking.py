from datetime import datetime, date
from application import db


class DailySeatBooking(db.Model):
    """Walk-in daily seat assignment tied to a registered Member."""

    __tablename__ = "daily_seat_bookings"
    __table_args__ = (
        db.UniqueConstraint("seat_number", "booking_date", name="uq_seat_per_day"),
    )

    id = db.Column(db.Integer, primary_key=True)
    seat_number = db.Column(db.Integer, nullable=False)
    member_id = db.Column(db.Integer, db.ForeignKey("members.id"), nullable=False)
    member_name = db.Column(db.String(120), nullable=False)  # denormalised for speed
    booking_date = db.Column(db.Date, default=date.today, nullable=False)
    booked_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    member = db.relationship("Member")
    booked_by = db.relationship("User")

    def __repr__(self):
        return f"<DailySeatBooking seat={self.seat_number} date={self.booking_date}>"
