"""add admission profile fields to members

Revision ID: e4c2b9a1d7f6
Revises: d9c1e7b8f3a4
Create Date: 2026-06-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "e4c2b9a1d7f6"
down_revision = "d9c1e7b8f3a4"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if "members" not in inspector.get_table_names():
        return

    existing_cols = [c["name"] for c in inspector.get_columns("members")]
    with op.batch_alter_table("members", schema=None) as batch_op:
        if "aadhaar_number" not in existing_cols:
            batch_op.add_column(sa.Column("aadhaar_number", sa.String(length=12), nullable=True))
        if "date_of_birth" not in existing_cols:
            batch_op.add_column(sa.Column("date_of_birth", sa.Date(), nullable=True))
        if "age" not in existing_cols:
            batch_op.add_column(sa.Column("age", sa.Integer(), nullable=True))
        if "gender" not in existing_cols:
            batch_op.add_column(sa.Column("gender", sa.String(length=16), nullable=True))
        if "school_name" not in existing_cols:
            batch_op.add_column(sa.Column("school_name", sa.String(length=120), nullable=True))
        if "emergency_contact_name" not in existing_cols:
            batch_op.add_column(sa.Column("emergency_contact_name", sa.String(length=120), nullable=True))
        if "emergency_contact_number" not in existing_cols:
            batch_op.add_column(sa.Column("emergency_contact_number", sa.String(length=30), nullable=True))

    # Add a unique constraint for Aadhaar once column exists.
    # Safe on SQLite through batch mode.
    existing_unique_names = {u.get("name") for u in inspector.get_unique_constraints("members")}
    if "uq_members_aadhaar_number" not in existing_unique_names:
        with op.batch_alter_table("members", schema=None) as batch_op:
            batch_op.create_unique_constraint("uq_members_aadhaar_number", ["aadhaar_number"])


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if "members" not in inspector.get_table_names():
        return

    existing_cols = [c["name"] for c in inspector.get_columns("members")]
    with op.batch_alter_table("members", schema=None) as batch_op:
        existing_unique_names = {u.get("name") for u in inspector.get_unique_constraints("members")}
        if "uq_members_aadhaar_number" in existing_unique_names:
            batch_op.drop_constraint("uq_members_aadhaar_number", type_="unique")

        if "emergency_contact_number" in existing_cols:
            batch_op.drop_column("emergency_contact_number")
        if "emergency_contact_name" in existing_cols:
            batch_op.drop_column("emergency_contact_name")
        if "school_name" in existing_cols:
            batch_op.drop_column("school_name")
        if "gender" in existing_cols:
            batch_op.drop_column("gender")
        if "age" in existing_cols:
            batch_op.drop_column("age")
        if "date_of_birth" in existing_cols:
            batch_op.drop_column("date_of_birth")
        if "aadhaar_number" in existing_cols:
            batch_op.drop_column("aadhaar_number")
