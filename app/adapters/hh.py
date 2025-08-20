import asyncio, httpx
from typing import Optional
from app.config import settings
from app.oauth2 import ensure_fresh_access


class HHError(Exception): ...


def _is_retryable(status: int) -> bool:
    return status == 429 or 500 <= status < 600


async def set_employer_state(response_id: str, target_state: str, employer_id: Optional[str]) -> None:
    """
    Меняет статус отклика (response/negotiation) у конкретного работодателя.
    """
    access = await ensure_fresh_access(
        service="hh",
        token_url=settings.HH_TOKEN_URL,
        client_id=settings.HH_CLIENT_ID,
        client_secret=settings.HH_CLIENT_SECRET,
        redirect_uri=settings.HH_REDIRECT_URI,
        use_basic_auth=False,
        owner_id=employer_id,
    )

    url = settings.HH_API_BASE.rstrip("/") + settings.HH_SET_STATE_PATH.format(response_id=response_id)
    payload = {"status": target_state}

    backoff = 0.5
    for _ in range(5):
        async with httpx.AsyncClient(timeout=30) as x:
            r = await x.post(url, json=payload, headers={
                "Authorization": f"Bearer {access}",
                "Accept": "application/json",
            })
        if r.status_code < 400:
            return
        if _is_retryable(r.status_code):
            await asyncio.sleep(backoff)
            backoff *= 2
            continue
        raise HHError(f"HH set_state failed {r.status_code}: {r.text}")

    raise HHError(f"HH set_state retry exhausted for {response_id}->{target_state}")


async def send_message(response_id: str, text: str, employer_id: Optional[str]) -> None:
    access = await ensure_fresh_access(
        service="hh",
        token_url=settings.HH_TOKEN_URL,
        client_id=settings.HH_CLIENT_ID,
        client_secret=settings.HH_CLIENT_SECRET,
        redirect_uri=settings.HH_REDIRECT_URI,
        use_basic_auth=False,
        owner_id=employer_id,
    )
    url = settings.HH_API_BASE.rstrip("/") + f"/negotiations/{response_id}/messages"
    payload = {"message": {"text": text}}

    backoff = 0.5
    for _ in range(5):
        async with httpx.AsyncClient(timeout=30) as x:
            r = await x.post(url, json=payload, headers={
                "Authorization": f"Bearer {access}",
                "Accept": "application/json",
            })
        if r.status_code < 400:
            return
        if _is_retryable(r.status_code):
            await asyncio.sleep(backoff); backoff *= 2; continue
        raise HHError(f"HH send_message failed {r.status_code}: {r.text}")
    raise HHError(f"HH send_message retry exhausted for {response_id}")