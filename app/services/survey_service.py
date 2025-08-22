from app.core.config import settings
from app.services.queue import publish_task
from app.store_survey import (
    start_or_reset_survey,
    get_survey,
    store_answer_and_advance,
    delete_survey,
)
from app.services.survey import mark_went_to_bot_async


class SurveyService:
    async def start(self, user_id: int, bot_kind: str, lead_id: int, identity: str) -> None:
        """Start or reset survey and mark that user went to bot."""
        await start_or_reset_survey(user_id, bot_kind, lead_id)
        await mark_went_to_bot_async(lead_id, bot_kind, identity)

    async def get(self, user_id: int, bot_kind: str):
        return await get_survey(user_id, bot_kind)

    async def store_answer(self, user_id: int, bot_kind: str, text: str):
        return await store_answer_and_advance(user_id, bot_kind, text)

    async def finish(self, user_id: int, bot_kind: str, lead_id: int, summary: str) -> None:
        await publish_task({
            "platform": "amo",
            "action": "amo_add_tags",
            "lead_id": lead_id,
            "tags": [settings.AMO_TAG_SURVEY_DONE],
        })
        await publish_task({
            "platform": "amo",
            "action": "amo_add_note",
            "lead_id": lead_id,
            "text": f"[{bot_kind}] {summary}",
        })
        await delete_survey(user_id, bot_kind)
