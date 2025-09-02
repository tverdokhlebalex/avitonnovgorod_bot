from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
)

def kb_request_phone() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отправить телефон", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )

def kb_webapp(url: str) -> ReplyKeyboardMarkup:
    # постоянная кнопка на мини-приложение
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Лидерборд", web_app=WebAppInfo(url=url))]],
        resize_keyboard=True
    )

def ib_webapp(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Открыть мини-приложение", web_app=WebAppInfo(url=url))]]
    )

def kb_confirm_start() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Стартовать")]],
        resize_keyboard=True, one_time_keyboard=True
    )