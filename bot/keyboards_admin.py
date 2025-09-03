# keyboards_admin.py
from typing import Literal
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

Action = Literal["appr", "rej"]

def kb_proof_actions(pid: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Зачесть",   callback_data=f"adm:appr:{pid}")
    b.button(text="❌ Отклонить", callback_data=f"adm:rej:{pid}")
    b.adjust(2)  # в ряд
    return b.as_markup()

def kb_confirm(action: Action, pid: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Да, подтвердить", callback_data=f"adm:ok:{action}:{pid}")
    b.button(text="Отмена",          callback_data=f"adm:cancel:{pid}")
    b.adjust(1, 1)  # подтверждение отдельной строкой от отмены
    return b.as_markup()

def kb_after_decision(approved: bool) -> InlineKeyboardMarkup:
    # чтобы “зафиксировать” сообщение после решения и исключить повторные клики
    text = "✅ Зачтено" if approved else "❌ Отклонено"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data="adm:noop")]
    ])