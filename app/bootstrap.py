import os
from app.token_store import DbTokenStore, TokenData


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

        at = os.getenv(f"{prefix}_ACCESS_TOKEN")
        rt = os.getenv(f"{prefix}_REFRESH_TOKEN")
        ea = os.getenv(f"{prefix}_EXPIRES_AT")
        if at and rt and ea:
            await store.save(TokenData(
                access_token=at,
                refresh_token=rt,
                expires_at=int(ea),
            ))
