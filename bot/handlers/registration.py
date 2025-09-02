# bot/handlers/registration.py
import os
import logging
from urllib.parse import urlparse

from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from ..states import RegStates
from ..keyboards import kb_request_phone, ib_webapp
from ..api_client import register_user, roster_by_tg
from ..utils import norm_phone, KNOWN, load_participants, format_roster, only_first_name
from ..config import STRICT_WHITELIST, TEAM_SIZE, API_BASE
from ..texts import ONBOARDING, CAPTAIN_ASSIGNED, ASK_TEAM_NAME

router = Router()


def _public_webapp_url() -> str | None:
    """
    Берём WEBAPP_PUBLIC_URL (если задан) иначе API_BASE/webapp.
    Возвращаем только https:// — иначе None (иначе Telegram уронит кнопку).
    """
    raw = os.getenv("WEBAPP_PUBLIC_URL") or f"{API_BASE}/webapp"
    try:
        p = urlparse(raw)
        if p.scheme == "https":
            return raw
    except Exception:
        pass
    return None


@router.message(F.text.in_({"/start", "start"}))
async def onboarding(m: Message):
    await m.answer(ONBOARDING, parse_mode="Markdown")


@router.message(F.text == "/reg")
async def reg_begin(m: Message, state: FSMContext):
    await state.set_state(RegStates.waiting_phone)
    await m.answer(
        "Шаг 1/2: пришли номер телефона в формате +7XXXXXXXXXX",
        reply_markup=kb_request_phone()
    )


@router.message(RegStates.waiting_phone, F.contact)
async def reg_phone_contact(m: Message, state: FSMContext):
    me = m.contact
    if me and me.user_id and m.from_user and me.user_id != m.from_user.id:
        return await m.answer("Нужен *твой* номер.", parse_mode="Markdown")
    phone = norm_phone(me.phone_number if me else "")
    if not phone:
        return await m.answer("Не распознал номер. Пришли ещё раз.")
    await state.update_data(phone=phone)
    await state.set_state(RegStates.waiting_name)
    await m.answer("Шаг 2/2: пришли *имя* (как тебя записать в команде).", parse_mode="Markdown")


@router.message(RegStates.waiting_phone, F.text)
async def reg_phone_text(m: Message, state: FSMContext):
    phone = norm_phone(m.text or "")
    if not phone:
        return await m.answer("Формат телефона не распознан. Пример: +79991234567")
    await state.update_data(phone=phone)
    await state.set_state(RegStates.waiting_name)
    await m.answer("Шаг 2/2: пришли *имя* (как тебя записать в команде).", parse_mode="Markdown")


@router.message(RegStates.waiting_name, F.text)
async def reg_name(m: Message, state: FSMContext):
    first = (m.text or "").strip().split()[0].title()
    if len(first) < 2:
        return await m.answer("Имя слишком короткое. Минимум 2 символа.")

    data = await state.get_data()
    phone = data.get("phone", "")

    if STRICT_WHITELIST:
        load_participants()
        if phone not in KNOWN:
            await state.clear()
            return await m.answer("Не нашёл тебя в списке. Обратись к координатору.")

    st, payload = await register_user(m.from_user.id, phone, first)
    await state.clear()
    if st != 200:
        logging.error("register_user failed: %s %s", st, payload)
        return await m.answer("Сервис регистрации временно недоступен.")

    # Состав + (опционально) кнопка WebApp
    st_r, roster = await roster_by_tg(m.from_user.id)
    if st_r == 200 and roster:
        roster_text = format_roster(roster)
        webapp_url = _public_webapp_url()
        kb = ib_webapp(webapp_url)

        if kb:
            await m.answer(roster_text, parse_mode="Markdown", reply_markup=kb)
        else:
            await m.answer(roster_text, parse_mode="Markdown")

        # «Капитаном назначен …»
        cap = roster.get("captain")
        if cap:
            await m.answer(CAPTAIN_ASSIGNED.format(captain=only_first_name(cap)), parse_mode="Markdown")

        # Если команда полная — просим капитана назвать команду
        members_count = len(roster.get("members") or [])
        if cap and members_count >= TEAM_SIZE:
            try:
                if str(cap.get("tg_id")) == str(m.from_user.id):
                    await m.answer("Команда выглядит полной. " + ASK_TEAM_NAME)
                else:
                    await m.bot.send_message(cap["tg_id"], ASK_TEAM_NAME)
            except Exception:
                logging.debug("Failed to DM captain about team name")
    else:
        await m.answer("Регистрация выполнена. /team — состав команды.")