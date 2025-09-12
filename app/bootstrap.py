"""Утилиты для инициализации постоянного хранилища при запуске приложения.

Модуль содержит помощники, которые при старте приложения проверяют наличие
требуемых для интеграций токенов. Если в базе токены отсутствуют, но заданы
в переменных окружения, они сохраняются для последующего использования.
"""

import logging

from app.db.token_store import DbTokenStore, TokenData
from app.core.config import get_settings


log = logging.getLogger(__name__)

settings = get_settings()


async def ensure_tokens() -> None:
    """Заполнить хранилище токенов из переменных окружения при необходимости.

    Для каждого поддерживаемого сервиса проверяется наличие сохранённых
    токенов. Если их нет, берутся значения из переменных окружения и
    сохраняются в базу данных.
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
            log.exception("Не удалось загрузить токен для сервиса %s", service)
            raise

        at = getattr(settings, f"{prefix}_ACCESS_TOKEN", None)
        rt = getattr(settings, f"{prefix}_REFRESH_TOKEN", None)
        ea = getattr(settings, f"{prefix}_EXPIRES_AT", None)
        if at and rt and ea:
            await store.save(TokenData(
                access_token=at,
                refresh_token=rt,
                expires_at=int(ea),
            ))
