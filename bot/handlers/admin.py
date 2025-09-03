# bot/handlers/admin.py
from __future__ import annotations

import logging
import re
from typing import Optional, Tuple

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.utils.markdown import hbold, hlink

from ..config import ADMIN_CHAT_ID
from ..api_client import (
    admin_pending,
    admin_approve,
    admin_reject,
    admin_get_team,
)
from ..keyboards_admin import (
    kb_proof_actions,
    kb_confirm,
)

router = Router()

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _is_admin_chat(obj: Message | CallbackQuery) -> bool:
    chat_id: Optional[int] = None
    if isinstance(obj, Message):
        chat_id = obj.chat.id
    else:
        if obj.message:
            chat_id = obj.message.chat.id
    return bool(ADMIN_CHAT_ID and chat_id and int(chat_id) == int(ADMIN_CHAT_ID))


def _captain_from_team(team_info: dict | None) -> Tuple[Optional[str], Optional[str]]:
    """
    Возвращает (captain_tg_id, captain_name)
    """
    if not team_info:
        return None, None
    cap = team_info.get("captain") or {}
    cap_tg = cap.get("tg_id")
    fn = (cap.get("first_name") or "").strip()
    ln = (cap.get("last_name") or "").strip()
    name = (fn or ln or "без имени").strip() if (fn or ln) else None
    return (str(cap_tg) if cap_tg else None), name


def _fmt_caption(proof: dict, team_info: dict | None) -> str:
    """
    Подпись к фото (parse_mode=HTML): Команда, ID команды, Маршрут, Задание, Капитан (ссылка).
    """
    team_name = proof.get("team_name") or "?"
    team_id = proof.get("team_id") or "?"
    route = proof.get("route") or "?"
    order_num = proof.get("order_num") or "?"
    cp_title = proof.get("checkpoint_title") or "?"

    cap_tg, cap_name = _captain_from_team(team_info)
    if cap_tg:
        cap_line = f"капитан: {hlink(cap_name or 'без имени', f'tg://user?id={cap_tg}')}"
    elif cap_name:
        cap_line = f"капитан: {cap_name}"
    else:
        cap_line = "капитан: неизвестен"

    lines = [
        f"{hbold('Команда')}: {team_name}",
        f"{hbold('ID команды')}: {team_id}",
        f"{hbold('Маршрут')}: {route}",
        f"{hbold('Задание')}: {order_num} — {cp_title}",
        cap_line,
    ]
    return "\n".join(lines)


async def _send_proof_card(bot: Bot, chat_id: int | str, proof: dict):
    """
    Вызывает AdminWatcher: тянем инфо о команде, шлём фото с подписью и клавиатурой.
    callback_data включает pid + (по возможности) cap_tg и team_id.
    """
    team_info: dict | None = None
    cap_tg_for_cb: Optional[str] = None
    team_id_for_cb: Optional[int] = None
    try:
        team_id_for_cb = int(proof.get("team_id") or 0) or None
        st_team, team_info = await admin_get_team(int(proof["team_id"]))
        if st_team != 200:
            team_info = None
        cap_tg_for_cb, _ = _captain_from_team(team_info)
    except Exception:
        logging.exception("admin: failed to fetch team info for proof %s", proof.get("id"))

    caption = _fmt_caption(proof, team_info)
    try:
        await bot.send_photo(
            chat_id=int(chat_id),
            photo=proof.get("photo_file_id"),
            caption=caption,
            parse_mode="HTML",
            reply_markup=kb_proof_actions(
                int(proof["id"]),
                captain_tg_id=cap_tg_for_cb,
                team_id=team_id_for_cb,
            ),
        )
    except Exception:
        logging.exception("admin: send_photo failed for proof %s", proof.get("id"))

# экспорт для AdminWatcher
__all__ = ["router", "_send_proof_card"]

# --------------------------------------------------------------------------- #
# Команда статуса очереди — только в админ-чате
# --------------------------------------------------------------------------- #

@router.message(F.text == "/pending")
async def admin_pending_cmd(m: Message):
    if not _is_admin_chat(m):
        return
    st, items = await admin_pending()
    if st != 200:
        return await m.answer("Не удалось получить очередь.")
    if not items:
        return await m.answer("Очередь пуста.")
    await m.answer(f"В ожидании: {len(items)}")

# --------------------------------------------------------------------------- #
# Колбэки
#
# Поддерживаем НОВЫЙ и СТАРЫЙ форматы:
#  новый:  adm:(appr|rej):<pid>[:<cap_tg_id>[:<team_id>]]
#  ok:     adm:ok:(appr|rej):<pid>[:<cap_tg_id>[:<team_id>]]
#  старый: те же, но без cap_tg_id и team_id (т.е. только pid)
# --------------------------------------------------------------------------- #

