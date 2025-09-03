# bot/main.py
import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from .config import BOT_TOKEN, get_http, HTTP
from .handlers import registration, captain, common, admin as admin_handlers
from .admin_watcher import ADMIN_WATCHER


async def main() -> None:
    # базовое логирование
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    log = logging.getLogger("bot.main")
    log.info("Starting aiogram polling...")

    bot = Bot(BOT_TOKEN, parse_mode="Markdown")

    # убираем вебхук и чистим очередь апдейтов
    with suppress(Exception):
        await bot.delete_webhook(drop_pending_updates=True)

    # регистрируем роутеры
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_routers(
        registration.router,
        captain.router,
        common.router,
        admin_handlers.router,   # обработчики админ-кнопок
    )

    # открываем общую HTTP-сессию заранее (её закроем в finally)
    await get_http()

    # стартуем фонового вотчера админ-заявок (шлёт карточки в ADMIN_CHAT_ID)
    ADMIN_WATCHER.start(bot)

    try:
        # drop_pending_updates уже сделали при delete_webhook
        await dp.start_polling(bot, polling_timeout=30)
    finally:
        # останавливаем вотчер, чтобы не висел и не использовал HTTP после закрытия
        task = getattr(ADMIN_WATCHER, "_task", None)
        if task and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

        # закрываем общую HTTP-сессию (если есть)
        try:
            if HTTP and not HTTP.closed:
                await HTTP.close()
        except Exception:
            log.exception("Failed to close shared HTTP session")

        # закрываем сессию бота (aiohttp внутри aiogram)
        with suppress(Exception):
            await bot.session.close()

        log.info("Bot shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())