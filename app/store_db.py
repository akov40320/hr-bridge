from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from app.db import get_session
from app.models import LeadLink, Task


async def save_link(lead_id: int, platform: str, vacancy_id: str, external_id: str | None):
    async with get_session() as s:
        stmt = insert(LeadLink).values(
            lead_id=lead_id, platform=platform, vacancy_id=vacancy_id, external_id=external_id
        ).on_conflict_do_update(
            index_elements=[LeadLink.lead_id],
            set_={"platform": platform, "vacancy_id": vacancy_id, "external_id": external_id}
        )
        await s.execute(stmt)
        await s.commit()


async def find_link(lead_id: int) -> dict | None:
    async with get_session() as s:
        row = (await s.execute(select(LeadLink).where(LeadLink.lead_id == lead_id))).scalar_one_or_none()
        if not row:
            return None
        return {"lead_id": row.lead_id, "platform": row.platform, "vacancy_id": row.vacancy_id,
                "external_id": row.external_id}


async def enqueue_pending(task: dict):
    # task: {"platform": "...", "action": "...", ...payload...}
    async with get_session() as s:
        await s.execute(insert(Task).values(
            platform=task["platform"],
            action=task["action"],
            payload=task
        ))
        await s.commit()


# для вашей /admin/sync/replay
async def list_queued(platforms: list[str] | None = None):
    async with get_session() as s:
        q = select(Task).where(Task.status == "queued")
        if platforms:
            from sqlalchemy import or_
            q = q.where(Task.platform.in_(platforms))
        rows = (await s.execute(q)).scalars().all()
        return [{"id": r.id, "platform": r.platform, "action": r.action, "payload": r.payload} for r in rows]


async def mark_task_done(task_id: int):
    async with get_session() as s:
        await s.execute(update(Task).where(Task.id == task_id).values(status="done"))
        await s.commit()
