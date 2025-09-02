from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
)
from .config import build_webapp_url

def kb_user_main() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Статус"), KeyboardButton(text="Поддержка")]],
        resize_keyboard=True
    )

def kb_request_phone() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отправить телефон", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )

def ib_leaderboard(tg_id: int | str) -> InlineKeyboardMarkup:
    # Откроется именно Telegram WebApp
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Лидерборд", web_app=WebAppInfo(url=build_webapp_url(tg_id)))
    ]])

def ib_start_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Стартуем!", callback_data="start_yes")],
        [InlineKeyboardButton(text="Ещё минутку", callback_data="start_no")],
    ])