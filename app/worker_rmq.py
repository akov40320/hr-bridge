from __future__ import annotations
import asyncio, os
from httpx import HTTPStatusError, TimeoutException, ConnectError

from app.queue import consume, publish_retry
from app.adapters import hh as hh_adapt, avito as avito_adapt
from app.amo_client import AmoClient, ReauthRequired
from app.config import settings

WORKER_MAX_ATTEMPTS = int(os.getenv("WORKER_MAX_ATTEMPTS", "6"))


def _is_transient(e: Exception) -> bool:
    if isinstance(e, (TimeoutException, ConnectError)):
        return True
    if isinstance(e, HTTPStatusError):
        return e.response.status_code == 429 or 500 <= e.response.status_code < 600
    return False


async def handle(payload: dict, attempts: int):
    try:
        plat = payload.get("platform")
        act = payload.get("action")

        if plat == "debug" and act == "echo":
            print("RMQ ECHO:", payload.get("msg"))
            return

        if plat == "avito" and act == "send_message":
            avito_adapt.send_message(payload["external_id"], payload["text"])
            return

        if plat == "hh" and act == "set_state":
            hh_adapt.set_employer_state(payload["external_id"], payload["target_state"])
            return

        if plat == "avito" and act == "mark_read":
            avito_adapt.mark_read(payload["external_id"])
            return

        if plat == "amo" and act == "amo_create_lead":
            amo = await AmoClient.create()
            await amo.create_leads(payload["lead_body"])
            return

        raise RuntimeError(f"unknown task: {payload}")

    except ReauthRequired as e:
        # терминальная для нас — нужна ручная переавторизация
        # просто проглатываем: задача не будет ретраиться
        print("ReauthRequired:", e)

    except Exception as e:
        if _is_transient(e) and attempts + 1 < WORKER_MAX_ATTEMPTS:
            await publish_retry(payload, attempts + 1)  # через TTL вернётся в main
        else:
            print("Task failed terminally:", e)


async def run_forever():
    await consume(handle)


if __name__ == "__main__":
    asyncio.run(run_forever())
