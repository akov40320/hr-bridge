import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

DATABASE_URL = "postgresql+asyncpg://hrdb_z7kv_user:qwuuDJIRwvLiMivJPpu02njox0fw4QdR@dpg-d2h3n0buibrs73etp7e0-a.oregon-postgres.render.com/hrdb_z7kv?ssl=require"

async def main():
    engine = create_async_engine(DATABASE_URL, echo=False)
    async with engine.begin() as conn:  # begin => автокоммит
        res = await conn.execute(
            text("UPDATE tg_links SET conversation_id = NULL, updated_at = NOW();")
        )
        print("rows updated:", res.rowcount)

asyncio.run(main())
