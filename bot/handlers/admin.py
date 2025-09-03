# bot/handlers/admin.py
import re
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from ..config import ADMIN_IDS, ADMIN_CHAT_ID
from ..api_client import admin_pending, admin_approve, admin_reject, admin_get_team

router = Router(name="admin")

# --- клавиатуры ---
def kb_proof_actions(pid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Зачесть",   callback_data=f"adm:appr:{pid}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm:rej:{pid}"),
    ]])

def kb_confirm(action: str, pid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Да, подтвердить", callback_data=f"adm:ok:{action}:{pid}"),
        InlineKeyboardButton(text="Отмена",          callback_data=f"adm:cancel:{pid}"),
    ]])

# --- доступ только для админов ---
def _admin_only(obj: Message | CallbackQuery) -> bool:
    uid = obj.from_user.id if getattr(obj, "from_user", None) else 0
    return uid in ADMIN_IDS

# --- публичная функция для админ-вотчера ---
async def _send_proof_card(bot, chat_id: int, p: dict):
    # подтянем капитана для удобной ссылки
    cap_link = "капитан: неизвестен"
    try:
        st, team = await admin_get_team(p.get("team_id"))
        cap = (team or {}).get("captain")
        if st == 200 and cap and cap.get("tg_id"):
            cap_link = f"[капитан](tg://user?id={cap['tg_id']})"
    except Exception:
        pass

    caption = (
        f"*Новая заявка #{p['id']}*\n"
        f"Команда: *{p.get('team_name','?')}* (id {p.get('team_id')})\n"
        f"Маршрут: {p.get('route','?')}  •  Чекпойнт: {p.get('order_num')} — {p.get('checkpoint_title')}\n"
        f"{cap_link}"
    )
    kb = kb_proof_actions(int(p["id"]))

    # фото — это Telegram file_id
    photo_id = p.get("photo_file_id") or ""
    try:
        await bot.send_photo(chat_id, photo=photo_id, caption=caption, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        # на крайний — просто текст
        await bot.send_message(chat_id, caption + f"\n\n(фото: `{photo_id}`)", parse_mode="Markdown", reply_markup=kb)

# --- команды админа ---
@router.message(F.text == "/admin")
async def cmd_admin_help(m: Message):
    if not _admin_only(m): return
    await m.answer(
        "Админ-панель:\n"
        "/pending — показать последние PENDING\n"
        "/approve <id> — зачесть\n"
        "/reject <id> — отклонить\n"
    )

@router.message(F.text.startswith("/pending"))
async def cmd_pending(m: Message):
    if not _admin_only(m): return
    st, items = await admin_pending()
    if st != 200:
        return await m.answer("Не удалось получить список заявок.")
    if not items:
        return await m.answer("Ожидающих заявок нет.")
    lines = [f"#{it['id']}: team {it['team_id']} • {it['checkpoint_title']} ({it['order_num']})" for it in items[-10:]]
    await m.answer("Последние PENDING:\n" + "\n".join(lines))

@router.message(F.text.regexp(r"^/approve\s+(\d+)$"))
async def cmd_approve(m: Message, regexp: re.Match):
    if not _admin_only(m): return
    pid = int(regexp.group(1))
    await m.answer(f"Зачесть заявку #{pid}?", reply_markup=kb_confirm("appr", pid))

@router.message(F.text.regexp(r"^/reject\s+(\d+)$"))
async def cmd_reject(m: Message, regexp: re.Match):
    if not _admin_only(m): return
    pid = int(regexp.group(1))
    await m.answer(f"Отклонить заявку #{pid}?", reply_markup=kb_confirm("rej", pid))

# --- колбэки подтверждения ---
@router.callback_query(F.data.regexp(r"^adm:appr:(\d+)$"))
async def cb_appr(call: CallbackQuery, regexp: re.Match):
    if not _admin_only(call): 
        return await call.answer("Недостаточно прав", show_alert=True)
    pid = int(regexp.group(1))
    await call.message.edit_reply_markup(reply_markup=kb_confirm("appr", pid))
    await call.answer()

@router.callback_query(F.data.regexp(r"^adm:rej:(\d+)$"))
async def cb_rej(call: CallbackQuery, regexp: re.Match):
    if not _admin_only(call): 
        return await call.answer("Недостаточно прав", show_alert=True)
    pid = int(regexp.group(1))
    await call.message.edit_reply_markup(reply_markup=kb_confirm("rej", pid))
    await call.answer()

@router.callback_query(F.data.regexp(r"^adm:cancel:(\d+)$"))
async def cb_cancel(call: CallbackQuery, regexp: re.Match):
    if not _admin_only(call): 
        return await call.answer("Недостаточно прав", show_alert=True)
    pid = int(regexp.group(1))
    await call.message.edit_reply_markup(reply_markup=kb_proof_actions(pid))
    await call.answer("Отменено")

@router.callback_query(F.data.regexp(r"^adm:ok:(appr|rej):(\d+)$"))
async def cb_ok(call: CallbackQuery, regexp: re.Match):
    if not _admin_only(call): 
        return await call.answer("Недостаточно прав", show_alert=True)
    action = regexp.group(1)
    pid = int(regexp.group(2))

    if action == "appr":
        st, resp = await admin_approve(pid)
        if st == 200 and (resp or {}).get("ok"):
            await call.message.edit_reply_markup(reply_markup=None)
            await call.message.reply(f"✅ Зачтено #{pid}: {resp.get('progress')}")
            return await call.answer("Готово")
        else:
            return await call.answer("Ошибка при зачёте", show_alert=True)
    else:
        st, resp = await admin_reject(pid)
        if st == 200 and (resp or {}).get("ok"):
            await call.message.edit_reply_markup(reply_markup=None)
            await call.message.reply(f"❌ Отклонено #{pid}")
            return await call.answer("Готово")
        else:
            return await call.answer("Ошибка при отклонении", show_alert=True)