"""Workers handling Avito specific tasks.

This module provides async handlers used by the background worker to interact
with the Avito API.  The functions are small wrappers around the underlying
adapter calls.  They are intentionally similar to the respective HH handlers in
order to keep the behaviour consistent across job boards.
"""

# pylint: disable=duplicate-code

import logging

from app.adapters import avito as avito_adapt
from app.services.common_request import perform_request

logger = logging.getLogger(__name__)


async def handle_avito_send_message(payload: dict) -> None:
    """Send a message to a candidate via Avito.

    Args:
        payload: Mapping that must contain the external message ID and text. It
            may optionally include an ``owner_id`` specifying the account.
    """

    logger.info("avito.send_message: %s", payload.get("external_id"))
    await perform_request(
        avito_adapt.send_message,
        payload["external_id"],
        payload["text"],
        owner_id=payload.get("owner_id"),
    )


async def handle_avito_mark_read(payload: dict) -> None:
    """Mark a conversation as read on Avito.

    Args:
        payload: Mapping that must contain the external message ID and may
            include an ``owner_id`` specifying the account.
    """

    logger.info("avito.mark_read: %s", payload.get("external_id"))
    await perform_request(
        avito_adapt.mark_read,
        payload["external_id"],
        owner_id=payload.get("owner_id"),
    )
