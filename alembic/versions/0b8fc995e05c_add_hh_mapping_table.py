"""add hh_mapping table

Revision ID: 0b8fc995e05c
Revises: ee1b2ca2553f
Create Date: 2025-08-21 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0b8fc995e05c'
down_revision: Union[str, Sequence[str], None] = 'ee1b2ca2553f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'hh_mapping',
        sa.Column('amo_status_id', sa.BigInteger(), primary_key=True, nullable=False),
        sa.Column('hh_code', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('hh_mapping')
