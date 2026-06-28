"""allow multiple attendance sessions per day

Revision ID: c7d8e9f0a1b2
Revises: f1a2b3c4d5e6
Create Date: 2026-06-28 00:00:00.000000

"""
from alembic import op
from sqlalchemy import inspect


revision = "c7d8e9f0a1b2"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    inspector = inspect(op.get_bind())
    if "attendance" not in inspector.get_table_names():
        return

    unique_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("attendance")}
    if "uq_member_per_day" in unique_constraints:
        with op.batch_alter_table("attendance", schema=None) as batch_op:
            batch_op.drop_constraint("uq_member_per_day", type_="unique")


def downgrade():
    inspector = inspect(op.get_bind())
    if "attendance" not in inspector.get_table_names():
        return

    unique_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("attendance")}
    if "uq_member_per_day" not in unique_constraints:
        with op.batch_alter_table("attendance", schema=None) as batch_op:
            batch_op.create_unique_constraint("uq_member_per_day", ["member_id", "attendance_date"])