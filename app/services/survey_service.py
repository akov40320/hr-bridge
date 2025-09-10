"""Service layer for managing user surveys.

This module provides the :class:`SurveyService` which coordinates starting,
retrieving, updating and finishing surveys through asynchronous calls and a
queue client.  The functions wrap lower level helpers and publish messages to
other services when the survey state changes.
"""

from app.core.config import get_settings
from app.services.queue import rabbitmq, RabbitMQClient
from app.store_survey import (
    start_or_reset_survey,
    get_survey,
    store_answer_and_advance,
    delete_survey,
)


async def _publish_tasks(queue_client: RabbitMQClient, tasks: list[dict]) -> None:
    """Publish a sequence of tasks to the queue client."""

    for payload in tasks:
        await queue_client.publish_task(payload)


class SurveyService:
    """Operations for driving the survey lifecycle."""

    def __init__(self, queue_client: RabbitMQClient = rabbitmq) -> None:
        """Initialize the service with a queue client."""
        self.queue_client = queue_client

    async def start(self, user_id: int, bot_kind: str, lead_id: int, identity: str) -> None:
        """Start or reset survey and mark that user went to bot."""
        await start_or_reset_survey(user_id, bot_kind, lead_id)
        s = get_settings()
        stage_id = (
            s.AMO_STAGE_ID_MASTER_NEW
            if bot_kind == "master"
            else s.AMO_STAGE_ID_OPERATOR_NEW
        )
        await _publish_tasks(
            self.queue_client,
            [
                {
                    "platform": "amo",
                    "action": "amo_add_note",
                    "lead_id": lead_id,
                    "text": f"[{bot_kind}] Кандидат перешёл в бота (TG {identity}).",
                },
                {
                    "platform": "amo",
                    "action": "amo_add_tags",
                    "lead_id": lead_id,
                    "tags": [s.AMO_TAG_WENT_TO_BOT],
                },
                {
                    "platform": "amo",
                    "action": "amo_update_status",
                    "lead_id": lead_id,
                    "status_id": stage_id,
                },
            ],
        )

    async def get(self, user_id: int, bot_kind: str):
        """Fetch the current survey state for the given user and bot."""
        return await get_survey(user_id, bot_kind)

    async def store_answer(self, user_id: int, bot_kind: str, text: str):
        """Persist an answer and advance the survey."""
        return await store_answer_and_advance(user_id, bot_kind, text)

    async def finish(self, user_id: int, bot_kind: str, lead_id: int, summary: str) -> None:
        """Finalize the survey and send results to the queue client."""
        s = get_settings()
        stage_id = (
            s.AMO_STAGE_ID_MASTER_SURVEY
            if bot_kind == "master"
            else s.AMO_STAGE_ID_OPERATOR_SURVEY
        )
        await _publish_tasks(
            self.queue_client,
            [
                {
                    "platform": "amo",
                    "action": "amo_add_tags",
                    "lead_id": lead_id,
                    "tags": [s.AMO_TAG_SURVEY_DONE],
                },
                {
                    "platform": "amo",
                    "action": "amo_add_note",
                    "lead_id": lead_id,
                    "text": f"[{bot_kind}] {summary}",
                },
                {
                    "platform": "amo",
                    "action": "amo_update_status",
                    "lead_id": lead_id,
                    "status_id": stage_id,
                },
            ],
        )
        await delete_survey(user_id, bot_kind)
