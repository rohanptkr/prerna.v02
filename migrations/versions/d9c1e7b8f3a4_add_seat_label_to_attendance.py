"""add seat_label to attendance

Revision ID: d9c1e7b8f3a4
Revises: a3f9d821cc47
Create Date: 2026-06-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "d9c1e7b8f3a4"
down_revision = "a3f9d821cc47"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    existing_tables = inspector.get_table_names()
    if "attendance" not in existing_tables:
        return

    existing_cols = [c["name"] for c in inspector.get_columns("attendance")]
    if "seat_label" not in existing_cols:
        with op.batch_alter_table("attendance", schema=None) as batch_op:
            batch_op.add_column(sa.Column("seat_label", sa.String(length=64), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    existing_tables = inspector.get_table_names()
    if "attendance" not in existing_tables:
        return

    existing_cols = [c["name"] for c in inspector.get_columns("attendance")]
    if "seat_label" in existing_cols:
        with op.batch_alter_table("attendance", schema=None) as batch_op:
            batch_op.drop_column("seat_label")
