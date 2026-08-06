"""add membership history table

Revision ID: 4d6e7f8a9b0c
Revises: 9a8b7c6d5e4f
Create Date: 2026-08-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "4d6e7f8a9b0c"
down_revision = "9a8b7c6d5e4f"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if "membership_history" not in inspector.get_table_names():
        op.create_table(
            "membership_history",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("member_id", sa.Integer(), nullable=False),
            sa.Column("period_start_date", sa.Date(), nullable=False),
            sa.Column("period_end_date", sa.Date(), nullable=False),
            sa.Column("event_type", sa.String(length=32), nullable=False),
            sa.Column("notes", sa.String(length=255), nullable=True),
            sa.Column("changed_by_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["member_id"], ["members.id"]),
            sa.ForeignKeyConstraint(["changed_by_user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_membership_history_member_id"), "membership_history", ["member_id"], unique=False)
        op.create_index(op.f("ix_membership_history_created_at"), "membership_history", ["created_at"], unique=False)

    # Backfill one baseline record per member when current period exists and no history exists yet.
    op.execute(
        sa.text(
            """
            INSERT INTO membership_history (
                member_id, period_start_date, period_end_date, event_type, notes, changed_by_user_id, created_at
            )
            SELECT
                m.id,
                m.membership_start_date,
                m.membership_end_date,
                'Imported',
                'Imported from existing member profile',
                NULL,
                COALESCE(m.registration_date, CURRENT_TIMESTAMP)
            FROM members m
            WHERE m.membership_start_date IS NOT NULL
              AND m.membership_end_date IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM membership_history mh WHERE mh.member_id = m.id
              )
            """
        )
    )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if "membership_history" in inspector.get_table_names():
        op.drop_index(op.f("ix_membership_history_created_at"), table_name="membership_history")
        op.drop_index(op.f("ix_membership_history_member_id"), table_name="membership_history")
        op.drop_table("membership_history")
