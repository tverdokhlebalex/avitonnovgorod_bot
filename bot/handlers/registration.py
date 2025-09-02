import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from ..states import RegStates, CaptainStates
from ..keyboards import kb_request_phone, kb_user_main, ib_leaderboard
from ..api_client import register_user, roster_by_tg
from ..utils import norm_phone, KNOWN, load_participants, format_roster, only_first_name
from ..config import STRICT_WHITELIST, TEAM_SIZE
from ..texts import ONBOARDING, CAPTAIN_ASSIGNED

router = Router()

@router.message(F.text.in_({"/start","start"}))
async def onboarding(m: Message):
    await m.answer(ONBOARDING, parse_mode="Markdown")

@router.message(F.text == "/reg")
async def reg_begin(m: Message, state: FSMContext):
    await state.set_state(RegStates.waiting_phone)
    await m.answer("Шаг 1/2: пришли номер телефона в формате +7XXXXXXXXXX", reply_markup=kb_request_phone())

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
    phone = data.get("phone","")

    if STRICT_WHITELIST:
        load_participants()
        if phone not in KNOWN:
            return await m.answer("Не нашёл тебя в списке. Обратись к координатору.")

    st, payload = await register_user(m.from_user.id, phone, first)
    if st != 200:
        logging.error("register_user failed: %s %s", st, payload)
        await state.clear()
        return await m.answer("Сервис регистрации временно недоступен.")
    await state.clear()

    # Показать состав + кнопки
    _, roster = await roster_by_tg(m.from_user.id)
    if not roster:
        return await m.answer("Регистрация выполнена. /team — состав команды.")

    await m.answer(format_roster(roster), parse_mode="Markdown", reply_markup=kb_user_main())
    await m.answer(".", reply_markup=ib_leaderboard(m.from_user.id))  # без лишнего текста

    members_count = len(roster.get("members") or [])
    cap = roster.get("captain")

    # Сообщение о назначении капитана — всем
    if cap:
        await m.answer(CAPTAIN_ASSIGNED.format(captain=only_first_name(cap)), parse_mode="Markdown")

    # Если тек. пользователь — капитан и команда полная → просим имя
    if cap and str(cap.get("tg_id")) == str(m.from_user.id) and members_count >= TEAM_SIZE:
        await m.answer("Команда выглядит полной. Придумайте название:", parse_mode="Markdown")
        return await state.set_state(CaptainStates.waiting_team_name)

    # Если капитан другой и команда только что стала полной → пинганём капитана
    if cap and members_count >= TEAM_SIZE and str(cap.get("tg_id")) != str(m.from_user.id):
        try:
            await m.bot.send_message(
                int(cap["tg_id"]),
                "Команда выглядит полной. Придумайте название:",
                parse_mode="Markdown"
            )
        except Exception:
            logging.exception("Не удалось написать капитану про нейминг")