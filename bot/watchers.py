import asyncio, logging
from aiogram import Bot
from typing import Dict
from .api_client import current_checkpoint
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

    async def _loop(self, team_id: int, chat_id: int, tg_id: int | str, bot: Bot):
        last_order = None
        try:
            # первый чек сразу (если уже есть задание — пришлём)
            st, cur = await current_checkpoint(tg_id)
            if st == 200 and not cur.get("finished"):
                cp = cur["checkpoint"]
                last_order = cp["order_num"]
                await self._send_task(bot, chat_id, cp)
            while True:
                await asyncio.sleep(POLL_SECONDS)
                st, cur = await current_checkpoint(tg_id)
                if st != 200:
                    continue
                if cur.get("finished"):
                    await bot.send_message(chat_id, FINISH_MSG.format(team="ваша команда"))
                    break
                cp = cur["checkpoint"]
                if last_order is None or cp["order_num"] != last_order:
                    last_order = cp["order_num"]
                    await self._send_task(bot, chat_id, cp)
        except asyncio.CancelledError:
            pass
        except Exception:
            logging.exception("watcher loop error (team %s)", team_id)

    async def _send_task(self, bot: Bot, chat_id: int, cp: dict):
        total = cp.get("total") or "?"
        num = cp.get("order_num") or "?"
        title = (cp.get("title") or "").strip()
        riddle = (cp.get("riddle") or "").strip()
        hint = cp.get("photo_hint") or "Вся команда + деталь локации."
        txt = (f"*Задание {num}/{total} — {title}*\n\n{riddle}\n\n"
               f"_Рекомендация к фото:_ {hint}")
        await bot.send_message(chat_id, txt, parse_mode="Markdown")

WATCHERS = WatcherManager()
