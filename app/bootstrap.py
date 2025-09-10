"""Utilities for seeding persistent storage during application start-up.

This module provides helpers used when the application boots to ensure that
authentication tokens required by integrations are available. If tokens are
missing from the database but provided via environment variables, they are
persisted so that subsequent components can access them.
"""

import logging

from app.db.token_store import DbTokenStore, TokenData
from app.core.config import get_settings


log = logging.getLogger(__name__)

settings = get_settings()


async def ensure_tokens() -> None:
    """Populate the token store from environment variables when necessary.

    For each supported service, this function checks whether a token is
    already persisted. If not, it attempts to load credentials from the
    corresponding environment variables and saves them to the database.
    """
    # пара (service, ENV-префикс)
    pairs = [("amo", "AMO"), ("hh", "HH"), ("avito", "AVITO")]
    for service, prefix in pairs:
        store = DbTokenStore(service)
        # если уже есть в БД — ничего не делаем
        try:
            await store.load()
            continue
        except RuntimeError:
            # токен отсутствует, попробуем загрузить из ENV
            pass
        except Exception:  # pragma: no cover - log only
            log.exception("Failed to load token for service %s", service)
            raise

        at_field = getattr(settings, f"{prefix}_ACCESS_TOKEN", None)
        rt_field = getattr(settings, f"{prefix}_REFRESH_TOKEN", None)
        ea = getattr(settings, f"{prefix}_EXPIRES_AT", None)
        at = at_field.get_secret_value() if at_field else ""
        rt = rt_field.get_secret_value() if rt_field else ""
        if at and rt and ea:
            await store.save(TokenData(
                access_token=at,
                refresh_token=rt,
                expires_at=int(ea),
            ))
