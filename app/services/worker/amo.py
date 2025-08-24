"""Helpers for processing tasks related to amoCRM.

The functions defined here are small asynchronous handlers that are used by the
worker service.  Each handler delegates to :class:`app.adapters.amo_client.AmoClient`
to perform the actual API call.
"""

import logging

from httpx import HTTPStatusError

from app.adapters.amo_client import AmoClient
from app.http_client import get_http_client

logger = logging.getLogger(__name__)


async def handle_amo_create_lead(payload: dict) -> None:
    """Create a lead in amoCRM.

    Args:
        payload: Mapping with a ``lead_body`` key describing the lead to create.
    """

    logger.info("amo.create_lead")
    amo = await AmoClient.create(get_http_client())
    await amo.create_leads(payload["lead_body"])


async def handle_amo_add_note(payload: dict) -> None:
    """Attach a note to a lead in amoCRM.

    Args:
        payload: Must contain ``lead_id`` and ``text`` for the note contents.
    """

    logger.info("amo.add_note: %s", payload.get("lead_id"))
    amo = await AmoClient.create(get_http_client())
    try:
        await amo.add_note(int(payload["lead_id"]), payload["text"])
    except HTTPStatusError as err:  # pylint: disable=broad-except
        if err.response is not None and err.response.status_code < 500:
            logger.warning("amo.add_note failed: %s", err)
        else:
            raise


async def handle_amo_add_tags(payload: dict) -> None:
    """Add tags to a lead in amoCRM.

    Args:
        payload: Must contain ``lead_id`` and may include a list of ``tags``.
    """

    logger.info("amo.add_tags: %s", payload.get("lead_id"))
    amo = await AmoClient.create(get_http_client())
    try:
        await amo.add_tags(int(payload["lead_id"]), list(payload.get("tags") or []))
    except HTTPStatusError as err:  # pylint: disable=broad-except
        if err.response is not None and err.response.status_code < 500:
            logger.warning("amo.add_tags failed: %s", err)
        else:
            raise
