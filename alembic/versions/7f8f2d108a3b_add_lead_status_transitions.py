"""add lead status transitions table"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7f8f2d108a3b'
down_revision: Union[str, Sequence[str], None] = '9c2466183e7f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'lead_status_transitions',
        sa.Column('lead_id', sa.BigInteger(), nullable=False),
        sa.Column('status_id', sa.BigInteger(), nullable=False),
        sa.Column('ts', sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint('lead_id'),
    )


def downgrade() -> None:
    op.drop_table('lead_status_transitions')
