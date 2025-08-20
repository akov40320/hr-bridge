import os, asyncio, asyncpg

dsn = "postgresql://hrdb_z7kv_user:qwuuDJIRwvLiMivJPpu02njox0fw4QdR@dpg-d2h3n0buibrs73etp7e0-a.oregon-postgres.render.com/hrdb_z7kv?sslmode=require"

async def main():
    conn = await asyncpg.connect(dsn)
    print(await conn.fetchval("select 1"))
    await conn.close()

asyncio.run(main())
