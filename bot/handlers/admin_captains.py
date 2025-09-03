# bot/handlers/admin_captains.py
from __future__ import annotations

import logging
import re
from typing import Optional

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

from ..config import ADMIN_CHAT_ID, ADMIN_USER_IDS
from ..api_client import admin_search_teams, admin_get_team, admin_set_captain
from ..keyboards_admin_captains import (
    kb_team_search_results,
    kb_roster_set_captain,
    kb_confirm_set_captain,
)

router = Router()


# --------------------------------------------------------------------------- #
# Админ-контекст: разрешаем
#  • сообщения в ADMIN_CHAT_ID
#  • ЛС с ботом от пользователей из ADMIN_USER_IDS (если список задан)
# --------------------------------------------------------------------------- #
def _is_admin_context(obj: Message | CallbackQuery) -> bool:
    chat = obj.chat if isinstance(obj, Message) else (obj.message.chat if obj.message else None)
    from_user = (
        obj.from_user
        if isinstance(obj, Message)
        else (obj.from_user or (obj.message.from_user if obj.message else None))
    )
    chat_id = chat.id if chat else None
    user_id = from_user.id if from_user else None

    if ADMIN_CHAT_ID and chat_id == int(ADMIN_CHAT_ID):
        return True
    if chat and chat.type == "private" and user_id and (ADMIN_USER_IDS and user_id in ADMIN_USER_IDS):
        return True
    return False


# --------------------------------------------------------------------------- #
# /capname <часть названия> — поиск команд по названию
# Поддержка /capname@BotUserName <...>
# --------------------------------------------------------------------------- #
@router.message(F.text.regexp(r"^/capname(?:@\w+)?(?:\s+(.*))?$"))
async def cmd_capname(m: Message):
    if not _is_admin_context(m):
        return

    mobj = re.match(r"^/capname(?:@\w+)?(?:\s+(.*))?$", m.text or "")
    query = (mobj.group(1) or "").strip() if mobj else ""

    if not query:
        return await m.answer(
            "Укажи часть названия: `/capname Команда`",
            parse_mode="Markdown",
        )

    try:
        st, items = await admin_search_teams(query, limit=20)
    except Exception:
        logging.exception("admin_captains: search request failed")
        return await m.answer("Ошибка поиска. Попробуй ещё раз.")

    if st != 200 or not isinstance(items, list) or not items:
        return await m.answer("Ничего не найдено.")

    note = "Найдено: {}".format(len(items))
    await m.answer(note, reply_markup=kb_team_search_results(items))


# --------------------------------------------------------------------------- #
# Выбор команды → показать состав и дать выбрать нового капитана
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.regexp(r"^capn:pick:(\d+)$"))
async def cb_pick_team(cq: CallbackQuery):
    if not _is_admin_context(cq):
        return await cq.answer("Недоступно")
    if not cq.message:
        return await cq.answer()

    team_id = int(re.match(r"^capn:pick:(\d+)$", cq.data or "").group(1))

    try:
        st, data = await admin_get_team(team_id)
    except Exception:
        logging.exception("admin_captains: get_team failed team_id=%s", team_id)
        return await cq.answer("Ошибка загрузки команды", show_alert=True)

    if st != 200 or not isinstance(data, dict):
        await cq.answer("Команда не найдена", show_alert=True)
        return

    members = data.get("members") or []
    if not members:
        await cq.message.edit_text(
            f"Команда *{data.get('team_name', 'без имени')}* (ID {data.get('team_id')}).\n"
            "В составе пока нет участников.",
            parse_mode="Markdown",
            reply_markup=None,
        )
        return await cq.answer()

    await cq.message.edit_text(
        f"Команда *{data.get('team_name')}* (ID {data.get('team_id')}) — выбери нового капитана:",
        parse_mode="Markdown",
        reply_markup=kb_roster_set_captain(team_id, members),
    )
    await cq.answer()


# --------------------------------------------------------------------------- #
# Подтверждение «сделать капитаном»
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.regexp(r"^capn:ask:(\d+):(\d+)$"))
async def cb_ask_confirm(cq: CallbackQuery):
    if not _is_admin_context(cq):
        return await cq.answer("Недоступно")
    if not cq.message:
        return await cq.answer()

    team_id, user_id = map(int, re.match(r"^capn:ask:(\d+):(\d+)$", cq.data or "").groups())

    # Получим имя участника для текста подтверждения
    display_name = f"ID {user_id}"
    try:
        st, data = await admin_get_team(team_id)
        if st == 200 and isinstance(data, dict):
            for m in (data.get("members") or []):
                if int(m.get("user_id")) == user_id:
                    fn = (m.get("first_name") or "").strip()
                    ln = (m.get("last_name") or "").strip()
                    if fn or ln:
                        display_name = (fn or ln).strip()
                    break
    except Exception:
        logging.warning("admin_captains: resolve member name failed team=%s user=%s", team_id, user_id)

    try:
        await cq.message.edit_text(
            f"Назначить *{display_name}* капитаном команды ID {team_id}?",
            parse_mode="Markdown",
            reply_markup=kb_confirm_set_captain(team_id, user_id),
        )
        await cq.answer()
    except Exception:
        logging.exception("admin_captains: ask/edit failed")
        await cq.answer("Ошибка", show_alert=True)


# --------------------------------------------------------------------------- #
# Отмена подтверждения → назад к составу
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.regexp(r"^capn:cancel:(\d+)$"))
async def cb_cancel(cq: CallbackQuery):
    if not _is_admin_context(cq):
        return await cq.answer("Недоступно")
    if not cq.message:
        return await cq.answer()

    team_id = int(re.match(r"^capn:cancel:(\d+)$", cq.data or "").group(1))

    try:
        st, data = await admin_get_team(team_id)
    except Exception:
        logging.exception("admin_captains: cancel/get_team failed team_id=%s", team_id)
        st, data = 500, None

    if st != 200 or not isinstance(data, dict):
        await cq.message.edit_reply_markup(reply_markup=None)
        return await cq.answer("Ошибка", show_alert=True)

    await cq.message.edit_text(
        f"Команда *{data.get('team_name')}* (ID {data.get('team_id')}) — выбери нового капитана:",
        parse_mode="Markdown",
        reply_markup=kb_roster_set_captain(team_id, data.get("members") or []),
    )
    await cq.answer("Отменено")


# --------------------------------------------------------------------------- #
# Подтверждено → назначаем капитана
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.regexp(r"^capn:ok:(\d+):(\d+)$"))
async def cb_ok(cq: CallbackQuery):
    if not _is_admin_context(cq):
        return await cq.answer("Недоступно")
    if not cq.message:
        return await cq.answer()

    team_id, user_id = map(int, re.match(r"^capn:ok:(\d+):(\d+)$", cq.data or "").groups())

    try:
        st, resp = await admin_set_captain(team_id, user_id=user_id)
    except Exception:
        logging.exception("admin_captains: set_captain failed team_id=%s user_id=%s", team_id, user_id)
        return await cq.answer("Не удалось назначить", show_alert=True)

    if st != 200 or not isinstance(resp, dict):
        return await cq.answer("Не удалось назначить", show_alert=True)

    await cq.message.edit_text(
        f"Капитан обновлён в команде *{resp.get('team_name') or f'ID {team_id}'}* (ID {team_id}).",
        parse_mode="Markdown",
        reply_markup=kb_roster_set_captain(team_id, resp.get("members") or []),
    )
    await cq.answer("Готово")