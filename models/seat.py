from application import db

class Seat(db.Model):
    __tablename__ = "seats"

    id = db.Column(db.Integer, primary_key=True)
    seat_number = db.Column(db.String(32), unique=True, nullable=False)
    seat_type = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(32), default="Available", nullable=False)
    monthly_fee = db.Column(db.Numeric(10, 2), nullable=False)
    floor = db.Column(db.String(32), nullable=False)
    remarks = db.Column(db.String(255))

    bookings = db.relationship("Booking", back_populates="seat", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Seat {self.seat_number}>"
