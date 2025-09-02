import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from ..keyboards import kb_request_phone, kb_webapp
from ..api_client import register_user, roster_by_tg
from ..utils import norm_phone, KNOWN, load_participants, format_roster, only_first_name
from ..config import STRICT_WHITELIST, TEAM_SIZE, API_BASE
from ..texts import ONBOARDING, CAPTAIN_ASSIGNED, ASK_TEAM_NAME

router = Router()

@router.message(F.text.in_({"/start","start"}))
async def onboarding(m: Message):
    await m.answer(ONBOARDING, parse_mode="Markdown")

@router.message(F.text == "/reg")
async def reg_begin(m: Message, state: FSMContext):
    await state.set_state()  # сброс
    await m.answer("Шаг 1/2: пришли номер телефона в формате +7XXXXXXXXXX", reply_markup=kb_request_phone())

@router.message(F.contact)
async def reg_phone_contact(m: Message, state: FSMContext):
    # этап 1: телефон
    data = await state.get_data()
    if data.get("stage") == "name":  # уже на втором шаге
        return
    me = m.contact
    if me and me.user_id and m.from_user and me.user_id != m.from_user.id:
        return await m.answer("Нужен *твой* номер.", parse_mode="Markdown")
    phone = norm_phone(me.phone_number if me else "")
    if not phone:
        return await m.answer("Не распознал номер. Пришли ещё раз.")
    await state.update_data(stage="name", phone=phone)
    await m.answer("Шаг 2/2: пришли *имя* (как тебя записать в команде).", parse_mode="Markdown")

@router.message(F.text & ~F.text.startswith("/"))
async def reg_flow(m: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("stage") != "name":
        return  # не в процессе регистрации
    first = (m.text or "").strip().split()[0].title()
    if len(first) < 2:
        return await m.answer("Имя слишком короткое. Минимум 2 символа.")
    phone = data.get("phone","")
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

    # покажем состав + постоянную кнопку WebApp
    _, roster = await roster_by_tg(m.from_user.id)
    webapp = f"{API_BASE}/webapp"
    if roster:
        await m.answer(
            format_roster(roster), parse_mode="Markdown",
            reply_markup=kb_webapp(webapp)
        )
        members_count = len(roster.get("members") or [])
        cap = roster.get("captain")
        if cap:
            await m.answer(CAPTAIN_ASSIGNED.format(captain=only_first_name(cap)), parse_mode="Markdown")
            # если капитан — другой человек и команда уже полная — пинганём капитана
            if str(cap.get("tg_id")) != str(m.from_user.id) and members_count >= TEAM_SIZE:
                try:
                    await m.bot.send_message(cap["tg_id"], ASK_TEAM_NAME, parse_mode="Markdown")
                except Exception:
                    logging.exception("failed to DM captain about team name")
    else:
        await m.answer("Регистрация выполнена. /team — состав команды.", reply_markup=kb_webapp(webapp))