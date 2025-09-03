# bot/handlers/admin.py
from __future__ import annotations

import re
import logging
from typing import Any

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
)
from aiogram.utils.markdown import hbold, hlink

from ..config import ADMIN_CHAT_ID
from ..api_client import (
    admin_pending,
    admin_approve, admin_reject,
    admin_get_team,
)
from ..keyboards_admin import kb_proof_actions, kb_confirm

router = Router()


def _is_admin_chat(msg: Message | CallbackQuery) -> bool:
    chat_id = None
    if isinstance(msg, Message):
        chat_id = msg.chat.id
    else:
        if msg.message:
            chat_id = msg.message.chat.id
    return bool(ADMIN_CHAT_ID and chat_id and int(chat_id) == int(ADMIN_CHAT_ID))


def _fmt_caption(proof: dict, team_info: dict | None) -> str:
    """
    Формируем подпись к фото для админ-чата (HTML parse_mode).
    proof из /api/admin/proofs/pending, team_info из /api/admin/teams/{id}
    """
    team_name = proof.get("team_name") or "?"
    route = proof.get("route") or "?"
    order_num = proof.get("order_num") or "?"
    cp_title = proof.get("checkpoint_title") or "?"

    captain_line = "капитан: неизвестен"
    if team_info and team_info.get("captain"):
        cap = team_info["captain"]
        cap_fn = (cap.get("first_name") or "").strip()
        cap_ln = (cap.get("last_name") or "").strip()
        cap_name = (cap_fn or cap_ln or "без имени").strip()
        cap_tg = cap.get("tg_id")
        if cap_tg:
            # tg deep link
            link = f"tg://user?id={cap_tg}"
            captain_line = f'капитан: {hlink(cap_name, link)}'
        else:
            captain_line = f"капитан: {cap_name}"

    lines = [
        f"{hbold('Команда')}: {team_name}",
        f"{hbold('Маршрут')}: {route}",
        f"{hbold('Задание')}: {order_num} — {cp_title}",
        captain_line,
    ]
    return "\n".join(lines)


async def _send_proof_card(bot, chat_id: int | str, proof: dict):
    """
    Публичный хелпер — его вызывает AdminWatcher.
    Тянем инфо о команде, шлём фото с подписью и клавиатурой.
    """
    try:
        # team details (капитан, и т.п.)
        st_team, team_info = await admin_get_team(int(proof["team_id"]))
        if st_team != 200:
            team_info = None
    except Exception:
        logging.exception("admin: failed to fetch team info for proof %s", proof.get("id"))
        team_info = None

    caption = _fmt_caption(proof, team_info)

    try:
        await bot.send_photo(
            chat_id= int(chat_id),
            photo= proof.get("photo_file_id"),
            caption= caption,
            parse_mode="HTML",
            reply_markup= kb_proof_actions(int(proof["id"])),
        )
    except Exception:
        logging.exception("admin: send_photo failed for proof %s", proof.get("id"))


# -------------------- Команды/кнопки только в админ-чате ---------------------

@router.message(F.text == "/pending")
async def admin_pending_cmd(m: Message):
    if not _is_admin_chat(m):
        return
    st, items = await admin_pending()
    if st != 200:
        return await m.answer("Не удалось получить список ожиданий.")
    if not items:
        return await m.answer("Очередь пуста.")
    await m.answer(f"В очереди: {len(items)}")


@router.callback_query(F.data.regexp(r"^adm:appr:(\d+)$"))
async def cb_approve_prompt(cq: CallbackQuery):
    if not _is_admin_chat(cq):
        return await cq.answer("Недоступно", show_alert=False)
    m = cq.message
    if not m:
        return await cq.answer()

    pid = int(re.search(r"^adm:appr:(\d+)$", cq.data).group(1))
    try:
        await cq.answer("Подтвердите зачёт…", show_alert=False)
        # просто заменяем клавиатуру на подтверждение
        await m.edit_reply_markup(reply_markup=kb_confirm("appr", pid))
    except Exception:
        logging.exception("admin: approve prompt edit failed")


@router.callback_query(F.data.regexp(r"^adm:rej:(\d+)$"))
async def cb_reject_prompt(cq: CallbackQuery):
    if not _is_admin_chat(cq):
        return await cq.answer("Недоступно", show_alert=False)
    m = cq.message
    if not m:
        return await cq.answer()

    pid = int(re.search(r"^adm:rej:(\d+)$", cq.data).group(1))
    try:
        await cq.answer("Подтвердите отклонение…", show_alert=False)
        await m.edit_reply_markup(reply_markup=kb_confirm("rej", pid))
    except Exception:
        logging.exception("admin: reject prompt edit failed")


@router.callback_query(F.data.regexp(r"^adm:cancel:(\d+)$"))
async def cb_cancel(cq: CallbackQuery):
    if not _is_admin_chat(cq):
        return await cq.answer("Недоступно")
    m = cq.message
    if not m:
        return await cq.answer()

    pid = int(re.search(r"^adm:cancel:(\d+)$", cq.data).group(1))
    try:
        await cq.answer("Отменено")
        await m.edit_reply_markup(reply_markup=kb_proof_actions(pid))
    except Exception:
        logging.exception("admin: cancel restore kb failed")


@router.callback_query(F.data.regexp(r"^adm:ok:(appr|rej):(\d+)$"))
async def cb_confirm_action(cq: CallbackQuery):
    if not _is_admin_chat(cq):
        return await cq.answer("Недоступно")
    m = cq.message
    if not m:
        return await cq.answer()

    action, pid_s = re.search(r"^adm:ok:(appr|rej):(\d+)$", cq.data).groups()
    pid = int(pid_s)

    # делаем запрос в API
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
        # если уже обработан — тоже снимем клавиатуру
        await cq.answer("Не удалось обработать (возможно, уже обработан).", show_alert=True)
        try:
            await m.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    # помечаем в подписи статус и убираем кнопки
    try:
        new_suffix = "✅ ЗАЧТЕНО" if action == "appr" else "❌ ОТКЛОНЕНО"
        cap = m.caption or ""
        if new_suffix not in cap:
            cap = f"{cap}\n\n{new_suffix}" if cap else new_suffix
        await m.edit_caption(caption=cap, parse_mode="HTML", reply_markup=None)
    except Exception:
        logging.exception("admin: edit_caption after action failed")

    await cq.answer("Готово")