from __future__ import annotations

import asyncio
import logging
from typing import Optional

from aiogram import Bot

from .config import ADMIN_CHAT_ID, ADMIN_POLL_SECONDS
from .api_client import admin_pending
from .handlers.admin import _send_proof_card


class AdminWatcher:
    """
    Пуллит /api/admin/proofs/pending и постит карточки в ADMIN_CHAT_ID.
    ВАЖНО: перед закрытием HTTP-сессии нужно остановить watcher (stop()).
    """

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._seen: set[int] = set()
        self._stopping = False

    def start(self, bot: Bot) -> None:
        if not ADMIN_CHAT_ID:
            logging.info("AdminWatcher: ADMIN_CHAT_ID not set — watcher disabled.")
            return
        if self._task and not self._task.done():
            return
        self._stopping = False
        self._task = asyncio.create_task(self._loop(bot), name="admin_watcher")

    async def stop(self) -> None:
        """Аккуратно останавливаем фоновую задачу и ждём её завершения."""
        self._stopping = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _loop(self, bot: Bot) -> None:
        backoff = 1.0
        try:
            while True:
                # даём шанc отмене прилететь ещё до сетевых операций
                await asyncio.sleep(0)

                st, items = await admin_pending()
                if st == 200 and isinstance(items, list):
                    for p in items:
                        try:
                            pid = int(p["id"])
                        except Exception:
                            continue
                        if pid in self._seen:
                            continue

                        try:
                            ok = await _send_proof_card(bot, int(ADMIN_CHAT_ID), p)
                        except Exception:
                            logging.exception("AdminWatcher: send_proof_card failed for proof %r", p)
                            ok = False

                        # Если отправка не удалась — не помечаем как seen (будет повтор)
                        if ok is not False:
                            self._seen.add(pid)

                    # периодическая уборка, чтобы set не разрастался бесконечно
                    if len(self._seen) > 5000:
                        self._seen = set(list(self._seen)[-2000:])

                    backoff = 1.0
                else:
                    logging.warning("AdminWatcher: bad /pending response %s %r", st, items)

                await asyncio.sleep(max(1.0, float(ADMIN_POLL_SECONDS)))
        except asyncio.CancelledError:
            # Нормальная остановка
            raise
        except Exception as e:
            logging.exception("AdminWatcher crashed: %r", e)
        finally:
            logging.info("AdminWatcher: loop finished.")