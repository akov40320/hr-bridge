import asyncio
from dataclasses import dataclass
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.bootstrap import ensure_tokens
from app.config import settings
from app.amo_client import AmoClient
from app.db import init_db


# Простая сессия опроса в памяти (MVP). Можно потом вынести в таблицу.
@dataclass
class SurveyState:
    lead_id: int
    step: int = 0
    city: str | None = None
    experience: str | None = None
    time_pref: str | None = None


# user_id -> SurveyState
SURVEYS: dict[int, SurveyState] = {}


async def tag_and_note(lead_id: int, tags: list[str], note: str):
    amo = await AmoClient.create()
    if tags:
        await amo.add_tags(lead_id, tags)
    if note:
        await amo.add_note(lead_id, note)


def parse_start_arg(text: str) -> int | None:
    # /start 123456
    parts = text.strip().split(maxsplit=1)
    if len(parts) == 2 and parts[0].startswith("/start"):
        try:
            return int(parts[1])
        except:
            return None
    return None


def survey_prompt(state: SurveyState) -> str:
    if state.step == 0:
        return "В каком вы городе?"
    if state.step == 1:
        return "Опишите кратко опыт по вакансии."
    if state.step == 2:
        return "Когда вам удобно на связи? (например, завтра после 14:00)"
    return "Спасибо, опрос завершён!"


def survey_store_answer(state: SurveyState, text: str):
    if state.step == 0:
        state.city = text
    elif state.step == 1:
        state.experience = text
    elif state.step == 2:
        state.time_pref = text
    state.step += 1


def survey_summary(state: SurveyState) -> str:
    return (
        "Итоги опроса:\n"
        f"• Город: {state.city or '-'}\n"
        f"• Опыт: {state.experience or '-'}\n"
        f"• Связь: {state.time_pref or '-'}"
    )


def make_router(bot_kind: str):
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def on_start(m: Message):
        lead_id = parse_start_arg(m.text or "")
        if not lead_id:
            await m.answer("Нужно открыть бота по ссылке из сообщения, чтобы я увидел вашу заявку.")
            return

        SURVEYS[m.from_user.id] = SurveyState(lead_id=lead_id, step=0)

        # тег + заметка
        await tag_and_note(lead_id, [settings.AMO_TAG_WENT_TO_BOT],
                           f"[{bot_kind}] Кандидат перешёл в бота (TG @{m.from_user.username or m.from_user.id}).")

        await m.answer(
            "Здравствуйте! Нужны пару уточнений по заявке. "
            "Отвечайте, пожалуйста, коротко.\n\n" + survey_prompt(SURVEYS[m.from_user.id])
        )

    @dp.message(F.text)
    async def on_text(m: Message):
        st = SURVEYS.get(m.from_user.id)
        if not st:
            await m.answer("Нажмите /start по ссылке из сообщения, чтобы привязать диалог к заявке.")
            return

        # дублируем каждое сообщение в таймлайн сделки
        try:
            amo = await AmoClient.create()
            await amo.add_note(st.lead_id, f"[TG->{bot_kind}] {m.text}")
        except Exception as e:
            # не падаем из-за временной ошибки
            print("add_note error:", e)

        # сохраняем ответ и двигаем опрос
        survey_store_answer(st, m.text or "")
        if st.step <= 2:
            await m.answer(survey_prompt(st))
        else:
            # завершение
            summary = survey_summary(st)
            try:
                amo = await AmoClient.create()
                await amo.add_tags(st.lead_id, [settings.AMO_TAG_SURVEY_DONE])
                await amo.add_note(st.lead_id, f"[{bot_kind}] {summary}")
            except Exception as e:
                print("finish note/tag error:", e)
            await m.answer("Спасибо! Мы передали информацию рекрутеру. С вами свяжутся.")
            SURVEYS.pop(m.from_user.id, None)

    return dp


async def main():
    await init_db()
    await ensure_tokens()
    # два бота параллельно
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
