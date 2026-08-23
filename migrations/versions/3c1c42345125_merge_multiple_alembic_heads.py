"""Merge multiple alembic heads

Revision ID: 3c1c42345125
Revises: 20260823093000, a9b8c7d6e5f4
Create Date: 2026-08-23 12:11:30.031140

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3c1c42345125'
down_revision = ('20260823093000', 'a9b8c7d6e5f4')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
