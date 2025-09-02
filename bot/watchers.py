import asyncio, logging
from aiogram import Bot
from typing import Dict, List
from .api_client import current_checkpoint, roster_by_tg
from .texts import FINISH_MSG, APPROVED_MSG

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

    async def _notify_all(self, bot: Bot, captain_tg_id: int | str, text: str, parse_md: bool = True):
        # получим состав по tg капитана и разошлём всем
        st, roster = await roster_by_tg(captain_tg_id)
        if st != 200 or not roster:  # fallback — только капитану
            await bot.send_message(captain_tg_id, text, parse_mode="Markdown" if parse_md else None)
            return
        sent: List[int] = []
        for m in (roster.get("members") or []):
            tg = m.get("tg_id")
            if not tg or tg in sent:
                continue
            try:
                await bot.send_message(tg, text, parse_mode="Markdown" if parse_md else None)
                sent.append(tg)
            except Exception:
                logging.exception("notify_all: failed to DM %s", tg)

    async def _loop(self, team_id: int, chat_id: int, tg_id: int | str, bot: Bot):
        last_order = None
        try:
            # первый чек сразу (если уже есть задание — пришлём)
            st, cur = await current_checkpoint(tg_id)
            if st == 200 and not cur.get("finished"):
                cp = cur["checkpoint"]
                last_order = cp["order_num"]
                await self._send_task(bot, tg_id, cp)
            while True:
                await asyncio.sleep(POLL_SECONDS)
                st, cur = await current_checkpoint(tg_id)
                if st != 200:
                    continue
                if cur.get("finished"):
                    # финал всем участникам
                    await self._notify_all(
                        bot, tg_id,
                        FINISH_MSG.format(team="ваша команда")
                    )
                    break
                cp = cur["checkpoint"]
                if last_order is None:
                    last_order = cp["order_num"]
                    await self._send_task(bot, tg_id, cp)
                    continue
                if cp["order_num"] != last_order:
                    # предыдущая принята
                    prev = last_order
                    last_order = cp["order_num"]
                    await self._notify_all(bot, tg_id, APPROVED_MSG.format(num=prev))
                    await self._send_task(bot, tg_id, cp)
        except asyncio.CancelledError:
            pass
        except Exception:
            logging.exception("watcher loop error (team %s)", team_id)

    async def _send_task(self, bot: Bot, captain_tg_id: int | str, cp: dict):
        total = cp.get("total") or "?"
        num = cp.get("order_num") or "?"
        title = (cp.get("title") or "").strip()
        riddle = (cp.get("riddle") or "").strip()
        hint = cp.get("photo_hint") or "Вся команда + деталь локации."
        txt = (f"*Задание {num}/{total} — {title}*\n\n{riddle}\n\n"
               f"_Рекомендация к фото:_ {hint}")
        await self._notify_all(bot, captain_tg_id, txt)

WATCHERS = WatcherManager()