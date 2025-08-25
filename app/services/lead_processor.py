"""Сервисные утилиты для обработки лидов и кандидатов."""

import json
import logging
import time

import httpx

from app.adapters import hh as hh_adapt, amochats
from app.adapters.amo_client import ReauthRequired
from app.core.config import get_settings
from app.services.queue import rabbitmq, RabbitMQClient
from app.store import save_link
from app import store_chat
from app.api.utils import route_kind
from app.services import amo_lead_enrichment
from app.models import IncomingPayload
from app.http_client import get_http_client

logger = logging.getLogger(__name__)


async def enrich_applicant(
        payload: IncomingPayload, http_client: httpx.AsyncClient
) -> IncomingPayload:
    """Обогатить данные кандидата из HH, если возможно."""
    if payload.platform == "hh" and payload.applicant.id:
        owner_id = payload.owner_id
        try:
            extra = await hh_adapt.fetch_applicant_details(
                payload.applicant.id, owner_id, http_client
            )
            if extra:
                payload.applicant.phone = payload.applicant.phone or extra.get("phone")
                payload.applicant.city = payload.applicant.city or extra.get("city")
                payload.applicant.email = payload.applicant.email or extra.get("email")
                payload.applicant.name = (
                    payload.applicant.name
                    if payload.applicant.name and payload.applicant.name != "кандидат"
                    else extra.get("name") or payload.applicant.name
                )
        except (httpx.HTTPError, json.JSONDecodeError) as e:  # pragma: no cover
            logger.warning("HH: обогащение кандидата %s не удалось: %s", payload.applicant.id, type(e).__name__)
        if payload.vacancy_id and not (payload.vacancy_desc or "").strip():
            try:
                desc = await hh_adapt.fetch_vacancy_description(
                    payload.vacancy_id, owner_id, http_client
                )
                if desc:
                    payload.vacancy_desc = desc
            except (httpx.HTTPError, json.JSONDecodeError) as e:  # pragma: no cover
                logger.warning("HH: описание вакансии %s не получено: %s", payload.vacancy_id, type(e).__name__)
    return payload


async def create_lead(
        payload: IncomingPayload,
        client,
        queue_client: RabbitMQClient = rabbitmq,
) -> tuple[int | None, str]:
    """Создать лид в AmoCRM и вернуть (lead_id, kind)."""
    s = get_settings()

    kind = route_kind(
        desc=(payload.vacancy_desc or ""),
        raw=" ".join([payload.raw_text or "", payload.vacancy_title or ""]).strip(),
    )
    payload.kind = kind

    if kind == "ignore":
        logger.info(
            "маршрутизация: ignore (нет хэштегов) title=%r desc_len=%d raw_len=%d",
            payload.vacancy_title or "",
            len(payload.vacancy_desc or ""),
            len(payload.raw_text or ""),
        )
        return None, kind

    if kind == "master":
        pipeline_id = s.AMO_PIPELINE_ID_MASTER
        stage_id = s.AMO_STAGE_ID_MASTER_NEW
    else:
        pipeline_id = s.AMO_PIPELINE_ID_OPERATOR
        stage_id = s.AMO_STAGE_ID_OPERATOR_NEW

    lead_name = (f"{payload.vacancy_title or ''} — {payload.applicant.name or 'кандидат'}").strip(" —")

    logger.info(
        "lead:create platform=%s -> name=%s pipeline=%s stage=%s",
        payload.platform,
        lead_name,
        pipeline_id,
        stage_id,
    )

    body = [{"name": lead_name, "pipeline_id": pipeline_id, "status_id": stage_id}]
    try:
        created = await client.create_leads(body)
    except ReauthRequired:
        await queue_client.publish_task(
            {
                "platform": payload.platform or "unknown",
                "action": "amo_create_lead",
                "lead_body": body,
                "ts": int(time.time()),
            }
        )
        return None, kind

    lead_id = created["_embedded"]["leads"][0]["id"]

    contact_id = await amo_lead_enrichment.enrich_lead(
        client,
        lead_id,
        applicant_name=payload.applicant.name,
        phone=payload.applicant.phone,
        city=payload.applicant.city,
        vacancy_title=payload.vacancy_title,
        email=payload.applicant.email,
    )

    if not contact_id:
        try:
            cr = await client.create_contact(payload.applicant.name or "Кандидат", None, None)
            contact_id = cr["_embedded"]["contacts"][0]["id"]
        except Exception as e:  # pragma: no cover
            logger.warning("force create contact failed: %s", e)

    tg_user_id = getattr(payload, "tg_user_id", None)
    if tg_user_id:
        tg_user_name = getattr(payload, "tg_user_name", None)
        result = await amochats.ensure_chat_created(
            lead_id=lead_id,
            tg_user_id=int(tg_user_id),
            tg_user_name=tg_user_name,
            contact_id=contact_id,
            client=get_http_client(),
        )
        if isinstance(result, tuple):
            conv_id, amo_uuid = result
        else:
            conv_id, amo_uuid = result, None
        await store_chat.upsert_tg_link(user_id=int(tg_user_id), bot_kind=kind, lead_id=lead_id)
        if conv_id:
            await store_chat.set_conversation(int(tg_user_id), kind, conv_id)

        # 4) Привязать чат к контакту
        if contact_id and amo_uuid:
            try:
                await client.attach_chat_to_contact(int(contact_id), amo_uuid)
            except Exception as e:  # pragma: no cover
                logger.warning("attach chat to contact failed: %s", e)
    if contact_id:
        try:
            await client.link_contact_to_lead(lead_id, contact_id)
        except Exception as e:  # pragma: no cover
            logger.warning("link contact to lead failed: %s", e)

    await save_link(
        lead_id=lead_id,
        platform=payload.platform or "unknown",
        owner_id=payload.owner_id,
        vacancy_id=str(payload.vacancy_id or ""),
        external_id=str(payload.applicant.id or "") or None,
    )

    return lead_id, kind


