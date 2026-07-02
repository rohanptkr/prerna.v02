from application import db

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

    def __repr__(self):
        return f"<Role {self.role_name}>"
