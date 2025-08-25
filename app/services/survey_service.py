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
from app.services.survey import mark_went_to_bot_async


class SurveyService:
    """Operations for driving the survey lifecycle."""

    def __init__(self, queue_client: RabbitMQClient = rabbitmq) -> None:
        """Initialize the service with a queue client."""
        self.queue_client = queue_client

    async def start(self, user_id: int, bot_kind: str, lead_id: int, identity: str) -> None:
        """Start or reset survey and mark that user went to bot."""
        await start_or_reset_survey(user_id, bot_kind, lead_id)
        await mark_went_to_bot_async(lead_id, bot_kind, identity, self.queue_client)

    async def get(self, user_id: int, bot_kind: str):
        """Fetch the current survey state for the given user and bot."""
        return await get_survey(user_id, bot_kind)

    async def store_answer(self, user_id: int, bot_kind: str, text: str):
        """Persist an answer and advance the survey."""
        return await store_answer_and_advance(user_id, bot_kind, text)

    async def finish(self, user_id: int, bot_kind: str, lead_id: int, summary: str) -> None:
        """Finalize the survey and send results to the queue client."""
        s = get_settings()
        await self.queue_client.publish_task({
            "platform": "amo",
            "action": "amo_add_tags",
            "lead_id": lead_id,
            "tags": [s.AMO_TAG_SURVEY_DONE],
        })
        await self.queue_client.publish_task({
            "platform": "amo",
            "action": "amo_add_note",
            "lead_id": lead_id,
            "text": f"[{bot_kind}] {summary}",
        })
        stage_id = (
            s.AMO_STAGE_ID_MASTER_SURVEY
            if bot_kind == "master"
            else s.AMO_STAGE_ID_OPERATOR_SURVEY
        )
        await self.queue_client.publish_task(
            {
                "platform": "amo",
                "action": "amo_update_status",
                "lead_id": lead_id,
                "status_id": stage_id,
            }
        )
        await delete_survey(user_id, bot_kind)
