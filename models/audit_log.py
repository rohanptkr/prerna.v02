from datetime import datetime

from application import db


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    method = db.Column(db.String(16), nullable=False)
    endpoint = db.Column(db.String(128), nullable=True)
    path = db.Column(db.String(255), nullable=False)
    status_code = db.Column(db.Integer, nullable=False)
    ip_address = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User")

    def __repr__(self):
        return f"<AuditLog user_id={self.user_id} method={self.method} path={self.path}>"