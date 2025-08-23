"""Worker handlers for the HeadHunter (hh.ru) service.

The module provides functions that proxy worker payloads to the ``hh`` adapter.
Each handler expects a payload dictionary produced by message broker tasks and
forwards it to the appropriate adapter function using a shared HTTP client.
"""

import logging

from app.adapters import hh as hh_adapt
from app.http_client import get_http_client

logger = logging.getLogger(__name__)


async def handle_hh_send_message(payload: dict):
    """Send a message via the hh adapter.

    The ``payload`` must contain ``external_id`` and ``text`` keys. Optionally,
    the ``owner_id`` key can be provided to target a specific employer.
    """

    logger.info("hh.send_message: %s", payload.get("external_id"))
    client = get_http_client()
    await hh_adapt.send_message(
        payload["external_id"],
        payload["text"],
        employer_id=payload.get("owner_id"),
        client=client,
    )


async def handle_hh_set_state(payload: dict):
    """Update an employer's state in hh.ru.

    The ``payload`` must contain ``external_id`` and ``target_state`` keys. The
    optional ``owner_id`` key is used to specify the employer account context.
    """

    logger.info(
        "hh.set_state: %s -> %s",
        payload.get("external_id"),
        payload.get("target_state"),
    )
    client = get_http_client()
    await hh_adapt.set_employer_state(
        payload["external_id"],
        payload["target_state"],
        employer_id=payload.get("owner_id"),
        client=client,
    )
