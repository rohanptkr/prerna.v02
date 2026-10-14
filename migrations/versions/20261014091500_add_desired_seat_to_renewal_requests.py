"""add desired seat number to renewal requests

Revision ID: 20261014091500
Revises: 20261007120000
Create Date: 2026-10-14 09:15:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20261014091500"
down_revision = "20261007120000"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if "renewal_requests" not in inspector.get_table_names():
        return

    columns = {c["name"] for c in inspector.get_columns("renewal_requests")}
    if "desired_seat_number" not in columns:
        op.add_column("renewal_requests", sa.Column("desired_seat_number", sa.String(length=16), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if "renewal_requests" not in inspector.get_table_names():
        return

    columns = {c["name"] for c in inspector.get_columns("renewal_requests")}
    if "desired_seat_number" in columns:
        op.drop_column("renewal_requests", "desired_seat_number")
