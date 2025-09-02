# bot/watchers.py
import asyncio
import logging
from typing import Dict

from aiogram import Bot

from .api_client import current_checkpoint, roster_by_tg
from .texts import FINISH_MSG

POLL_SECONDS = 5


class WatcherManager:
    def __init__(self):
        self._tasks: Dict[int, asyncio.Task] = {}  # team_id -> Task

    def running(self, team_id: int) -> bool:
        return team_id in self._tasks and not self._tasks[team_id].done()

    def cancel(self, team_id: int) -> None:
        t = self._tasks.get(team_id)
        if t and not t.done():
            t.cancel()

    def start(self, *, team_id: int, chat_id: int, tg_id: int | str, bot: Bot):
        # один вотчер на команду
        self.cancel(team_id)
        self._tasks[team_id] = asyncio.create_task(self._loop(team_id, chat_id, tg_id, bot))

    async def _broadcast(self, bot: Bot, tg_id: int | str, text: str, parse_mode: str | None = "Markdown"):
        """Разошлём сообщение всем участникам команды, чей tg_id известен."""
        try:
            st, roster = await roster_by_tg(tg_id)
            if st == 200 and roster and isinstance(roster.get("members"), list):
                sent = set()
                for mem in roster["members"]:
                    uid = mem.get("tg_id")
                    if not uid or uid in sent:
                        continue
                    try:
                        await bot.send_message(uid, text, parse_mode=parse_mode)
                        sent.add(uid)
                    except Exception:
                        pass
                return
        except Exception:
            logging.exception("watcher broadcast failed")
        # fallback — если не удалось получить состав, ничего не делаем (капитану уже ушло раньше)

    async def _loop(self, team_id: int, chat_id: int, tg_id: int | str, bot: Bot):
        last_order = None
        try:
            # первый чек сразу (если уже есть задание — пришлём)
            st, cur = await current_checkpoint(tg_id)
            if st == 200 and not cur.get("finished"):
                cp = cur["checkpoint"]
                last_order = cp["order_num"]
                await self._send_task(bot, tg_id, cp)  # сразу всем
            while True:
                await asyncio.sleep(POLL_SECONDS)
                st, cur = await current_checkpoint(tg_id)
                if st != 200:
                    continue
                if cur.get("finished"):
                    await self._broadcast(bot, tg_id, FINISH_MSG.format(team="ваша команда"))
                    break
                cp = cur["checkpoint"]
                if last_order is None or cp["order_num"] != last_order:
                    last_order = cp["order_num"]
                    await self._send_task(bot, tg_id, cp)
        except asyncio.CancelledError:
            pass
        except Exception:
            logging.exception("watcher loop error (team %s)", team_id)

    async def _send_task(self, bot: Bot, tg_id: int | str, cp: dict):
        total = cp.get("total") or "?"
        num = cp.get("order_num") or "?"
        title = (cp.get("title") or "").strip()
        riddle = (cp.get("riddle") or "").strip()
        hint = cp.get("photo_hint") or "Вся команда + деталь локации."
        txt = (f"*Задание {num}/{total} — {title}*\n\n{riddle}\n\n"
               f"_Рекомендация к фото:_ {hint}")
        await self._broadcast(bot, tg_id, txt, parse_mode="Markdown")


WATCHERS = WatcherManager()