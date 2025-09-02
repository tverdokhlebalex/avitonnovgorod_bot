# bot/main.py
import asyncio
import logging
import sys
import pathlib

# --- гибкий импорт: работает и как модуль, и как скрипт ---
if __package__ in (None, ""):
    # запущен как /code/bot/main.py -> добавим корень проекта в sys.path
    ROOT = pathlib.Path(__file__).resolve().parents[1]  # /code
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    # импортируем абсолютными путями
    from bot.config import BOT_TOKEN, get_http, HTTP
    from bot.handlers import registration, captain, common
else:
    # запущен как модуль: python -m bot.main
    from .config import BOT_TOKEN, get_http, HTTP
    from .handlers import registration, captain, common

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage


async def main():
    logging.info("Starting aiogram polling...")
    bot = Bot(BOT_TOKEN, parse_mode="Markdown")

    # на всякий случай снимаем вебхук
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_routers(
        registration.router,
        captain.router,
        common.router,
    )

    # открыть HTTP-сессию заранее
    await get_http()
    try:
        await dp.start_polling(bot, polling_timeout=30, drop_pending_updates=True)
    finally:
        try:
            if HTTP and not HTTP.closed:
                await HTTP.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
