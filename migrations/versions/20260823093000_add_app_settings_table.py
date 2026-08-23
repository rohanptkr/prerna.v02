"""add app settings table

Revision ID: 20260823093000
Revises: 20260821101124
Create Date: 2026-08-23 09:30:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = "20260823093000"
down_revision = "20260821101124"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if "app_settings" in inspector.get_table_names():
        return

    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("setting_key", sa.String(length=64), nullable=False),
        sa.Column("setting_value", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_app_settings_setting_key"), "app_settings", ["setting_key"], unique=True)


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if "app_settings" not in inspector.get_table_names():
        return

    op.drop_index(op.f("ix_app_settings_setting_key"), table_name="app_settings")
    op.drop_table("app_settings")