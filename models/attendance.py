from datetime import date, datetime
from application import db


class Attendance(db.Model):
    """Daily attendance log — one row per seating session.

    Login time is set when a seat is booked.
    seat_label stores where the member was seated for that session.
    Logout time is set when the seat is unbooked.
    Members may have multiple rows on the same date, but only one open row
    should exist at a time.
    """

    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey("members.id"), nullable=False)
    seat_label = db.Column(db.String(64), nullable=True)
    booked_by_email = db.Column(db.String(120), nullable=True)
    attendance_date = db.Column(db.Date, default=date.today, nullable=False)
    login_time = db.Column(db.DateTime, nullable=True)
    logout_time = db.Column(db.DateTime, nullable=True)

    member = db.relationship("Member", back_populates="attendance_records")

    def __repr__(self):
        return f"<Attendance member={self.member_id} date={self.attendance_date}>"
