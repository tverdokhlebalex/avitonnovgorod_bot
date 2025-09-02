# bot/handlers/captain.py
from aiogram import Router, F
from aiogram.types import Message
from aiogram.enums import ContentType

from ..api_client import (
    team_by_tg,
    team_rename,
    start_game,
    submit_photo,
    roster_by_tg,
)
from ..watchers import WATCHERS
from ..texts import RULES_SHORT, STARTED_MSG, APP_HINT
from ..keyboards import kb_confirm_start, ib_webapp
from ..config import API_BASE

router = Router()


async def _load_team(m: Message) -> dict | None:
    st, info = await team_by_tg(m.from_user.id)
    if st != 200:
        await m.answer("Ты не в команде. Набери /reg.")
        return None
    return info


def _is_captain(info: dict) -> bool:
    return bool(info and info.get("is_captain"))


async def _broadcast_to_team(m: Message, text: str, *, markdown: bool = False) -> None:
    """Отправить сообщение всем участникам команды (включая капитана)."""
    st, roster = await roster_by_tg(m.from_user.id)
    parse_mode = "Markdown" if markdown else None
    if st != 200 or not roster:
        await m.answer(text, parse_mode=parse_mode)
        return
    sent: set[str] = set()
    for mem in (roster.get("members") or []):
        tg_id = mem.get("tg_id")
        if not tg_id or tg_id in sent:
            continue
        try:
            await m.bot.send_message(tg_id, text, parse_mode=parse_mode)
            sent.add(tg_id)
        except Exception:
            pass
    # на всякий — капитану тоже (если не был в members)
    if str(m.from_user.id) not in sent:
        try:
            await m.bot.send_message(m.from_user.id, text, parse_mode=parse_mode)
        except Exception:
            pass


# --- Переименование без /rename: капитан просто пишет название ---

@router.message(F.text & ~F.text.startswith("/"))
async def maybe_team_name(m: Message):
    info = await _load_team(m)
    if not info or not _is_captain(info):
        return
    if not info.get("can_rename", True) or info.get("started_at"):
        return

    new_name = (m.text or "").strip()
    if len(new_name) < 2:
        return

    st, resp = await team_rename(m.from_user.id, new_name)
    if st == 200 and resp.get("ok"):
        await m.answer(
            f"Готово! Новое имя команды: *{resp.get('team_name')}*.",
            parse_mode="Markdown",
        )
        await m.answer(RULES_SHORT, parse_mode="Markdown")
        await m.answer("Готовы стартовать?", reply_markup=kb_confirm_start())
    # 409 и пр. — молча игнорим


# --- /rename (оставляем как запасной путь) ---

@router.message(F.text.regexp(r"^/rename(\s+.+)?$"))
async def cmd_rename(m: Message):
    info = await _load_team(m)
    if not info or not _is_captain(info):
        return

    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return await m.answer("Использование: `/rename Новое имя команды`", parse_mode="Markdown")

    st, resp = await team_rename(m.from_user.id, parts[1].strip())
    if st == 200 and resp.get("ok"):
        await m.answer(
            f"Готово! Новое имя команды: *{resp.get('team_name')}*.",
            parse_mode="Markdown",
        )
        await m.answer(RULES_SHORT, parse_mode="Markdown")
        await m.answer("Готовы стартовать?", reply_markup=kb_confirm_start())
    else:
        await m.answer(resp.get("detail") or "Переименование недоступно.")


# --- Старт: кнопка «Стартовать» или /startquest ---

@router.message(F.text.in_({"/startquest", "Стартовать"}))
async def cmd_start(m: Message):
    info = await _load_team(m)
    if not info or not _is_captain(info):
        return

    st, resp = await start_game(m.from_user.id)
    if st == 200 and resp.get("ok"):
        # 1) Всем участникам — уведомление о старте
        await _broadcast_to_team(m, STARTED_MSG)

        # 2) Включаем вотчер: пришлёт ПЕРВОЕ задание сам
        WATCHERS.start(team_id=resp["team_id"], chat_id=m.chat.id, tg_id=m.from_user.id, bot=m.bot)

        # 3) Подсказка про мини-приложение (+кнопка, если https)
        webapp_url = f"{API_BASE}/webapp"
        kb = ib_webapp(webapp_url)
        if kb:
            await m.answer(APP_HINT, parse_mode="Markdown", reply_markup=kb)
        else:
            await m.answer(APP_HINT, parse_mode="Markdown")
    elif st == 200:
        await m.answer(resp.get("message") or "Уже начали.")
    else:
        await m.answer(resp.get("detail") or "Старт недоступен.")


# --- Фото: только от капитана ---

@router.message(F.text == "/photo")
async def cmd_photo_hint(m: Message):
    info = await _load_team(m)
    if not info or not _is_captain(info):
        return
    await m.answer("Ок! Пришли *фото* текущей точки одним сообщением.", parse_mode="Markdown")


@router.message(F.content_type == ContentType.PHOTO)
async def on_any_photo(m: Message):
    info = await _load_team(m)
    if not info or not _is_captain(info):
        return await m.answer("Эта команда уже имеет капитана. Со мной общается только капитан.")

    file_id = m.photo[-1].file_id
    st2, resp = await submit_photo(m.from_user.id, file_id)
    if st2 == 200 and resp.get("ok"):
        await m.answer("Принял, отправил модератору. Ждём ⚡")
        WATCHERS.start(team_id=info["team_id"], chat_id=m.chat.id, tg_id=m.from_user.id, bot=m.bot)
    else:
        await m.answer(resp.get("detail") or "Не удалось отправить фото.")