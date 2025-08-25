"""Helpers for enriching AmoCRM leads with applicant data."""

import logging

from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def enrich_lead(  # pylint: disable=too-many-arguments
    amo,
    lead_id: int,
    *,
    applicant_name: str | None,
    phone: str | None,
    city: str | None,
    vacancy_title: str | None,
    email: str | None,
) -> int | None:
    """Attach extra data to a newly created lead.

    Returns the ID of the created contact if a contact was created.
    """
    s = get_settings()

    contact_id = None
    if applicant_name or phone or email:
        try:
            cr = await amo.create_contact(applicant_name or "Кандидат", phone, email)
            contact_id = cr["_embedded"]["contacts"][0]["id"]
        except Exception as e:  # pragma: no cover - log only  # pylint: disable=broad-exception-caught
            logger.warning("create contact failed: %s", e)

    cf: dict[int, str] = {}
    if s.AMO_CF_LEAD_CITY_ID:
        cf[s.AMO_CF_LEAD_CITY_ID] = city or ""
    if s.AMO_CF_LEAD_VACANCY_TITLE_ID:
        cf[s.AMO_CF_LEAD_VACANCY_TITLE_ID] = vacancy_title or ""
    if s.AMO_CF_LEAD_APPLICANT_PHONE_ID:
        cf[s.AMO_CF_LEAD_APPLICANT_PHONE_ID] = phone or ""
    if s.AMO_CF_LEAD_APPLICANT_NAME_ID:
        cf[s.AMO_CF_LEAD_APPLICANT_NAME_ID] = applicant_name or ""
    if getattr(s, "AMO_CF_LEAD_APPLICANT_EMAIL_ID", 0):
        cf[s.AMO_CF_LEAD_APPLICANT_EMAIL_ID] = email or ""
    try:
        await amo.update_lead_custom_fields(lead_id, cf)
    except Exception as e:  # pragma: no cover - log only  # pylint: disable=broad-exception-caught
        logger.warning("update lead CF failed: %s", e)

    if not any(
        [
            s.AMO_CF_LEAD_CITY_ID,
            s.AMO_CF_LEAD_VACANCY_TITLE_ID,
            s.AMO_CF_LEAD_APPLICANT_PHONE_ID,
            s.AMO_CF_LEAD_APPLICANT_NAME_ID,
            getattr(s, "AMO_CF_LEAD_APPLICANT_EMAIL_ID", 0),
        ]
    ):
        try:
            note = (
                "Данные кандидата:\n"
                f"• Имя: {applicant_name or '-'}\n"
                f"• Телефон: {phone or '-'}\n"
                f"• Город: {city or '-'}\n"
                f"• Вакансия: {vacancy_title or '-'}\n"
                f"• Email: {email or '-'}"
            )
            await amo.add_note(lead_id, note)
        except Exception as e:  # pragma: no cover - log only  # pylint: disable=broad-exception-caught
            logger.warning("add note (candidate data) error: %s", e)
    return contact_id


__all__ = ["enrich_lead"]
