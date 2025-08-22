import asyncio


async def with_backoff(coro, *args, **kwargs):
    backoff = 0.5
    for _ in range(6):
        try:
            return await coro(*args, **kwargs)
        except Exception:
            if backoff > 8:
                raise
            await asyncio.sleep(backoff)
            backoff *= 2
