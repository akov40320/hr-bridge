from app.token_store import DbTokenStore, TokenData
from app.config import settings


async def ensure_tokens():
    # пара (service, ENV-префикс)
    pairs = [("amo", "AMO"), ("hh", "HH"), ("avito", "AVITO")]
    for service, prefix in pairs:
        store = DbTokenStore(service)
        # если уже есть в БД — ничего не делаем
        try:
            await store.load()
            continue
        except Exception:
            pass

        at = getattr(settings, f"{prefix}_ACCESS_TOKEN", None)
        rt = getattr(settings, f"{prefix}_REFRESH_TOKEN", None)
        ea = getattr(settings, f"{prefix}_EXPIRES_AT", None)
        if at and rt and ea:
            await store.save(TokenData(
                access_token=at,
                refresh_token=rt,
                expires_at=int(ea),
            ))
