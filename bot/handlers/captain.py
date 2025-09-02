from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.enums import ContentType
from ..api_client import team_by_tg, team_rename, start_game, submit_photo, current_checkpoint
from ..states import PhotoStates, CaptainStates   # ← NEW
from ..watchers import WATCHERS
from ..utils import format_roster
from ..texts import RULES_SHORT
from ..keyboards import ib_leaderboard          # ← NEW
from ..config import API_BASE                   # ← NEW

router = Router()

async def _ensure_captain(m: Message) -> bool:
    st, info = await team_by_tg(m.from_user.id)
    if st != 200:
        await m.answer("Ты не в команде. Набери /reg.")
        return False
    if not info.get("is_captain"):
        await m.answer("Эта команда у капитана. Передай управление капитану.")
        return False
    return True

# NEW: капитан просто пишет название в ответ на наше предложение
@router.message(CaptainStates.waiting_team_name, F.text)
async def set_team_name_plain(m: Message, state: FSMContext):
    if not await _ensure_captain(m):
        await state.clear()
        return
    new_name = (m.text or "").strip()
    if len(new_name) < 2:
        return await m.answer("Название слишком короткое. Напиши другое.")

    st, resp = await team_rename(m.from_user.id, new_name)
    if st == 200 and isinstance(resp, dict) and resp.get("ok"):
        await state.clear()
        await m.answer(f"Готово! Новое имя команды: *{resp.get('team_name')}*.", parse_mode="Markdown")

        # Инструкция + кнопка лидерборда (мини-приложение)
        rules = (
            RULES_SHORT
            + "\n\nКнопка ниже — *Лидерборд*: живая таблица команд в мини-приложении."
        )
        await m.answer(rules, parse_mode="Markdown", reply_markup=ib_leaderboard(f"{API_BASE}/webapp"))
        await m.answer("Когда будете готовы — запустите квест командой */startquest*.", parse_mode="Markdown")
    else:
        detail = resp.get("detail") if isinstance(resp, dict) else None
        await m.answer((detail or "Не удалось принять название. Попробуй другое.") + "\n\nПришли новое название.")

@router.message(F.text.regexp(r"^/rename(\s+.+)?$"))
async def cmd_rename(m: Message):
    if not await _ensure_captain(m):
        return
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return await m.answer("Просто пришли *название* одним сообщением (без команды).", parse_mode="Markdown")
    st, resp = await team_rename(m.from_user.id, parts[1].strip())
    if st == 200 and resp.get("ok"):
        await m.answer(f"Готово! Новое имя команды: *{resp.get('team_name')}*.", parse_mode="Markdown")
    else:
        await m.answer(resp.get("detail") or "Переименование недоступно.")

@router.message(F.text == "/startquest")
async def cmd_start(m: Message):
    if not await _ensure_captain(m):
        return
    st, resp = await start_game(m.from_user.id)
    if st == 200 and resp.get("ok"):
        await m.answer("🚀 Квест начат! Удачи!\n" + RULES_SHORT, parse_mode="Markdown")
        # watchers сам пришлёт задание (и на будущее — новые)
        st2, cur = await current_checkpoint(m.from_user.id)
        if st2 == 200 and not cur.get("finished"):
            WATCHERS.start(team_id=resp["team_id"], chat_id=m.chat.id, tg_id=m.from_user.id, bot=m.bot)
        else:
            await m.answer("Задания пока не найдены. Свяжитесь с координатором.")
    elif st == 200:
        await m.answer(resp.get("message") or "Уже начали.")
    else:
        await m.answer(resp.get("detail") or "Старт недоступен.")

@router.message(F.text == "/photo")
async def cmd_photo_hint(m: Message, state: FSMContext):
    if not await _ensure_captain(m):
        return
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
