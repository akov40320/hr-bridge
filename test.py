import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

DATABASE_URL = "postgresql+asyncpg://hrdb_z7kv_user:qwuuDJIRwvLiMivJPpu02njox0fw4QdR@dpg-d2h3n0buibrs73etp7e0-a.oregon-postgres.render.com/hrdb_z7kv?ssl=require"

async def main():
    engine = create_async_engine(DATABASE_URL, echo=False)
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT service, owner_id, access_token, refresh_token, expires_at FROM tokens WHERE service='avito'")
        )
        rows = result.fetchall()
        for row in rows:
            print("Service:", row.service)
            print("Owner:", row.owner_id)
            print("Access token:", row.access_token)
            print("Refresh token:", row.refresh_token)
            print("Expires at:", row.expires_at)
            print("-" * 40)

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
