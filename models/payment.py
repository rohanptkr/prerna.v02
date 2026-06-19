from datetime import datetime
from application import db

class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey("members.id"), nullable=False)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    payment_method = db.Column(db.String(64), nullable=False)
    payment_date = db.Column(db.DateTime, default=datetime.utcnow)
    payment_status = db.Column(db.String(32), default="Completed", nullable=False)
    transaction_reference = db.Column(db.String(128), unique=True, nullable=False)

    member = db.relationship("Member", back_populates="payments")
    booking = db.relationship("Booking", back_populates="payments")

    def __repr__(self):
        return f"<Payment {self.transaction_reference}>"
