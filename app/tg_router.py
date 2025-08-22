import logging
from aiogram import Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.core.config import settings
from app.store_chat import upsert_tg_link, get_by_user
from app.services.queue import rabbitmq, RabbitMQClient
from app.services.survey import (
    parse_start_arg,
    survey_prompt,
    survey_summary,
    pretty_tg_identity,
)
from app.services.survey_service import SurveyService

logger = logging.getLogger("tg.router")


def make_router(bot_kind: str, queue_client: RabbitMQClient = rabbitmq) -> Dispatcher:
    dp = Dispatcher()
    svc = SurveyService(queue_client)

    async def _answer_and_mirror(m: Message, text: str, bot_kind: str, lead_id: int, conv_id: str | None):
        # 1) отвечаем в TG
        await m.answer(text)
        # 2) отправляем в AmoChats через RMQ (воркер создаст чат при необходимости)
        msg_key = f"bot_to_amo:{lead_id}:{m.message_id}"
        await queue_client.publish_task({
            "platform": "mirror",
            "action": "bot_to_amo",
            "text": text,
            "user_id": m.from_user.id,
            "user_name": m.from_user.username,
            "conversation_id": conv_id,
            "lead_id": lead_id,
            "msg_key": msg_key,
        })

    @dp.message(CommandStart())
    async def on_start(m: Message):
        lead_id = parse_start_arg(m.text or "")
        if not lead_id:
            await m.answer("Нужно открыть бота по ссылке из сообщения, чтобы я увидел вашу заявку.")
            return

        await upsert_tg_link(m.from_user.id, bot_kind, lead_id)
        await svc.start(m.from_user.id, bot_kind, lead_id, pretty_tg_identity(m))

        greeting = "Здравствуйте! Нужны пару уточнений по заявке.\n\n" + survey_prompt(0)
        await _answer_and_mirror(m, greeting, bot_kind, lead_id, conv_id=None)

        logger.info("[%s] /start user_id=%s lead_id=%s", bot_kind, m.from_user.id, lead_id)

    @dp.message(F.text)
    async def on_text(m: Message):
        text = m.text or ""
        survey = await svc.get(m.from_user.id, bot_kind)

        # найдём привязку даже если опрос завершён
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
            await m.answer("Нажмите /start по ссылке из сообщения, чтобы привязать диалог к заявке.")
            return

        # TG -> Amo (заметка + AmoChats) целиком через воркер
        msg_key = f"tg:{m.chat.id}:{m.message_id}"
        await queue_client.publish_task({
            "platform": "mirror",
            "action": "tg_to_amo",
            "lead_id": lead_id,
            "text": text,
            "tg_user_id": m.from_user.id,
            "tg_user_name": m.from_user.username,
            "conversation_id": conv_id,
            "bot_kind": bot_kind,
            "msg_key": msg_key,
        })

        # опрос
        if survey:
            survey = await svc.store_answer(m.from_user.id, bot_kind, text)
            if not survey:
                await _answer_and_mirror(m, "Сессия не найдена. Нажмите /start ещё раз.", bot_kind, lead_id, conv_id)
                return

            if survey.step <= 2:
                await _answer_and_mirror(m, survey_prompt(survey.step), bot_kind, lead_id, conv_id)
            else:
                summary = survey_summary(survey.city, survey.experience, survey.time_pref)
                await svc.finish(m.from_user.id, bot_kind, lead_id, summary)
                await _answer_and_mirror(
                    m,
                    "Спасибо! Мы передали информацию рекрутеру. С вами свяжутся.",
                    bot_kind, lead_id, conv_id
                )
                logger.info("[%s] survey finished user_id=%s lead_id=%s", bot_kind, m.from_user.id, lead_id)
        else:
            # обычный чат после опроса — зеркалирование уже отправили выше
            pass

    return dp
