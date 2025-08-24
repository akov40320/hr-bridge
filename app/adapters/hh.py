"""Utilities for interacting with the HeadHunter API."""

from typing import Optional

import httpx

from app.api.oauth2 import OAuth2Config, ensure_fresh_access
from app.core.config import get_settings
from app.core.retry import with_retry
from ._requests import request_with_retry


class HHError(Exception):
    """Base exception for HeadHunter related errors."""


async def set_employer_state(
    response_id: str,
    target_state: str,
    employer_id: Optional[str],
    client: httpx.AsyncClient,
) -> None:
    """Set the negotiation state for a given employer."""
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
    """Send a message to an applicant within a negotiation."""
    s = get_settings()
    access = await ensure_fresh_access(
        config=OAuth2Config(
            service="hh",
            token_url=s.HH_TOKEN_URL,
            client_id=s.HH_CLIENT_ID,
            client_secret=s.HH_CLIENT_SECRET,
            redirect_uri=s.HH_REDIRECT_URI,
            use_basic_auth=False,
            owner_id=employer_id,
        ),
        http_client=client,
    )
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
    """Fetch basic applicant information such as name, city, phone and email."""
    s = get_settings()
    access = await ensure_fresh_access(
        config=OAuth2Config(
            service="hh",
            token_url=s.HH_TOKEN_URL,
            client_id=s.HH_CLIENT_ID,
            client_secret=s.HH_CLIENT_SECRET,
            redirect_uri=s.HH_REDIRECT_URI,
            use_basic_auth=False,
            owner_id=employer_id,
        ),
        http_client=client,
    )

    headers = {"Authorization": f"Bearer {access}", "Accept": "application/json"}
    base_url = s.HH_API_BASE.rstrip("/")

    # 1) negotiation -> resume id
    negotiation = await client.get(
        f"{base_url}/negotiations/{response_id}", headers=headers, timeout=30
    )
    if negotiation.status_code >= 400:
        return {}
    resume_id = (negotiation.json().get("resume") or {}).get("id")
    if not resume_id:
        return {}

    # 2) resume -> phone, email, city, full name
    resume_resp = await client.get(
        f"{base_url}/resumes/{resume_id}?with_contacts=true",
        headers=headers,
        timeout=30,
    )
    if resume_resp.status_code >= 400:
        return {}

    data = resume_resp.json()
    city = (data.get("area") or {}).get("name")
    contact = data.get("contact") or []
    phone = None
    email = None
    for item in contact:
        kind = item.get("kind")
        if kind == "phone" and not phone:
            phone = item.get("contact_value")
            if not phone:
                value = item.get("value") or {}
                if isinstance(value, dict):
                    phone = value.get("formatted")
        elif kind == "email" and not email:
            email = item.get("contact_value") or item.get("value")

    name = " ".join(
        [(data.get("first_name") or "").strip(), (data.get("last_name") or "").strip()]
    ).strip() or data.get("title")

    return {"name": name, "city": city, "phone": phone, "email": email}



async def fetch_vacancy_description(
    vacancy_id: str,
    employer_id: Optional[str],
    client: httpx.AsyncClient,
) -> str:
    """Fetch vacancy description text."""
    from app.api.oauth2 import OAuth2Config

    s = get_settings()
    access = await ensure_fresh_access(
        config=OAuth2Config(
            service="hh",
            token_url=s.HH_TOKEN_URL,
            client_id=s.HH_CLIENT_ID,
            client_secret=s.HH_CLIENT_SECRET,
            redirect_uri=s.HH_REDIRECT_URI,
            use_basic_auth=False,
            owner_id=employer_id,
        ),
        http_client=client,
    )

    resp = await client.get(
        f"{s.HH_API_BASE.rstrip('/')}/vacancies/{vacancy_id}",
        headers={"Authorization": f"Bearer {access}", "Accept": "application/json"},
        timeout=30,
    )
    if resp.status_code >= 400:
        return ""
    return resp.json().get("description") or ""
