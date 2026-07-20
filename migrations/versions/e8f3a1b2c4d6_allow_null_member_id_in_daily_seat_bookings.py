"""allow null member_id in daily_seat_bookings

Revision ID: e8f3a1b2c4d6
Revises: c1d2e3f4a5b6, b7c8d9e0f1a2
Create Date: 2026-07-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "e8f3a1b2c4d6"
down_revision = ("c1d2e3f4a5b6", "b7c8d9e0f1a2")
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if "daily_seat_bookings" not in inspector.get_table_names():
        return

    columns = {column["name"]: column for column in inspector.get_columns("daily_seat_bookings")}
    member_id_col = columns.get("member_id")
    if not member_id_col:
        return

    if member_id_col.get("nullable") is False:
        with op.batch_alter_table("daily_seat_bookings", schema=None) as batch_op:
            batch_op.alter_column("member_id", existing_type=sa.Integer(), nullable=True)


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if "daily_seat_bookings" not in inspector.get_table_names():
        return

    columns = {column["name"]: column for column in inspector.get_columns("daily_seat_bookings")}
    member_id_col = columns.get("member_id")
    if not member_id_col:
        return

    null_count = bind.execute(text("SELECT COUNT(*) FROM daily_seat_bookings WHERE member_id IS NULL")).scalar() or 0
    if null_count > 0:
        return

    if member_id_col.get("nullable") is True:
        with op.batch_alter_table("daily_seat_bookings", schema=None) as batch_op:
            batch_op.alter_column("member_id", existing_type=sa.Integer(), nullable=False)
