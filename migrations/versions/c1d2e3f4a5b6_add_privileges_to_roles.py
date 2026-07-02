"""add privileges to roles

Revision ID: c1d2e3f4a5b6
Revises: b4e5f6a7c8d9
Create Date: 2026-07-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "c1d2e3f4a5b6"
down_revision = "b4e5f6a7c8d9"
branch_labels = None
depends_on = None


def upgrade():
    inspector = inspect(op.get_bind())
    if "roles" not in inspector.get_table_names():
        return

    existing_cols = [column["name"] for column in inspector.get_columns("roles")]
    with op.batch_alter_table("roles", schema=None) as batch_op:
        if "privileges" not in existing_cols:
            batch_op.add_column(sa.Column("privileges", sa.String(length=512), nullable=False, server_default=""))


def downgrade():
    inspector = inspect(op.get_bind())
    if "roles" not in inspector.get_table_names():
        return

    existing_cols = [column["name"] for column in inspector.get_columns("roles")]
    with op.batch_alter_table("roles", schema=None) as batch_op:
        if "privileges" in existing_cols:
            batch_op.drop_column("privileges")
