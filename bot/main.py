# bot/main.py
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from .config import BOT_TOKEN, get_http, HTTP
from .handlers import registration, captain, common, admin as admin_handlers
from .admin_watcher import ADMIN_WATCHER


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.info("Starting aiogram polling...")

    bot = Bot(BOT_TOKEN, parse_mode="Markdown")

    # снятие вебхука и очистка очереди апдейтов
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_routers(
        registration.router,
        captain.router,
        common.router,
        admin_handlers.router,  # админ-обработчики (кнопки «зачесть/отклонить», /pending и т.п.)
    )

    # открыть общую HTTP-сессию заранее (для api_client)
    await get_http()

    # запустить фоновый вотчер админ-заявок (шлёт карточки в ADMIN_CHAT_ID)
    ADMIN_WATCHER.start(bot)

    try:
        await dp.start_polling(bot, polling_timeout=30)
    finally:
        # аккуратно закрыть HTTP-сессию, если открыта
        try:
            if HTTP and not HTTP.closed:
                await HTTP.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())