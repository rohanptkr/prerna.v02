"""add lab to members

Revision ID: b7c8d9e0f1a2
Revises: f1a2b3c4d5e6
Create Date: 2026-07-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "b7c8d9e0f1a2"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if "members" not in inspector.get_table_names():
        return

    existing_cols = [c["name"] for c in inspector.get_columns("members")]
    if "lab" not in existing_cols:
        with op.batch_alter_table("members", schema=None) as batch_op:
            batch_op.add_column(sa.Column("lab", sa.String(length=16), nullable=False, server_default="Lab 1"))


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if "members" not in inspector.get_table_names():
        return

    existing_cols = [c["name"] for c in inspector.get_columns("members")]
    if "lab" in existing_cols:
        with op.batch_alter_table("members", schema=None) as batch_op:
            batch_op.drop_column("lab")
