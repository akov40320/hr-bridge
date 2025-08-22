from typing import Optional
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import update, delete
from app.db import get_session
from app.db.models import TgSurvey


async def start_or_reset_survey(user_id: int, bot_kind: str, lead_id: int) -> None:
    """Создаёт/сбрасывает сессию: step=0, чистые ответы."""
    async with get_session() as s:
        new_data = {
            "user_id": user_id,
            "bot_kind": bot_kind,
            "lead_id": lead_id,
            "step": 0,
            "city": None,
            "experience": None,
            "time_pref": None,
        }

        existing = (
            await s.execute(
                select(TgSurvey).where(
                    TgSurvey.user_id == user_id, TgSurvey.bot_kind == bot_kind
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            stmt = insert(TgSurvey).values(**new_data).on_conflict_do_nothing()
        else:
            diff = {
                k: v
                for k, v in new_data.items()
                if getattr(existing, k) != v and k not in {"user_id", "bot_kind"}
            }

            if diff:
                stmt = (
                    insert(TgSurvey)
                    .values(**new_data)
                    .on_conflict_do_update(
                        index_elements=[TgSurvey.user_id, TgSurvey.bot_kind],
                        set_=diff,
                    )
                )
            else:
                stmt = insert(TgSurvey).values(**new_data).on_conflict_do_nothing()

        await s.execute(stmt)
        await s.commit()


async def get_survey(user_id: int, bot_kind: str) -> Optional[TgSurvey]:
    async with get_session() as s:
        row = (
            await s.execute(
                select(TgSurvey).where(
                    TgSurvey.user_id == user_id, TgSurvey.bot_kind == bot_kind
                )
            )
        ).scalar_one_or_none()
        return row


async def store_answer_and_advance(user_id: int, bot_kind: str, text: str) -> Optional[TgSurvey]:
    """Сохраняет ответ по текущему step и сдвигает step += 1. Возвращает обновлённую запись."""
    async with get_session() as s:
        row = (
            await s.execute(
                select(TgSurvey).where(
                    TgSurvey.user_id == user_id, TgSurvey.bot_kind == bot_kind
                ).with_for_update()
            )
        ).scalar_one_or_none()
        if not row:
            return None

        if row.step == 0:
            upd = {"city": text, "step": 1}
        elif row.step == 1:
            upd = {"experience": text, "step": 2}
        elif row.step == 2:
            upd = {"time_pref": text, "step": 3}
        else:
            upd = {}

        if upd:
            await s.execute(
                update(TgSurvey)
                .where(TgSurvey.user_id == user_id, TgSurvey.bot_kind == bot_kind)
                .values(**upd)
            )
            await s.commit()

        # перечитаем для актуального состояния
        row = (
            await s.execute(
                select(TgSurvey).where(
                    TgSurvey.user_id == user_id, TgSurvey.bot_kind == bot_kind
                )
            )
        ).scalar_one_or_none()
        return row


async def delete_survey(user_id: int, bot_kind: str) -> None:
    async with get_session() as s:
        await s.execute(
            delete(TgSurvey).where(
                TgSurvey.user_id == user_id, TgSurvey.bot_kind == bot_kind
            )
        )
        await s.commit()
