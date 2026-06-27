"""add booked_by_email to attendance

Revision ID: f1a2b3c4d5e6
Revises: e4c2b9a1d7f6
Create Date: 2026-06-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "f1a2b3c4d5e6"
down_revision = "e4c2b9a1d7f6"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if "attendance" not in inspector.get_table_names():
        return

    existing_cols = [c["name"] for c in inspector.get_columns("attendance")]
    if "booked_by_email" not in existing_cols:
        with op.batch_alter_table("attendance", schema=None) as batch_op:
            batch_op.add_column(sa.Column("booked_by_email", sa.String(length=120), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if "attendance" not in inspector.get_table_names():
        return

    existing_cols = [c["name"] for c in inspector.get_columns("attendance")]
    if "booked_by_email" in existing_cols:
        with op.batch_alter_table("attendance", schema=None) as batch_op:
            batch_op.drop_column("booked_by_email")
