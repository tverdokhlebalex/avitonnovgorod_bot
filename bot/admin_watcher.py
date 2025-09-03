# bot/admin_watcher.py
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

    ВАЖНО:
    - Перед закрытием общей HTTP-сессии (aiohttp) нужно остановить watcher: await ADMIN_WATCHER.stop()
      Иначе возможны предупреждения "Unclosed client session".
    - Дедупликация сделана по КЛЮЧУ ВЕРСИИ, а не по одному только proof.id:
      ключ = f"{id}:{updated_at or created_at}:{photo_file_id}".
      Это гарантирует повторную отправку карточки после REJECT -> новое фото -> PENDING.
    """

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._seen: set[str] = set()  # ключи версий карточек
        self._stopping = False

    # ---------- public API ----------

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

    # ---------- internals ----------

    @staticmethod
    def _version_key(item: dict) -> Optional[str]:
        """
        Формирует версионный ключ для дедупликации.
        Приоритет полей:
          - id (обязателен)
          - updated_at (если есть) иначе created_at
          - photo_file_id (на случай отсутствия updated_at в модели)
        """
        try:
            pid = int(item.get("id"))
        except Exception:
            return None

        # то, что должно меняться при ре-модерации
        updated = item.get("updated_at") or item.get("created_at") or ""
        file_id = item.get("photo_file_id") or ""
        return f"{pid}:{updated}:{file_id}"

    async def _loop(self, bot: Bot) -> None:
        backoff = 1.0
        chat_id = int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID is not None else None

        try:
            while not self._stopping:
                # даём шанс отмене
                await asyncio.sleep(0)

                try:
                    st, items = await admin_pending()
                except Exception as e:
                    logging.warning("AdminWatcher: /pending request failed: %r", e)
                    await asyncio.sleep(min(backoff, 15.0))
                    backoff = min(backoff * 2.0, 60.0)
                    continue

                if st == 200 and isinstance(items, list):
                    for p in items:
                        key = self._version_key(p)
                        if not key:
                            continue
                        if key in self._seen:
                            continue

                        try:
                            # _send_proof_card может ничего не возвращать — считаем, что ОК, если исключений нет
                            ok = await _send_proof_card(bot, chat_id, p)
                        except Exception:
                            logging.exception("AdminWatcher: send_proof_card failed for proof %r", p)
                            ok = False

                        # Если отправка не удалась явно (ok is False) — не помечаем как seen.
                        if ok is not False:
                            self._seen.add(key)

                    # Периодическая уборка, чтобы set не рос бесконечно.
                    if len(self._seen) > 10000:
                        # Обрезаем примерно до последних ~4000 ключей.
                        self._seen = set(list(self._seen)[-4000:])

                    backoff = 1.0
                else:
                    logging.warning("AdminWatcher: bad /pending response %s %r", st, items)

                await asyncio.sleep(max(1.0, float(ADMIN_POLL_SECONDS or 2.0)))
        except asyncio.CancelledError:
            # Нормальная остановка
            raise
        except Exception as e:
            logging.exception("AdminWatcher crashed: %r", e)
        finally:
            logging.info("AdminWatcher: loop finished.")


ADMIN_WATCHER = AdminWatcher()