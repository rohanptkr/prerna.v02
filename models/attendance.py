from datetime import date, datetime
from application import db


class Attendance(db.Model):
    """Daily attendance log — one row per member per day.

    Login time is set when a seat is booked on the daily seat dashboard.
    Logout time is set when the seat is unbooked.
    Multiple check-ins per day are tracked by updating the existing row
    (latest login_time wins) so the view stays simple (one row per day).
    """

    __tablename__ = "attendance"
    __table_args__ = (
        db.UniqueConstraint("member_id", "attendance_date", name="uq_member_per_day"),
    )

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey("members.id"), nullable=False)
    attendance_date = db.Column(db.Date, default=date.today, nullable=False)
    login_time = db.Column(db.DateTime, nullable=True)
    logout_time = db.Column(db.DateTime, nullable=True)

    member = db.relationship("Member", back_populates="attendance_records")

    def __repr__(self):
        return f"<Attendance member={self.member_id} date={self.attendance_date}>"
