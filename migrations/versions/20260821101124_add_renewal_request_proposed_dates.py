"""add renewal request proposed dates

Revision ID: 20260821101124
Revises: f1a2b3c4d5e6
Create Date: 2026-08-21 10:11:24.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = '20260821101124'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("renewal_requests")}
    if "proposed_start_date" not in columns:
        op.add_column("renewal_requests", sa.Column("proposed_start_date", sa.Date(), nullable=True))
    if "proposed_end_date" not in columns:
        op.add_column("renewal_requests", sa.Column("proposed_end_date", sa.Date(), nullable=True))

def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("renewal_requests")}
    if "proposed_end_date" in columns:
        op.drop_column("renewal_requests", "proposed_end_date")
    if "proposed_start_date" in columns:
        op.drop_column("renewal_requests", "proposed_start_date")
