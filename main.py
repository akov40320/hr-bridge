import contextlib
import uvicorn
from fastapi import FastAPI
from app.api import router, admin
from app.api_amochats import router_amo_chats
from app.bootstrap import ensure_tokens
from app.config import settings
from app.db import init_db
from app.tg_webhooks import router as tg_wh_router
from app.logging_setup import setup_logging

setup_logging("INFO")

app = FastAPI(title="Recruiting Bridge")
app.include_router(router)
app.include_router(admin)
app.include_router(router_amo_chats)




if settings.TELEGRAM_WEBHOOK_MODE:
    app.include_router(tg_wh_router)


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
