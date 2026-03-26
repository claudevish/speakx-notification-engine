"""Make notification_events.notification_id nullable for click tracking.

Revision ID: a1b2c3d4e5f6
Revises: c81e04b22196
Create Date: 2026-03-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "5a701e1481e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "notification_events",
        "notification_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "notification_events",
        "notification_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
