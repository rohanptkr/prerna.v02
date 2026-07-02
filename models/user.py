from datetime import datetime
from flask_login import UserMixin
from application import db
from werkzeug.security import generate_password_hash, check_password_hash

class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    is_locked = db.Column(db.Boolean, default=False, nullable=False)

    role = db.relationship("Role", back_populates="users")
    member = db.relationship("Member", back_populates="user", uselist=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def has_privilege(self, privilege):
        return bool(self.role and self.role.has_privilege(privilege))

    @property
    def is_admin(self):
        return bool(self.role and self.role.is_admin)

    @property
    def is_member(self):
        return bool(self.role and self.role.is_member)

    def get_id(self):
        return str(self.id)

    def __repr__(self):
        return f"<User {self.username}>"
