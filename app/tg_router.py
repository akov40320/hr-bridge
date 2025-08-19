import logging
from aiogram import Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.config import settings
from app.amo_client import AmoClient
from app.store_chat import upsert_tg_link, get_by_user, set_conversation
from app.store_survey import (
    start_or_reset_survey, get_survey, store_answer_and_advance, delete_survey
)
from app.amochats import send_text

logger = logging.getLogger("tg.router")


def _parse_start_arg(text: str) -> int | None:
    parts = (text or "").strip().split(maxsplit=1)
    if len(parts) == 2 and parts[0].startswith("/start"):
        try:
            return int(parts[1])
        except Exception:
            return None
    return None


def _survey_prompt(step: int) -> str:
    if step == 0: return "В каком вы городе?"
    if step == 1: return "Опишите кратко опыт по вакансии."
    if step == 2: return "Когда вам удобно на связи? (например, завтра после 14:00)"
    return "Спасибо, опрос завершён!"


def _survey_summary(city: str | None, experience: str | None, time_pref: str | None) -> str:
    return (
        "Итоги опроса:\n"
        f"• Город: {city or '-'}\n"
        f"• Опыт: {experience or '-'}\n"
        f"• Связь: {time_pref or '-'}"
    )


def _pretty_tg_identity(m: Message) -> str:
    # username с @ если есть, иначе читаемый id
    return f"@{m.from_user.username}" if m.from_user.username else f"id:{m.from_user.id}"


async def mark_went_to_bot(lead_id: int, bot_kind: str, identity: str):
    amo = await AmoClient.create()
    note = f"[{bot_kind}] Кандидат перешёл в бота (TG {identity})."
    # 1) сначала заметка — как первичный факт
    await amo.add_note(lead_id, note)
    # 2) затем тег — как «статусный» признак
    await amo.add_tags(lead_id, [settings.AMO_TAG_WENT_TO_BOT])


def make_router(bot_kind: str) -> Dispatcher:
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def on_start(m: Message):
        lead_id = _parse_start_arg(m.text or "")
        if not lead_id:
            await m.answer("Нужно открыть бота по ссылке из сообщения, чтобы я увидел вашу заявку.")
            return

        await upsert_tg_link(m.from_user.id, bot_kind, lead_id)
        await start_or_reset_survey(m.from_user.id, bot_kind, lead_id)

        await mark_went_to_bot(lead_id, bot_kind, _pretty_tg_identity(m))
        await m.answer("Здравствуйте! Нужны пару уточнений по заявке.\n\n" + _survey_prompt(0))
        logger.info("[%s] /start user_id=%s lead_id=%s", bot_kind, m.from_user.id, lead_id)

    @dp.message(F.text)
    async def on_text(m: Message):
        text = m.text or ""
        survey = await get_survey(m.from_user.id, bot_kind)

        # --- определяем lead_id/conv_id даже если опроса уже нет (чат-режим) ---
        lead_id = None
        conv_id = None
        if survey:
            lead_id = survey.lead_id
        else:
            link = await get_by_user(m.from_user.id, bot_kind)
            if link:
                lead_id = link.lead_id
                conv_id = link.conversation_id

        if not lead_id:
            await m.answer("Нажмите /start по ссылке из сообщения, чтобы привязать диалог к заявке.")
            return

        # --- зеркалим в Amo и (если включено) в AmoChats ---
        try:
            amo = await AmoClient.create()
            await amo.add_note(lead_id, f"[TG->{bot_kind}] {text}")

            if settings.AMOCHATS_ENABLED:
                try:
                    new_conv_id = await send_text(
                        lead_id,
                        text,
                        tg_user_id=m.from_user.id,
                        tg_user_name=m.from_user.username,
                        conversation_id=conv_id,
                    )
                    if new_conv_id and (not conv_id or new_conv_id != conv_id):
                        await set_conversation(m.from_user.id, bot_kind, new_conv_id)
                except Exception as e:
                    logger.warning("amochats send error: %s", e)
        except Exception as e:
            logger.warning("add_note error: %s", e)

        # --- если идёт опрос — продолжаем шаги, иначе ведём себя как «чат» ---
        if survey:
            survey = await store_answer_and_advance(m.from_user.id, bot_kind, text)
            if not survey:
                await m.answer("Сессия не найдена. Нажмите /start ещё раз.")
                return

            if survey.step <= 2:
                await m.answer(_survey_prompt(survey.step))
            else:
                summary = _survey_summary(survey.city, survey.experience, survey.time_pref)
                try:
                    await amo.add_tags(lead_id, [settings.AMO_TAG_SURVEY_DONE])
                    await amo.add_note(lead_id, f"[{bot_kind}] {summary}")
                except Exception as e:
                    logger.exception("finish note/tag error: %s", e)
                await delete_survey(m.from_user.id, bot_kind)
                await m.answer("Спасибо! Мы передали информацию рекрутеру. С вами свяжутся.")
                logger.info("[%s] survey finished user_id=%s lead_id=%s", bot_kind, m.from_user.id, lead_id)
        else:
            # чат-режим после опроса — без навязчивых подсказок
            # можно вообще ничего не отвечать, либо короткое подтверждение:
            # await m.answer("Принято, передал(а) рекрутеру.")
            pass

    return dp
