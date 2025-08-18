import asyncio
from app.store import fetch_and_lock, mark_task_done, mark_task_failed
from app.adapters import hh as hh_adapt, avito as avito_adapt
from app.amo_client import AmoClient


async def handle_task(p: dict):
    if p["platform"] == "hh" and p["action"] == "set_state":
        hh_adapt.set_employer_state(p["external_id"], p["target_state"])
        return
    if p["platform"] == "avito" and p["action"] == "mark_read":
        avito_adapt.mark_read(p["external_id"])
        return
    if p["platform"] == "amo" and p["action"] == "amo_create_lead":
        amo = await AmoClient.create()
        await amo.create_leads(p["lead_body"])
        return
    raise RuntimeError(f"Unknown task: {p}")


async def loop():
    while True:
        tasks = await fetch_and_lock(limit=50)
        if not tasks:
            await asyncio.sleep(2)
            continue
        for t in tasks:
            try:
                await handle_task(t.payload)
                await mark_task_done(t.id)
            except Exception as e:
                await mark_task_failed(t.id, str(e))
        await asyncio.sleep(0.2)


if __name__ == "__main__":
    asyncio.run(loop())
