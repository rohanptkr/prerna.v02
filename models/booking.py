from datetime import datetime
from application import db

class Booking(db.Model):
    __tablename__ = "bookings"

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey("members.id"), nullable=False)
    seat_id = db.Column(db.Integer, db.ForeignKey("seats.id"), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    booking_status = db.Column(db.String(32), default="Confirmed", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    member = db.relationship("Member", back_populates="bookings")
    seat = db.relationship("Seat", back_populates="bookings")
    payments = db.relationship("Payment", back_populates="booking", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Booking {self.id} member={self.member_id} seat={self.seat_id}>"
