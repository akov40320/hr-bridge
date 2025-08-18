import contextlib

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


@app.on_event("shutdown")
async def on_shutdown():
    t = getattr(app.state, "rmq_task", None)
    if t:
        t.cancel()
        with contextlib.suppress(Exception):
            await t


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
