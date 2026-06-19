"""add attendance table and member_id to daily_seat_bookings

Revision ID: a3f9d821cc47
Revises: 1666d0a980b9
Create Date: 2026-06-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'a3f9d821cc47'
down_revision = '1666d0a980b9'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names()

    # 1. Create attendance table only if it doesn't exist yet
    if 'attendance' not in existing_tables:
        op.create_table(
            'attendance',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('member_id', sa.Integer(), nullable=False),
            sa.Column('attendance_date', sa.Date(), nullable=False),
            sa.Column('login_time', sa.DateTime(), nullable=True),
            sa.Column('logout_time', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['member_id'], ['members.id'], name='fk_attendance_member_id'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('member_id', 'attendance_date', name='uq_member_per_day'),
        )

    # 2. Add member_id to daily_seat_bookings only if column doesn't exist
    existing_cols = [c['name'] for c in inspector.get_columns('daily_seat_bookings')]
    if 'member_id' not in existing_cols:
        with op.batch_alter_table('daily_seat_bookings', schema=None) as batch_op:
            batch_op.add_column(sa.Column('member_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                'fk_daily_seat_booking_member_id',
                'members',
                ['member_id'], ['id']
            )


def downgrade():
    existing_cols = [c['name'] for c in inspect(op.get_bind()).get_columns('daily_seat_bookings')]
    if 'member_id' in existing_cols:
        with op.batch_alter_table('daily_seat_bookings', schema=None) as batch_op:
            batch_op.drop_constraint('fk_daily_seat_booking_member_id', type_='foreignkey')
            batch_op.drop_column('member_id')

    op.drop_table('attendance')
