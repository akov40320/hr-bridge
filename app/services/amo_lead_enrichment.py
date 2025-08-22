import logging

from app.core.config import settings


logger = logging.getLogger(__name__)


async def enrich_lead(
    amo,
    lead_id: int,
    *,
    applicant_name: str | None,
    phone: str | None,
    city: str | None,
    vacancy_title: str | None,
) -> None:
    """Attach extra data to a newly created lead."""
    contact_id = None
    if applicant_name or phone:
        try:
            cr = await amo.create_contact(applicant_name or "Кандидат", phone)
            contact_id = cr["_embedded"]["contacts"][0]["id"]
            await amo.link_contact_to_lead(lead_id, contact_id)
        except Exception as e:  # pragma: no cover - log only
            logger.warning("create/link contact failed: %s", e)

    cf: dict[int, str] = {}
    if settings.AMO_CF_LEAD_CITY_ID:
        cf[settings.AMO_CF_LEAD_CITY_ID] = city or ""
    if settings.AMO_CF_LEAD_VACANCY_TITLE_ID:
        cf[settings.AMO_CF_LEAD_VACANCY_TITLE_ID] = vacancy_title or ""
    if settings.AMO_CF_LEAD_APPLICANT_PHONE_ID:
        cf[settings.AMO_CF_LEAD_APPLICANT_PHONE_ID] = phone or ""
    if settings.AMO_CF_LEAD_APPLICANT_NAME_ID:
        cf[settings.AMO_CF_LEAD_APPLICANT_NAME_ID] = applicant_name or ""
    try:
        await amo.update_lead_custom_fields(lead_id, cf)
    except Exception as e:  # pragma: no cover - log only
        logger.warning("update lead CF failed: %s", e)

    if not any(
        [
            settings.AMO_CF_LEAD_CITY_ID,
            settings.AMO_CF_LEAD_VACANCY_TITLE_ID,
            settings.AMO_CF_LEAD_APPLICANT_PHONE_ID,
            settings.AMO_CF_LEAD_APPLICANT_NAME_ID,
        ]
    ):
        try:
            note = (
                "Данные кандидата:\n"
                f"• Имя: {applicant_name or '-'}\n"
                f"• Телефон: {phone or '-'}\n"
                f"• Город: {city or '-'}\n"
                f"• Вакансия: {vacancy_title or '-'}"
            )
            await amo.add_note(lead_id, note)
        except Exception as e:  # pragma: no cover - log only
            logger.warning("add note (candidate data) error: %s", e)


__all__ = ["enrich_lead"]

