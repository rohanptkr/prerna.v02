from datetime import datetime
from application import db

class Member(db.Model):
    __tablename__ = "members"

    id = db.Column(db.Integer, primary_key=True)
    member_code = db.Column(db.String(32), unique=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    aadhaar_number = db.Column(db.String(12), unique=True)
    date_of_birth = db.Column(db.Date)
    age = db.Column(db.Integer)
    gender = db.Column(db.String(16))
    school_name = db.Column(db.String(120))
    emergency_contact_name = db.Column(db.String(120))
    emergency_contact_number = db.Column(db.String(30))
    address = db.Column(db.String(255), nullable=False)
    registration_date = db.Column(db.DateTime, default=datetime.utcnow)
    membership_start_date = db.Column(db.Date)
    membership_end_date = db.Column(db.Date)
    membership_status = db.Column(db.String(32), default="Active")
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    user = db.relationship("User", back_populates="member")
    bookings = db.relationship("Booking", back_populates="member", cascade="all, delete-orphan")
    payments = db.relationship("Payment", back_populates="member", cascade="all, delete-orphan")
    attendance_records = db.relationship("Attendance", back_populates="member", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Member {self.full_name}>"
