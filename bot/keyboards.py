from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from .config import WEBAPP_URL

def kb_request_phone() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отправить телефон", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )

# NEW: общий минимальный набор
def kb_main() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Статус"), KeyboardButton(text="Поддержка")],
        ],
        resize_keyboard=True
    )

def kb_captain_main() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Статус"), KeyboardButton(text="Поддержка")],
        ],
        resize_keyboard=True
    )

def ib_leaderboard(url: str | None = None) -> InlineKeyboardMarkup:
    link = url or WEBAPP_URL
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Лидерборд (WebApp)", url=link)]
        ]
    )
