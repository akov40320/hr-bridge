"""multi-account hh/avito

Revision ID: 340d65b94b03
Revises: 3ffd507a8db4
Create Date: 2025-08-20 11:09:06.433896

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '340d65b94b03'
down_revision: Union[str, Sequence[str], None] = '3ffd507a8db4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # --- tokens ---
    # 1) добавить owner_id
    op.add_column("tokens", sa.Column("owner_id", sa.Text(), nullable=True))

    # 2) добавить surrogate PK: id BIGSERIAL
    op.add_column("tokens", sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=True))
    # выставим DEFAULT nextval (аналог BIGSERIAL)
    op.execute("CREATE SEQUENCE IF NOT EXISTS tokens_id_seq OWNED BY tokens.id;")
    op.execute("ALTER TABLE tokens ALTER COLUMN id SET DEFAULT nextval('tokens_id_seq');")

    # 3) заполнить id для существующих строк
    op.execute("UPDATE tokens SET id = nextval('tokens_id_seq') WHERE id IS NULL;")

    # 4) заменить PK: снять старый PK (обычно tokens_pkey), повесить новый на id
    # проверь имя PK перед запуском: в большинстве случаев 'tokens_pkey'
    op.drop_constraint("tokens_pkey", "tokens", type_="primary")
    op.create_primary_key("tokens_pkey", "tokens", ["id"])

    # 5) индексы и уникальность
    op.create_index("ix_tokens_service", "tokens", ["service"], unique=False)
    op.create_index("ix_tokens_owner_id", "tokens", ["owner_id"], unique=False)
    op.create_unique_constraint("ux_tokens_service_owner", "tokens", ["service", "owner_id"])

    # --- lead_links ---
    op.add_column("lead_links", sa.Column("owner_id", sa.Text(), nullable=True))
    op.create_index("ix_lead_links_owner_id", "lead_links", ["owner_id"], unique=False)


def downgrade():
    # --- lead_links ---
    op.drop_index("ix_lead_links_owner_id", table_name="lead_links")
    op.drop_column("lead_links", "owner_id")

    # --- tokens ---
    # снять новые индексы/уникальность
    op.drop_constraint("ux_tokens_service_owner", "tokens", type_="unique")
    op.drop_index("ix_tokens_owner_id", table_name="tokens")
    op.drop_index("ix_tokens_service", table_name="tokens")

    # вернуть старый PK (по service)
    op.drop_constraint("tokens_pkey", "tokens", type_="primary")
    op.create_primary_key("tokens_pkey", "tokens", ["service"])

    # убрать id
    op.execute("ALTER TABLE tokens ALTER COLUMN id DROP DEFAULT;")
    op.drop_column("tokens", "id")
    # по желанию: удалить sequence
    op.execute("DROP SEQUENCE IF EXISTS tokens_id_seq;")

    # убрать owner_id
    op.drop_column("tokens", "owner_id")