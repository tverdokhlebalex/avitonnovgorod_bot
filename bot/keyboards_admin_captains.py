# bot/keyboards_admin_captains.py
from __future__ import annotations
from typing import Iterable, Optional
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

def kb_team_search_results(teams: Iterable[dict]) -> InlineKeyboardMarkup:
    """
    teams: [{team_id, team_name, started_at?}, ...]
    """
    b = InlineKeyboardBuilder()
    for t in teams:
        tid = t.get("team_id")
        name = (t.get("team_name") or f"ID {tid}").strip()
        started = " • ▶️" if t.get("started_at") else ""
        b.button(text=f"{name}{started}", callback_data=f"capn:pick:{tid}")
    b.adjust(1)
    return b.as_markup()

def kb_roster_set_captain(team_id: int, members: Iterable[dict]) -> InlineKeyboardMarkup:
    """
    members: iterable of dicts: user_id, first_name, last_name, role
    """
    b = InlineKeyboardBuilder()
    for m in members:
        uid = int(m.get("user_id"))
        fn = (m.get("first_name") or "").strip()
        ln = (m.get("last_name") or "").strip()
        name = (fn or ln or f"ID {uid}").strip()
        is_cap = (m.get("role") or "").upper() == "CAPTAIN"
        prefix = "👑 " if is_cap else ""
        b.button(text=f"{prefix}{name}", callback_data=f"capn:ask:{team_id}:{uid}")
    b.adjust(1)
    return b.as_markup()

def kb_confirm_set_captain(team_id: int, user_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Подтвердить", callback_data=f"capn:ok:{team_id}:{user_id}")
    b.button(text="↩️ Отмена",      callback_data=f"capn:cancel:{team_id}")
    b.adjust(1, 1)
    return b.as_markup()