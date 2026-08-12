"""add renewal requests table

Revision ID: a9b8c7d6e5f4
Revises: 4d6e7f8a9b0c
Create Date: 2026-08-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "a9b8c7d6e5f4"
down_revision = "4d6e7f8a9b0c"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if "renewal_requests" in inspector.get_table_names():
        return

    op.create_table(
        "renewal_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=False),
        sa.Column("duration_months", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"]),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_renewal_requests_member_id"), "renewal_requests", ["member_id"], unique=False)
    op.create_index(op.f("ix_renewal_requests_requested_at"), "renewal_requests", ["requested_at"], unique=False)
    op.create_index(op.f("ix_renewal_requests_requested_by_user_id"), "renewal_requests", ["requested_by_user_id"], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if "renewal_requests" not in inspector.get_table_names():
        return

    op.drop_index(op.f("ix_renewal_requests_requested_by_user_id"), table_name="renewal_requests")
    op.drop_index(op.f("ix_renewal_requests_requested_at"), table_name="renewal_requests")
    op.drop_index(op.f("ix_renewal_requests_member_id"), table_name="renewal_requests")
    op.drop_table("renewal_requests")