async def send_invite(
        payload: IncomingPayload, lead_id: int, queue_client: RabbitMQClient = rabbitmq
) -> str:
    """Отправить приглашение кандидату (правильные действия для HH/Avito)."""
    s = get_settings()

    kind = payload.kind or route_kind(
        desc=payload.vacancy_desc or "",
        raw=" ".join([payload.raw_text or "", payload.vacancy_title or ""]).strip(),
    )
    bot_username = s.TELEGRAM_MASTER_BOT_USERNAME if kind == "master" else s.TELEGRAM_OPERATOR_BOT_USERNAME

    deep_link = f"https://t.me/{bot_username}?start={lead_id}"

    invite_text_avito = (
        "Здравствуйте! Перейдите, пожалуйста, в Telegram-бот и пройдите короткий опрос: "
        f"{deep_link}"
    )
    # HH — без «голой» ссылки
    invite_text_hh = (
        f"Здравствуйте! Откройте Telegram, найдите @{bot_username} "
        f"и отправьте команду: /start {lead_id}"
    )

    platform = payload.platform
    # В нашем пайлоаде applicant.id для HH = negotiation_id (nid)
    negotiation_id = payload.applicant.id

    if platform == "avito" and negotiation_id:
        await queue_client.publish_task({
            "platform": "avito",
            "action": "send_message",
            "external_id": negotiation_id,
            "text": invite_text_avito,
            "owner_id": payload.owner_id,
        })

    if platform == "hh" and negotiation_id:
        # 1) Перевод в этап «Первичный контакт» через action
        await queue_client.publish_task({
            "platform": "hh",
            "action": "set_state",
            "negotiation_id": negotiation_id,
            "action_id": "phone_interview",  # PUT /negotiations/phone_interview/{nid}
            "owner_id": payload.owner_id,
        })
        # 2) Сообщение кандидату (form-urlencoded, HH-User-Agent на стороне воркера)
        await queue_client.publish_task({
            "platform": "hh",
            "action": "send_message",
            "negotiation_id": negotiation_id,
            "text": invite_text_hh,
            "owner_id": payload.owner_id,
        })

    return deep_link


async def tag_lead(lead_id: int, kind: str, amo_client) -> None:
    """Присвоить теги лиду."""
    await amo_client.add_tags(
        lead_id,
        [f"type:{'мастер' if kind == 'master' else 'оператор'}"],
    )


__all__ = ["enrich_applicant", "create_lead", "send_invite", "tag_lead"]
