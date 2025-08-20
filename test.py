import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

DATABASE_URL = "postgresql+asyncpg://hrdb_z7kv_user:qwuuDJIRwvLiMivJPpu02njox0fw4QdR@dpg-d2h3n0buibrs73etp7e0-a.oregon-postgres.render.com/hrdb_z7kv?ssl=require"

async def main():
    engine = create_async_engine(DATABASE_URL, echo=False)
    async with engine.begin() as conn:  # begin => автокоммит
        await conn.execute(text("TRUNCATE TABLE tg_links RESTART IDENTITY CASCADE;"))
        await conn.execute(text("TRUNCATE TABLE tg_surveys RESTART IDENTITY CASCADE;"))
        await conn.execute(text("TRUNCATE TABLE events_dedup RESTART IDENTITY CASCADE;"))
        await conn.execute(text("TRUNCATE TABLE lead_links RESTART IDENTITY CASCADE;"))
        print("Tables truncated successfully")

asyncio.run(main())
