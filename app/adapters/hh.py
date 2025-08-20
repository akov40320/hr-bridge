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


async def fetch_applicant_details(response_id: str, employer_id: Optional[str]) -> dict:
    access = await ensure_fresh_access(
        service="hh",
        token_url=settings.HH_TOKEN_URL,
        client_id=settings.HH_CLIENT_ID,
        client_secret=settings.HH_CLIENT_SECRET,
        redirect_uri=settings.HH_REDIRECT_URI,
        use_basic_auth=False,
        owner_id=employer_id,
    )

    h = {"Authorization": f"Bearer {access}", "Accept": "application/json"}
    base = settings.HH_API_BASE.rstrip("/")

    async with httpx.AsyncClient(timeout=30) as x:
        # 1) negotiation -> resume id
        r1 = await x.get(f"{base}/negotiations/{response_id}", headers=h)
        if r1.status_code >= 400:
            return {}
        js1 = r1.json()
        resume_id = (js1.get("resume") or {}).get("id")
        if not resume_id:
            return {}

        # 2) resume -> phone, city, full name
        r2 = await x.get(f"{base}/resumes/{resume_id}", headers=h)
        if r2.status_code >= 400:
            return {}

        j = r2.json()
        city = ((j.get("area") or {}).get("name")) or None
        # В разных схемах контакт может отличаться, разбираем безопасно:
        phone = None
        contact = j.get("contact") or {}
        phones = contact.get("phones") or contact.get("phone") or []
        if isinstance(phones, list) and phones:
            phone = (phones[0].get("formatted") or phones[0].get("value") or None)
        elif isinstance(phones, dict):
            phone = phones.get("formatted") or phones.get("value") or None

        name = " ".join([
            (j.get("first_name") or "").strip(),
            (j.get("last_name") or "").strip()
        ]).strip() or (j.get("title") or None)

        return {"name": name, "city": city, "phone": phone}