import asyncio
from app.bootstrap import ensure_tokens
from app.tg_bots import main


async def run():
    await ensure_tokens()
    await main()


if __name__ == "__main__":
    asyncio.run(run())
