"""add_notification_image_path

Revision ID: 5a701e1481e2
Revises: 7832c636fe7a
Create Date: 2026-03-10 14:49:07.431546

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '5a701e1481e2'
down_revision: Union[str, None] = '7832c636fe7a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('notifications', sa.Column('image_path', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('notifications', 'image_path')
