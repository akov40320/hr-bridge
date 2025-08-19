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
from app.amochats import send_text_from_client, ensure_chat_created, send_text_from_manager

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

    async def _ensure_conv_id_for(m: Message, bot_kind: str, lead_id: int, conv_id: str | None) -> str | None:
        if conv_id:
            return conv_id
        if not settings.AMOCHATS_ENABLED:
            return None
        try:
            cid = await ensure_chat_created(
                lead_id=lead_id,
                tg_user_id=m.from_user.id,
                tg_user_name=m.from_user.username
            )
            await set_conversation(m.from_user.id, bot_kind, cid)
            logger.info("[%s] conv saved user_id=%s lead=%s conv=%s", bot_kind, m.from_user.id, lead_id, cid)
            return cid
        except Exception as e:
            logger.warning("ensure_chat_created error: %s", e)
            return None

    async def _answer_and_mirror(m: Message, text: str, bot_kind: str, lead_id: int, conv_id: str | None):
        await m.answer(text)
        cid = await _ensure_conv_id_for(m, bot_kind, lead_id, conv_id)
        if settings.AMOCHATS_ENABLED and cid:
            try:
                await send_text_from_manager(
                    conversation_id=cid,
                    user_id=m.from_user.id,
                    user_name=m.from_user.username,
                    avatar=None,
                    text=text,
                )
                logger.info("bot->amo mirrored: conv=%s text_len=%d", cid, len(text))
            except Exception as e:
                logger.warning("mirror to amo error: %s", e)

    @dp.message(CommandStart())
    async def on_start(m: Message):
        lead_id = _parse_start_arg(m.text or "")
        if not lead_id:
            # Это системное сообщение — в Amo не зеркалим
            await m.answer("Нужно открыть бота по ссылке из сообщения, чтобы я увидел вашу заявку.")
            return

        await upsert_tg_link(m.from_user.id, bot_kind, lead_id)

        # заранее пытаемся создать чат и сохранить conversation_id (если включено)
        conv_id = None
        if settings.AMOCHATS_ENABLED:
            try:
                conv_id = await ensure_chat_created(
                    lead_id=lead_id,
                    tg_user_id=m.from_user.id,
                    tg_user_name=m.from_user.username
                )
                await set_conversation(m.from_user.id, bot_kind, conv_id)
                logger.info("[%s] ensure_chat_created -> %s", bot_kind, conv_id)
            except Exception as e:
                logger.warning("ensure_chat_created error: %s", e)

        await start_or_reset_survey(m.from_user.id, bot_kind, lead_id)
        await mark_went_to_bot(lead_id, bot_kind, _pretty_tg_identity(m))

        greeting = "Здравствуйте! Нужны пару уточнений по заявке.\n\n" + _survey_prompt(0)
        await _answer_and_mirror(m, greeting, bot_kind, lead_id, conv_id)

        logger.info("[%s] /start user_id=%s lead_id=%s", bot_kind, m.from_user.id, lead_id)

    @dp.message(F.text)
    async def on_text(m: Message):
        text = m.text or ""
        survey = await get_survey(m.from_user.id, bot_kind)

        # определяем lead_id/conv_id даже если опроса уже нет (чат-режим)
        lead_id: int | None = None
        conv_id: str | None = None
        if survey:
            lead_id = survey.lead_id
        else:
            link = await get_by_user(m.from_user.id, bot_kind)
            if link:
                lead_id = link.lead_id
                conv_id = link.conversation_id

        if not lead_id:
            # без привязки к заявке в Amo зеркалить нечего
            await m.answer("Нажмите /start по ссылке из сообщения, чтобы привязать диалог к заявке.")
            return

        # зеркалим входящее от кандидата в Amo (заметка) и AmoChats (как клиент)
        try:
            amo = await AmoClient.create()
            await amo.add_note(lead_id, f"[TG->{bot_kind}] {text}")

            if settings.AMOCHATS_ENABLED:
                try:
                    new_conv_id = await send_text_from_client(
                        lead_id=lead_id,
                        text=text,
                        tg_user_id=m.from_user.id,
                        tg_user_name=m.from_user.username,
                        conversation_id=conv_id,
                    )
                    if new_conv_id and new_conv_id != conv_id:
                        logger.info("Saving conv_id for %s/%s -> %s", m.from_user.id, bot_kind, new_conv_id)
                        await set_conversation(m.from_user.id, bot_kind, new_conv_id)
                        conv_id = new_conv_id
                except Exception as e:
                    logger.warning("amochats send error: %s", e)
        except Exception as e:
            logger.warning("add_note error: %s", e)

        # продолжаем опрос или работаем как обычный чат
        if survey:
            survey = await store_answer_and_advance(m.from_user.id, bot_kind, text)
            if not survey:
                await _answer_and_mirror(m, "Сессия не найдена. Нажмите /start ещё раз.", bot_kind, lead_id, conv_id)
                return

            if survey.step <= 2:
                await _answer_and_mirror(m, _survey_prompt(survey.step), bot_kind, lead_id, conv_id)
            else:
                summary = _survey_summary(survey.city, survey.experience, survey.time_pref)
                try:
                    amo2 = await AmoClient.create()
                    await amo2.add_tags(lead_id, [settings.AMO_TAG_SURVEY_DONE])
                    await amo2.add_note(lead_id, f"[{bot_kind}] {summary}")
                except Exception as e:
                    logger.exception("finish note/tag error: %s", e)

                await delete_survey(m.from_user.id, bot_kind)
                await _answer_and_mirror(
                    m,
                    "Спасибо! Мы передали информацию рекрутеру. С вами свяжутся.",
                    bot_kind, lead_id, conv_id
                )
                logger.info("[%s] survey finished user_id=%s lead_id=%s", bot_kind, m.from_user.id, lead_id)
        else:
            # чат-режим после опроса — без автосообщений
            pass

    return dp

