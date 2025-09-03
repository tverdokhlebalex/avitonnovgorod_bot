import asyncio, logging, os
from aiogram import Bot
from .config import ADMIN_CHAT_ID, ADMIN_POLL_SECONDS
from .api_client import admin_pending
from .handlers.admin import _send_proof_card

class AdminWatcher:
    def __init__(self):
        self._task: asyncio.Task | None = None
        self._seen: set[int] = set()

    def start(self, bot: Bot):
        if not ADMIN_CHAT_ID:
            return
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(bot))

    async def _loop(self, bot: Bot):
        backoff = 1
        while True:
            try:
                st, items = await admin_pending()
                if st == 200 and isinstance(items, list):
                    for p in items:
                        pid = int(p["id"])
                        if pid in self._seen:
                            continue
                        await _send_proof_card(bot, ADMIN_CHAT_ID, p)
                        self._seen.add(pid)
                    backoff = 1
                await asyncio.sleep(ADMIN_POLL_SECONDS)
            except Exception as e:
                logging.warning("admin watcher error: %r", e)
                await asyncio.sleep(min(backoff, 15))
                backoff = min(backoff * 2, 60)

ADMIN_WATCHER = AdminWatcher()