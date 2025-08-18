import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.amochats import send_text
from app.bootstrap import ensure_tokens
from app.config import settings
from app.amo_client import AmoClient
from app.db import init_db
from app.store_chat import upsert_tg_link, get_by_user, set_conversation
from app.store_survey import (
    start_or_reset_survey,
    get_survey,
    store_answer_and_advance,
    delete_survey,
)


async def tag_and_note(lead_id: int, tags: list[str], note: str):
    amo = await AmoClient.create()
    if tags:
        await amo.add_tags(lead_id, tags)
    if note:
        await amo.add_note(lead_id, note)


def parse_start_arg(text: str) -> int | None:
    parts = (text or "").strip().split(maxsplit=1)
    if len(parts) == 2 and parts[0].startswith("/start"):
        try:
            return int(parts[1])
        except:
            return None
    return None


def survey_prompt(step: int) -> str:
    if step == 0:
        return "В каком вы городе?"
    if step == 1:
        return "Опишите кратко опыт по вакансии."
    if step == 2:
        return "Когда вам удобно на связи? (например, завтра после 14:00)"
    return "Спасибо, опрос завершён!"


def survey_summary(city: str | None, experience: str | None, time_pref: str | None) -> str:
    return (
        "Итоги опроса:\n"
        f"• Город: {city or '-'}\n"
        f"• Опыт: {experience or '-'}\n"
        f"• Связь: {time_pref or '-'}"
    )


def make_router(bot_kind: str):
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def on_start(m: Message):
        lead_id = parse_start_arg(m.text or "")
        if not lead_id:
            await m.answer("Нужно открыть бота по ссылке из сообщения, чтобы я увидел вашу заявку.")
            return

        # 1) связь TG↔Lead в БД
        await upsert_tg_link(m.from_user.id, bot_kind, lead_id)
        # 2) (пере)старт опроса
        await start_or_reset_survey(m.from_user.id, bot_kind, lead_id)

        # тег + заметка в Amo
        await tag_and_note(
            lead_id,
            [settings.AMO_TAG_WENT_TO_BOT],
            f"[{bot_kind}] Кандидат перешёл в бота (TG @{m.from_user.username or m.from_user.id}).",
        )
        await m.answer("Здравствуйте! Нужны пару уточнений по заявке.\n\n" + survey_prompt(0))

    @dp.message(F.text)
    async def on_text(m: Message):
        s = await get_survey(m.from_user.id, bot_kind)
        if not s:
            await m.answer("Нажмите /start по ссылке из сообщения, чтобы привязать диалог к заявке.")
            return

        # зеркало сообщения в таймлайн сделки
        try:
            amo = await AmoClient.create()
            await amo.add_note(s.lead_id, f"[TG->{bot_kind}] {m.text}")
            if settings.AMOCHATS_ENABLED:
                try:
                    # найдём существующую связку, чтобы хранить/обновлять conversation_id
                    link = await get_by_user(m.from_user.id, bot_kind)
                    conv_id = link.conversation_id if link else None
                    new_conv_id = await send_text(s.lead_id, m.text or "", conversation_id=conv_id)
                    if new_conv_id and link and new_conv_id != conv_id:
                        await set_conversation(link.user_id, bot_kind, new_conv_id)
                except Exception as e:
                    print("amochats send error:", e)
        except Exception as e:
            print("add_note error:", e)

        # сохранить ответ и сдвинуть шаг
        s = await store_answer_and_advance(m.from_user.id, bot_kind, m.text or "")
        if not s:
            await m.answer("Сессия не найдена. Нажмите /start ещё раз.")
            return

        if s.step <= 2:
            await m.answer(survey_prompt(s.step))
        else:
            # завершение
            summary = survey_summary(s.city, s.experience, s.time_pref)
            try:
                amo = await AmoClient.create()
                await amo.add_tags(s.lead_id, [settings.AMO_TAG_SURVEY_DONE])
                await amo.add_note(s.lead_id, f"[{bot_kind}] {summary}")
            except Exception as e:
                print("finish note/tag error:", e)
            await delete_survey(m.from_user.id, bot_kind)
            await m.answer("Спасибо! Мы передали информацию рекрутеру. С вами свяжутся.")

    return dp


async def main():
    await init_db()
    await ensure_tokens()

    master_bot = Bot(settings.TELEGRAM_MASTER_BOT_TOKEN)
    operator_bot = Bot(settings.TELEGRAM_OPERATOR_BOT_TOKEN)
    master_dp = make_router("master")
    operator_dp = make_router("operator")
    await asyncio.gather(
        master_dp.start_polling(master_bot),
        operator_dp.start_polling(operator_bot),
    )


if __name__ == "__main__":
    asyncio.run(main())
