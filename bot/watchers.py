# bot/watchers.py
import asyncio
import logging
from typing import Dict

from aiogram import Bot
from aiohttp import ClientError
from .api_client import current_checkpoint, roster_by_tg
from .texts import FINISH_MSG, format_task_card

POLL_SECONDS = 5

class _WatcherState:
    def __init__(self, team_id, tg_id, bot):
        self.team_id = team_id
        self.tg_id = str(tg_id)
        self.bot = bot
        self.last_cp_id = None
        self.finished_sent = False

class _Watchers:
    def __init__(self):
        self._tasks = {}  # team_id -> asyncio.Task
        self._states = {} # team_id -> _WatcherState

    def start(self, team_id: int, chat_id: int, tg_id: int | str, bot):
        if team_id in self._tasks and not self._tasks[team_id].done():
            return  # уже запущен
        st = _WatcherState(team_id, tg_id, bot)
        self._states[team_id] = st
        self._tasks[team_id] = asyncio.create_task(self._loop(st))

    async def _broadcast_to_team(self, tg_id: str, text: str, bot, *, markdown=True):
        try:
            st, roster = await roster_by_tg(tg_id)
        except Exception:
            logging.exception("watcher: roster_by_tg failed")
            return
        parse_mode = "Markdown" if markdown else None
        if st != 200 or not roster:
            # если не удалось — пошлём хотя бы капитану
            try:
                await bot.send_message(int(tg_id), text, parse_mode=parse_mode)
            except Exception:
                pass
            return
        sent = set()
        for mem in (roster.get("members") or []):
            uid = mem.get("tg_id")
            if not uid or uid in sent:
                continue
            try:
                await bot.send_message(int(uid), text, parse_mode=parse_mode)
                sent.add(uid)
            except Exception:
                pass

    async def _loop(self, st: _WatcherState):
        backoff = 1
        while True:
            try:
                code, data = await current_checkpoint(st.tg_id)
                if code != 200:
                    await asyncio.sleep(2)
                    continue

                if data.get("finished"):
                    if not st.finished_sent:
                        await self._broadcast_to_team(st.tg_id, "🏁 Финиш! Вы прошли маршрут. Поздравляем!", st.bot, markdown=False)
                        st.finished_sent = True
                    await asyncio.sleep(5)
                    continue

                cp = (data or {}).get("checkpoint") or {}
                cp_id = cp.get("id")
                if cp_id and cp_id != st.last_cp_id:
                    # отправляем карточку 1 раз при входе на точку
                    await self._broadcast_to_team(st.tg_id, format_task_card(cp), st.bot, markdown=True)
                    st.last_cp_id = cp_id

                backoff = 1
                await asyncio.sleep(3)

            except (ClientError, asyncio.TimeoutError):
                # сетевой сбой — не паникуем, ждём и пробуем снова
                logging.warning("watcher: network error, retrying soon")
                await asyncio.sleep(min(backoff, 10))
                backoff = min(backoff * 2, 30)
            except Exception:
                logging.exception("watcher loop error (team %s)", st.team_id)
                await asyncio.sleep(3)

WATCHERS = _Watchers()

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