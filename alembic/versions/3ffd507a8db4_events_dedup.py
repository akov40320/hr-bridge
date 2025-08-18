"""events_dedup

Revision ID: 3ffd507a8db4
Revises: eca5df20771b
Create Date: 2025-08-18 20:24:52.386066

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3ffd507a8db4'
down_revision: Union[str, Sequence[str], None] = 'eca5df20771b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "events_dedup",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_events_dedup_created_at", "events_dedup", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_events_dedup_created_at", table_name="events_dedup")
    op.drop_table("events_dedup")