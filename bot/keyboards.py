# bot/keyboards.py
from typing import Optional
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
)


def kb_request_phone() -> ReplyKeyboardMarkup:
    """Кнопка запроса телефона (контакта)"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Отправить телефон", request_contact=True)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )


def kb_confirm_start() -> ReplyKeyboardMarkup:
    """Одна кнопка «Стартовать» для подтверждения старта капитаном"""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Стартовать")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )


def _is_https(url: Optional[str]) -> bool:
    return bool(url and url.lower().startswith("https://"))


def ib_webapp(url: Optional[str]) -> Optional[InlineKeyboardMarkup]:
    """
    Inline-кнопка WebApp. Возвращает клавиатуру только для https:// URL.
    Иначе — None (нельзя отдавать http:// или локальные хосты в Telegram).
    """
    if not _is_https(url):
        return None
    btn = InlineKeyboardButton(text="Открыть мини-приложение", web_app=WebAppInfo(url=url))  # type: ignore[arg-type]
    return InlineKeyboardMarkup(inline_keyboard=[[btn]])


# Совместимость с вашим кодом, где встречался import kb_webapp
def kb_webapp(url: Optional[str]) -> Optional[InlineKeyboardMarkup]:
    return ib_webapp(url)