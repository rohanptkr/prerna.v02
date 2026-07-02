"""add login failure lock fields

Revision ID: b4e5f6a7c8d9
Revises: c7d8e9f0a1b2
Create Date: 2026-07-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "b4e5f6a7c8d9"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


def upgrade():
    inspector = inspect(op.get_bind())
    if "users" not in inspector.get_table_names():
        return

    existing_cols = [column["name"] for column in inspector.get_columns("users")]
    with op.batch_alter_table("users", schema=None) as batch_op:
        if "failed_login_attempts" not in existing_cols:
            batch_op.add_column(sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"))
        if "is_locked" not in existing_cols:
            batch_op.add_column(sa.Column("is_locked", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    inspector = inspect(op.get_bind())
    if "users" not in inspector.get_table_names():
        return

    existing_cols = [column["name"] for column in inspector.get_columns("users")]
    with op.batch_alter_table("users", schema=None) as batch_op:
        if "is_locked" in existing_cols:
            batch_op.drop_column("is_locked")
        if "failed_login_attempts" in existing_cols:
            batch_op.drop_column("failed_login_attempts")
