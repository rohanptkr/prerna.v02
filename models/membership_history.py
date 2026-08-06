from datetime import datetime

from application import db


class MembershipHistory(db.Model):
    __tablename__ = "membership_history"

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey("members.id"), nullable=False, index=True)
    period_start_date = db.Column(db.Date, nullable=False)
    period_end_date = db.Column(db.Date, nullable=False)
    event_type = db.Column(db.String(32), nullable=False, default="Admission")
    notes = db.Column(db.String(255))
    changed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    member = db.relationship("Member", back_populates="membership_history")
    changed_by_user = db.relationship("User", foreign_keys=[changed_by_user_id])

    def __repr__(self):
        return (
            f"<MembershipHistory member_id={self.member_id} "
            f"start={self.period_start_date} end={self.period_end_date} type={self.event_type}>"
        )
