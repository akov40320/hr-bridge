from __future__ import annotations
import asyncio, os
from httpx import HTTPStatusError, TimeoutException, ConnectError

from app.queue import consume, publish_retry, publish_dlq
from app.adapters import hh as hh_adapt, avito as avito_adapt
from app.amo_client import AmoClient, ReauthRequired
from app.logging_setup import setup_logging

setup_logging("INFO")

WORKER_MAX_ATTEMPTS = int(os.getenv("WORKER_MAX_ATTEMPTS", "6"))


def _is_transient(e: Exception) -> bool:
    if isinstance(e, (TimeoutException, ConnectError)):
        return True
    if isinstance(e, HTTPStatusError):
        return e.response.status_code == 429 or 500 <= e.response.status_code < 600
    return False


async def handle(payload: dict, attempts: int):
    try:
        plat = payload.get("platform"); act = payload.get("action")

        if plat == "debug" and act == "echo":
            print("RMQ ECHO:", payload.get("msg")); return

        if plat == "avito" and act == "send_message":
            await avito_adapt.send_message(payload["external_id"], payload["text"]); return

        if plat == "hh" and act == "set_state":
            await hh_adapt.set_employer_state(payload["external_id"], payload["target_state"]); return

        if plat == "avito" and act == "mark_read":
            await avito_adapt.mark_read(payload["external_id"]); return

        if plat == "amo" and act == "amo_create_lead":
            amo = await AmoClient.create()
            await amo.create_leads(payload["lead_body"]); return

        raise RuntimeError(f"unknown task: {payload}")

    except ReauthRequired as e:
        # терминальная для нас — нужна ручная переавторизация
        await publish_dlq(payload, attempts + 1, f"ReauthRequired: {e}")

    except Exception as e:
        if _is_transient(e) and attempts + 1 < WORKER_MAX_ATTEMPTS:
            await publish_retry(payload, attempts + 1)  # вернётся из retry в main
        else:
            await publish_dlq(payload, attempts + 1, str(e))


async def run_forever():
    await consume(handle)


if __name__ == "__main__":
    asyncio.run(run_forever())