# промпты «Зачесть/Отклонить»
@router.callback_query(F.data.regexp(r"^adm:(appr|rej):(\d+)(?::(\d+))?(?::(\d+))?$"))
async def cb_prompt(cq: CallbackQuery):
    if not _is_admin_chat(cq):
        return await cq.answer("Недоступно")
    if not cq.message:
        return await cq.answer()

    m = re.match(r"^adm:(appr|rej):(\d+)(?::(\d+))?(?::(\d+))?$", cq.data or "")
    if not m:
        return await cq.answer()

    action, pid_s, cap_s, team_s = m.groups()
    pid = int(pid_s)
    cap = cap_s or "0"
    team_id = int(team_s) if team_s else None

    try:
        await cq.answer("Подтвердите действие…", show_alert=False)
        await cq.message.edit_reply_markup(
            reply_markup=kb_confirm(action, pid, cap, team_id)
        )
    except Exception:
        logging.exception("admin: prompt edit failed (action=%s, pid=%s)", action, pid)


# отмена подтверждения
@router.callback_query(F.data.regexp(r"^adm:cancel:(\d+)$"))
async def cb_cancel(cq: CallbackQuery):
    if not _is_admin_chat(cq):
        return await cq.answer("Недоступно")
    if not cq.message:
        return await cq.answer()

    pid = int(re.match(r"^adm:cancel:(\d+)$", cq.data or "").group(1))
    try:
        await cq.answer("Отменено")
        # восстановим обычные кнопки без дополнительных данных
        await cq.message.edit_reply_markup(reply_markup=kb_proof_actions(pid))
    except Exception:
        logging.exception("admin: cancel restore kb failed")


# подтверждение действия
@router.callback_query(F.data.regexp(r"^adm:ok:(appr|rej):(\d+)(?::(\d+))?(?::(\d+))?$"))
async def cb_confirm_action(cq: CallbackQuery):
    if not _is_admin_chat(cq):
        return await cq.answer("Недоступно")
    if not cq.message:
        return await cq.answer()

    m = re.match(r"^adm:ok:(appr|rej):(\d+)(?::(\d+))?(?::(\d+))?$", cq.data or "")
    if not m:
        return await cq.answer()

    action, pid_s, cap_s, team_s = m.groups()
    pid = int(pid_s)
    cap_tg_id: Optional[str] = cap_s if cap_s and cap_s != "0" else None
    team_id: Optional[int] = int(team_s) if team_s else None

    # если cap_tg_id нет — попробуем вытащить team_id из подписи, затем дернуть /admin/teams/{id}
    if not cap_tg_id:
        try:
            if cq.message.caption:
                mteam = re.search(r"ID команды\D+(\d+)", cq.message.caption)
                if mteam:
                    team_id = int(mteam.group(1))
            if team_id:
                st, tinfo = await admin_get_team(team_id)
                if st == 200:
                    cap_tg_id, _ = _captain_from_team(tinfo)
        except Exception:
            logging.warning("admin: fallback to fetch captain failed for team_id=%s", team_id)

    # API вызов
    try:
        if action == "appr":
            st, payload = await admin_approve(pid)
        else:
            st, payload = await admin_reject(pid)
    except Exception:
        logging.exception("admin: API call failed (action=%s, pid=%s)", action, pid)
        return await cq.answer("Ошибка связи с API", show_alert=True)

    ok = (st == 200 and isinstance(payload, dict) and payload.get("ok") is True)
    if not ok:
        await cq.answer("Не удалось обработать (возможно, уже обработан).", show_alert=True)
        # В любом случае убираем клавиатуру, чтобы исключить повторные клики
        try:
            await cq.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    # Обновляем подпись и полностью убираем клавиатуру
    suffix = "✅ ЗАЧТЕНО" if action == "appr" else "❌ ОТКЛОНЕНО"
    try:
        new_caption = cq.message.caption or ""
        if suffix not in new_caption:
            new_caption = f"{new_caption}\n\n{suffix}" if new_caption else suffix
        await cq.message.edit_caption(caption=new_caption, parse_mode="HTML", reply_markup=None)
    except Exception:
        logging.exception("admin: edit_caption after action failed")

    # Уведомим капитана при ОТКЛОНЕНИИ
    if cap_tg_id and action == "rej":
        try:
            order_num = "?"
            cp_title = "задание"
            if cq.message.caption:
                mm = re.search(r"Задание[^:]*:\s*([0-9]+)\s+—\s+(.+)", cq.message.caption)
                if mm:
                    order_num, cp_title = mm.group(1), mm.group(2)
            text = f"Фото по заданию {order_num} — {cp_title} отклонено модератором. Пришлите новое фото."
            await cq.bot.send_message(int(cap_tg_id), text)
        except Exception:
            logging.warning("admin: failed to notify captain tg_id=%s", cap_tg_id)

    await cq.answer("Готово")