from datetime import datetime, date

from application import db


class RenewalRequest(db.Model):
    __tablename__ = "renewal_requests"

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey("members.id"), nullable=False, index=True)
    requested_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    duration_months = db.Column(db.Integer, nullable=False, default=1)
    proposed_start_date = db.Column(db.Date, nullable=True)
    proposed_end_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(16), nullable=False, default="Pending")
    requested_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    member = db.relationship("Member", foreign_keys=[member_id])
    requested_by_user = db.relationship("User", foreign_keys=[requested_by_user_id])
    reviewed_by_user = db.relationship("User", foreign_keys=[reviewed_by_user_id])

    def __repr__(self):
        return f"<RenewalRequest member_id={self.member_id} status={self.status}>"
