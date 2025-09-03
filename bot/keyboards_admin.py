# bot/keyboards_admin.py
from __future__ import annotations

from typing import Literal, Optional
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

Action = Literal["appr", "rej"]


def _pack(*parts: str | int | None) -> str:
    """
    Собираем callback_data вида 'adm:appr:<pid>:<cap>:<team>'.
    None -> '0'. Следим за компактностью (лимит Telegram 64 байта).
    """
    out: list[str] = []
    for p in parts:
        out.append("0" if p is None else str(p))
    return ":".join(out)


def kb_proof_actions(
    pid: int,
    *,
    captain_tg_id: Optional[str] = None,
    team_id: Optional[int] = None,
) -> InlineKeyboardMarkup:
    """
    Кнопки на карточке модерации.
    Новый формат callback_data:
      - adm:appr:<pid>:<cap>:<team>
      - adm:rej:<pid>:<cap>:<team>
    (старый формат без cap/team поддержан в хендлерах)
    """
    b = InlineKeyboardBuilder()
    b.button(text="✅ Зачесть",   callback_data=_pack("adm", "appr", pid, captain_tg_id, team_id))
    b.button(text="❌ Отклонить", callback_data=_pack("adm", "rej",  pid, captain_tg_id, team_id))
    b.adjust(2)
    return b.as_markup()


def kb_confirm(
    action: Action,
    pid: int,
    captain_tg_id: Optional[str] = None,
    team_id: Optional[int] = None,
) -> InlineKeyboardMarkup:
    """
    Подтверждение действия:
      - adm:ok:<action>:<pid>:<cap>:<team>
      - adm:cancel:<pid>
    """
    b = InlineKeyboardBuilder()
    b.button(text="Да, подтвердить", callback_data=_pack("adm", "ok", action, pid, captain_tg_id, team_id))
    b.button(text="Отмена",          callback_data=_pack("adm", "cancel", pid))
    b.adjust(1, 1)
    return b.as_markup()