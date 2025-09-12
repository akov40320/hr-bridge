"""Telegram bot router for mirroring messages and collecting survey responses."""

import logging

from aiogram import Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message

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
    """Create a dispatcher with handlers for Telegram survey bots."""
    # pylint: disable=too-many-statements
    dp = Dispatcher()
    svc = SurveyService(queue_client)

    async def mirror_prompt_to_amo(
        m: Message, text: str, lead_id: int, conv_id: str | None, key: str
    ) -> None:
        """Mirror bot's prompt to the CRM queue."""
        user = m.from_user
        if user is None:
            return
        msg_key = f"bot_to_amo:{lead_id}:{m.message_id}:{key}"
        await queue_client.publish_task(
            {
                "platform": "mirror",
                "action": "bot_to_amo",
                "text": text,
                "user_id": user.id,
                "user_name": user.username,
                "conversation_id": conv_id,
                "lead_id": lead_id,
                "bot_kind": bot_kind,
                "msg_key": msg_key,
            }
        )

    @dp.message(CommandStart())
    async def on_start(m: Message) -> None:
        """Handle /start command to register user and start survey."""
        user = m.from_user
        if user is None:
            return
        lead_id = parse_start_arg(m.text or "")
        if not lead_id:
            await m.answer(
                "Нужно открыть бота по ссылке из сообщения, "
                "чтобы я увидел вашу заявку."
            )
            return

        await upsert_tg_link(user.id, bot_kind, lead_id)
        await svc.start(user.id, bot_kind, lead_id, pretty_tg_identity(m))

        greeting = "Здравствуйте! Нужны пару уточнений по заявке..."
        await m.answer(greeting)
        await mirror_prompt_to_amo(m, greeting, lead_id, conv_id=None, key="greet")

        first = survey_prompt(0)
        await m.answer(first)
        await mirror_prompt_to_amo(m, first, lead_id, conv_id=None, key="step0")

        logger.info(
            "[%s] /start user_id=%s lead_id=%s",
            bot_kind,
            user.id,
            lead_id,
        )

    @dp.message(F.text)
    async def on_text(m: Message) -> None:
        """Process text messages, mirror to CRM, and advance survey."""
        user = m.from_user
        if user is None:
            return
        text = m.text or ""
        survey = await svc.get(user.id, bot_kind)

        lead_id: int | None = None
        conv_id: str | None = None
        if survey:
            lead_id = survey.lead_id
        else:
            link = await get_by_user(user.id, bot_kind)
            if link:
                lead_id = link.lead_id
                conv_id = link.conversation_id

        if not lead_id:
            await m.answer(
                "Нажмите /start по ссылке из сообщения, "
                "чтобы привязать диалог к заявке."
            )
            return

        msg_key = f"tg:{m.chat.id}:{m.message_id}"
        await queue_client.publish_task(
            {
                "platform": "mirror",
                "action": "tg_to_amo",
                "lead_id": lead_id,
                "text": text,
                "tg_user_id": user.id,
                "tg_user_name": user.username,
                "conversation_id": conv_id,
                "bot_kind": bot_kind,
                "msg_key": msg_key,
            }
        )

        if survey:
            survey = await svc.store_answer(user.id, bot_kind, text)
            if not survey:
                text_out = "Сессия не найдена. Нажмите /start ещё раз."
                await m.answer(text_out)
                await mirror_prompt_to_amo(
                    m, text_out, lead_id, conv_id, key="error"
                )
                return

            if survey.step <= 2:
                prompt = survey_prompt(survey.step)
                await m.answer(prompt)
                await mirror_prompt_to_amo(
                    m, prompt, lead_id, conv_id, key=f"step{survey.step}"
                )
            else:
                summary = survey_summary(
                    survey.city, survey.experience, survey.time_pref
                )
                await svc.finish(user.id, bot_kind, lead_id, summary)
                final = (
                    "Спасибо! Мы передали информацию рекрутеру. "
                    "С вами свяжутся."
                )
                await m.answer(final)
                await mirror_prompt_to_amo(
                    m, final, lead_id, conv_id, key="finish"
                )
                logger.info(
                    "[%s] survey finished user_id=%s lead_id=%s",
                    bot_kind,
                    user.id,
                    lead_id,
                )

    return dp
