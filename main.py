import asyncio, contextlib

from app.config import settings
from app.worker_rmq import run_forever as rmq_run
import uvicorn
from fastapi import FastAPI
from app.api import router
from app.bootstrap import ensure_tokens
from app.db import init_db

app = FastAPI(title="Recruiting Bridge")
app.include_router(router)


@app.on_event("startup")
async def on_startup():
    await init_db()
    await ensure_tokens()
    if settings.RMQ_ENABLE_CONSUMER:
        app.state.rmq_task = asyncio.create_task(rmq_run())


@app.on_event("shutdown")
async def on_shutdown():
    t = getattr(app.state, "rmq_task", None)
    if t:
        t.cancel()
        with contextlib.suppress(Exception):
            await t


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
