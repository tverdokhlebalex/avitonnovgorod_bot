from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)

def kb_request_phone() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отправить телефон", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )

def kb_captain_main() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Статус"), KeyboardButton(text="Лидерборд")],
            [KeyboardButton(text="Помощь")],
        ],
        resize_keyboard=True
    )

def ib_leaderboard(url: str | None = None) -> InlineKeyboardMarkup:
    row = []
    if url:
        row.append(InlineKeyboardButton(text="Лидерборд (WebApp)", url=url))
    return InlineKeyboardMarkup(inline_keyboard=[row] if row else [[]])
