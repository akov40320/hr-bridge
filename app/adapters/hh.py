import httpx
from typing import Optional

from app.core.config import get_settings
from app.api.oauth2 import ensure_fresh_access, OAuth2Config
from app.core.retry import with_retry
from ._requests import request_with_retry


class HHError(Exception):
    ...


async def set_employer_state(
    response_id: str,
    target_state: str,
    employer_id: Optional[str],
    client: httpx.AsyncClient,
) -> None:
    """Меняет статус отклика (response/negotiation) у конкретного работодателя."""
    s = get_settings()
    config = OAuth2Config(
        service="hh",
        token_url=s.HH_TOKEN_URL,
        client_id=s.HH_CLIENT_ID,
        client_secret=s.HH_CLIENT_SECRET,
        redirect_uri=s.HH_REDIRECT_URI,
        use_basic_auth=False,
        owner_id=employer_id,
    )
    access = await ensure_fresh_access(config=config, http_client=client)

    url = s.HH_API_BASE.rstrip("/") + s.HH_SET_STATE_PATH.format(response_id=response_id)
    payload = {"status": target_state}

    await request_with_retry(
        client,
        "POST",
        url,
        json=payload,
        headers={
            "Authorization": f"Bearer {access}",
            "Accept": "application/json",
        },
        timeout=30,
        error_cls=HHError,
        service="HH",
        action="set_state",
        retry_func=with_retry,
    )


async def send_message(
    response_id: str,
    text: str,
    employer_id: Optional[str],
    client: httpx.AsyncClient,
) -> None:
    s = get_settings()
    config = OAuth2Config(
        service="hh",
        token_url=s.HH_TOKEN_URL,
        client_id=s.HH_CLIENT_ID,
        client_secret=s.HH_CLIENT_SECRET,
        redirect_uri=s.HH_REDIRECT_URI,
        use_basic_auth=False,
        owner_id=employer_id,
    )
    access = await ensure_fresh_access(config=config, http_client=client)
    url = s.HH_API_BASE.rstrip("/") + f"/negotiations/{response_id}/messages"
    payload = {"message": {"text": text}}

    await request_with_retry(
        client,
        "POST",
        url,
        json=payload,
        headers={
            "Authorization": f"Bearer {access}",
            "Accept": "application/json",
        },
        timeout=30,
        error_cls=HHError,
        service="HH",
        action="send_message",
        retry_func=with_retry,
    )


async def fetch_applicant_details(
    response_id: str,
    employer_id: Optional[str],
    client: httpx.AsyncClient,
) -> dict:
    s = get_settings()
    config = OAuth2Config(
        service="hh",
        token_url=s.HH_TOKEN_URL,
        client_id=s.HH_CLIENT_ID,
        client_secret=s.HH_CLIENT_SECRET,
        redirect_uri=s.HH_REDIRECT_URI,
        use_basic_auth=False,
        owner_id=employer_id,
    )
    access = await ensure_fresh_access(config=config, http_client=client)

    h = {"Authorization": f"Bearer {access}", "Accept": "application/json"}
    base = s.HH_API_BASE.rstrip("/")

    # 1) negotiation -> resume id
    r1 = await client.get(f"{base}/negotiations/{response_id}", headers=h, timeout=30)
    if r1.status_code >= 400:
        return {}
    js1 = r1.json()
    resume_id = (js1.get("resume") or {}).get("id")
    if not resume_id:
        return {}

    # 2) resume -> phone, city, full name
    r2 = await client.get(f"{base}/resumes/{resume_id}", headers=h, timeout=30)
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
