import asyncio
import asyncpg

DBURL = "postgresql://hrdb_z7kv_user:qwuuDJIRwvLiMivJPpu02njox0fw4QdR@dpg-d2h3n0buibrs73etp7e0-a.oregon-postgres.render.com/hrdb_z7kv?sslmode=require"

SQL = """
ALTER TABLE tokens ADD COLUMN IF NOT EXISTS owner_id TEXT;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='tokens' AND column_name='id'
  ) THEN
    ALTER TABLE tokens ADD COLUMN id BIGSERIAL;
  END IF;
END$$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tokens'::regclass AND contype='p' AND conname='tokens_pkey'
  ) THEN
    ALTER TABLE tokens DROP CONSTRAINT tokens_pkey;
  END IF;
END$$;

ALTER TABLE tokens ADD PRIMARY KEY (id);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tokens'::regclass AND conname = 'ux_tokens_service_owner'
  ) THEN
    ALTER TABLE tokens ADD CONSTRAINT ux_tokens_service_owner UNIQUE (service, owner_id);
  END IF;
END$$;

ALTER TABLE lead_links ADD COLUMN IF NOT EXISTS owner_id TEXT;
CREATE INDEX IF NOT EXISTS ix_lead_links_owner_id ON lead_links(owner_id);
"""

async def main():
    conn = await asyncpg.connect(DBURL)
    try:
        await conn.execute(SQL)
        print("✅ Миграция применена успешно")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
