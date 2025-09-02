from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.enums import ContentType
from ..api_client import team_by_tg, team_rename, start_game, submit_photo
from ..states import PhotoStates, CaptainStates
from ..watchers import WATCHERS
from ..utils import format_roster
from ..texts import RULES_SHORT
from ..keyboards import ib_leaderboard

router = Router()

async def _ensure_captain(m: Message) -> bool:
    st, info = await team_by_tg(m.from_user.id)
    if st != 200:
        await m.answer("Ты не в команде. Набери /reg.")
        return False
    if not info.get("is_captain"):
        await m.answer("Эта команда уже назначила капитана. Попроси капитана написать мне.")
        return False
    return True

@router.message(CaptainStates.waiting_team_name, F.text)
async def captain_name_state(m: Message, state: FSMContext):
    if not await _ensure_captain(m): 
        return await state.clear()
    new_name = (m.text or "").strip()
    if len(new_name) < 2:
        return await m.answer("Название слишком короткое. Ещё раз.")
    st, resp = await team_rename(m.from_user.id, new_name)
    await state.clear()
    if st == 200 and resp.get("ok"):
        await m.answer(f"Готово! Новое имя команды: *{resp.get('team_name')}*.", parse_mode="Markdown")
        await m.answer(RULES_SHORT, parse_mode="Markdown", reply_markup=ib_leaderboard())
    else:
        await m.answer(resp.get("detail") or "Переименование недоступно.")

# Fallback: капитан мог не попасть в state — принимаем свободный текст как название
@router.message(F.text)
async def free_text_as_team_name(m: Message, state: FSMContext):
    # отработаем только если капитан и можно переименовать
    st, info = await team_by_tg(m.from_user.id)
    if st != 200 or not info.get("is_captain"):
        return  # не капитан → пропускаем дальше
    # простая эвристика: дефолтное имя или can_rename ещё True на сервере
    if (info.get("team_name","").startswith("Команда №")) and info.get("route_id") is not None:
        new_name = (m.text or "").strip()
        if len(new_name) >= 2:
            st2, resp = await team_rename(m.from_user.id, new_name)
            if st2 == 200 and resp.get("ok"):
                await m.answer(f"Готово! Новое имя команды: *{resp.get('team_name')}*.", parse_mode="Markdown")
                await m.answer(RULES_SHORT, parse_mode="Markdown", reply_markup=ib_leaderboard())
                return
    # иначе никак не реагируем — другие хэндлеры подхватят

@router.message(F.text.regexp(r"^/rename(\s+.+)?$"))
async def cmd_rename(m: Message):
    if not await _ensure_captain(m): return
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return await m.answer("Просто пришли новое имя *текстом*.\nИли: `/rename Новое имя`", parse_mode="Markdown")
    st, resp = await team_rename(m.from_user.id, parts[1].strip())
    if st == 200 and resp.get("ok"):
        await m.answer(f"Готово! Новое имя команды: *{resp.get('team_name')}*.", parse_mode="Markdown")
        await m.answer(RULES_SHORT, parse_mode="Markdown", reply_markup=ib_leaderboard())
    else:
        await m.answer(resp.get("detail") or "Переименование недоступно.")

@router.message(F.text == "/startquest")
async def cmd_start(m: Message):
    if not await _ensure_captain(m): return
    st, resp = await start_game(m.from_user.id)
    if st == 200 and resp.get("ok"):
        await m.answer("🚀 Квест начат! Удачи!", parse_mode="Markdown")
        # ВСЕГДА запускаем вотчер — он сам пришлёт первое задание
        WATCHERS.start(team_id=resp["team_id"], chat_id=m.chat.id, tg_id=m.from_user.id, bot=m.bot)
    elif st == 200:
        await m.answer(resp.get("message") or "Уже начали.")
    else:
        await m.answer(resp.get("detail") or "Старт недоступен.")

@router.message(F.text == "/photo")
async def cmd_photo_hint(m: Message, state: FSMContext):
    if not await _ensure_captain(m): return
    await state.set_state(PhotoStates.waiting_photo)
    await m.answer("Ок! Пришли *фото* текущей точки одним сообщением.", parse_mode="Markdown")

@router.message(PhotoStates.waiting_photo, F.content_type == ContentType.PHOTO)
async def on_photo(m: Message, state: FSMContext):
    if not await _ensure_captain(m):
        await state.clear()
        return
    file_id = m.photo[-1].file_id
    st, resp = await submit_photo(m.from_user.id, file_id)
    await state.clear()
    if st == 200 and resp.get("ok"):
        await m.answer("Принял, отправил модератору. Ждём ⚡")
        # вотчер уже запущен после старта, но на всякий включим
        st_team, info = await team_by_tg(m.from_user.id)
        if st_team == 200:
            WATCHERS.start(team_id=info["team_id"], chat_id=m.chat.id, tg_id=m.from_user.id, bot=m.bot)
    else:
        await m.answer(resp.get("detail") or "Не удалось отправить фото.")

@router.message(F.content_type == ContentType.PHOTO)
async def on_any_photo(m: Message, state: FSMContext):
    st, info = await team_by_tg(m.from_user.id)
    if st == 200 and info.get("is_captain"):
        file_id = m.photo[-1].file_id
        st2, resp = await submit_photo(m.from_user.id, file_id)
        if st2 == 200 and resp.get("ok"):
            await m.answer("Принял, отправил модератору. Ждём ⚡")
            WATCHERS.start(team_id=info["team_id"], chat_id=m.chat.id, tg_id=m.from_user.id, bot=m.bot)
        else:
            await m.answer(resp.get("detail") or "Не удалось отправить фото.")
