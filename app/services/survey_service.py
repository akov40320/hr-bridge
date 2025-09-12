"""Сервисный слой для управления пользовательскими опросами.

Модуль предоставляет :class:`SurveyService`, который координирует запуск,
получение, обновление и завершение опросов через асинхронные вызовы и клиент
очереди. Функции оборачивают низкоуровневые помощники и публикуют сообщения в
другие сервисы при изменении состояния опроса.
"""

import logging

from app.core.config import get_settings
from app.services.queue import rabbitmq, RabbitMQClient
from app.store_survey import (
    start_or_reset_survey,
    get_survey,
    store_answer_and_advance,
    delete_survey,
)
from app.services.survey import mark_went_to_bot_async


logger = logging.getLogger(__name__)


class SurveyService:
    """Операции для управления жизненным циклом опроса."""

    def __init__(self, queue_client: RabbitMQClient = rabbitmq) -> None:
        """Инициализировать сервис клиентом очереди."""
        self.queue_client = queue_client

    async def start(self, user_id: int, bot_kind: str, lead_id: int, identity: str) -> None:
        """Запустить или сбросить опрос и отметить переход пользователя к боту."""
        await start_or_reset_survey(user_id, bot_kind, lead_id)
        await mark_went_to_bot_async(lead_id, bot_kind, identity, self.queue_client)

    async def get(self, user_id: int, bot_kind: str):
        """Получить текущее состояние опроса для пользователя и бота."""
        return await get_survey(user_id, bot_kind)

    async def store_answer(self, user_id: int, bot_kind: str, text: str):
        """Сохранить ответ и продвинуть опрос на следующий шаг."""
        return await store_answer_and_advance(user_id, bot_kind, text)

    async def finish(self, user_id: int, bot_kind: str, lead_id: int, summary: str) -> None:
        """Завершить опрос и отправить результаты в клиент очереди."""
        s = get_settings()
        try:
            await self.queue_client.publish_task(
                {
                    "platform": "amo",
                    "action": "amo_add_tags",
                    "lead_id": lead_id,
                    "tags": [s.AMO_TAG_SURVEY_DONE],
                }
            )
        except Exception:  # pylint: disable=broad-except
            logger.exception("ошибка публикации тегов lead_id=%s", lead_id)
            return

        try:
            await self.queue_client.publish_task(
                {
                    "platform": "amo",
                    "action": "amo_add_note",
                    "lead_id": lead_id,
                    "text": f"[{bot_kind}] {summary}",
                }
            )
        except Exception:  # pylint: disable=broad-except
            logger.exception("ошибка публикации заметки lead_id=%s", lead_id)
            return

        stage_id = (
            s.AMO_STAGE_ID_MASTER_SURVEY
            if bot_kind == "master"
            else s.AMO_STAGE_ID_OPERATOR_SURVEY
        )

        try:
            await self.queue_client.publish_task(
                {
                    "platform": "amo",
                    "action": "amo_update_status",
                    "lead_id": lead_id,
                    "status_id": stage_id,
                }
            )
        except Exception:  # pylint: disable=broad-except
            logger.exception("ошибка обновления статуса lead_id=%s", lead_id)
            return

        await delete_survey(user_id, bot_kind)
