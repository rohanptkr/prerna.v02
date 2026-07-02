from application import db


ADMIN_ROLE_NAME = "Admin"
MEMBER_ROLE_NAME = "Member"
MEMBER_DEFAULT_PRIVILEGES = {
    "dashboard.view",
    "daily_seats.view",
    "attendance.view",
}

class Role(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    role_name = db.Column(db.String(64), unique=True, nullable=False)
    description = db.Column(db.String(255))
    privileges = db.Column(db.String(512), default="", nullable=False)
    users = db.relationship("User", back_populates="role")

    @property
    def privilege_list(self):
        if not self.privileges:
            return []
        return [item for item in self.privileges.split(",") if item]

    def has_privilege(self, privilege):
        if not privilege:
            return False
        if self.role_name == ADMIN_ROLE_NAME:
            return True
        if self.role_name == MEMBER_ROLE_NAME:
            return privilege in MEMBER_DEFAULT_PRIVILEGES
        return privilege in set(self.privilege_list)

    @property
    def is_admin(self):
        return self.role_name == ADMIN_ROLE_NAME

    @property
    def is_member(self):
        return self.role_name == MEMBER_ROLE_NAME

    def __repr__(self):
        return f"<Role {self.role_name}>"
