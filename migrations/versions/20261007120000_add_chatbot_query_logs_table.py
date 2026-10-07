"""add chatbot query logs table

Revision ID: 20261007120000
Revises: 3c1c42345125
Create Date: 2026-10-07 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20261007120000"
down_revision = "3c1c42345125"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if "chatbot_query_logs" in inspector.get_table_names():
        return

    op.create_table(
        "chatbot_query_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(length=300), nullable=False),
        sa.Column("theme", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chatbot_query_logs_created_at"), "chatbot_query_logs", ["created_at"], unique=False)
    op.create_index(op.f("ix_chatbot_query_logs_theme"), "chatbot_query_logs", ["theme"], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if "chatbot_query_logs" not in inspector.get_table_names():
        return

    op.drop_index(op.f("ix_chatbot_query_logs_theme"), table_name="chatbot_query_logs")
    op.drop_index(op.f("ix_chatbot_query_logs_created_at"), table_name="chatbot_query_logs")
    op.drop_table("chatbot_query_logs")
