# bot/watchers.py
import asyncio
import logging
from aiogram import Bot
from aiohttp import ClientError

from .api_client import current_checkpoint, roster_by_tg
from .texts import FINISH_MSG, format_task_card

POLL_SECONDS = 4

class _State:
    def __init__(self, team_id: int, tg_id: int | str, bot: Bot):
        self.team_id = team_id
        self.tg_id = str(tg_id)
        self.bot = bot
        self.last_cp_id: int | None = None
        self.finished_sent = False

class Watchers:
    def __init__(self):
        self._tasks: dict[int, asyncio.Task] = {}
        self._states: dict[int, _State] = {}

    def start(self, team_id: int, chat_id: int, tg_id: int | str, bot: Bot):
        # один цикл на команду: если был — отменяем и запускаем заново
        t = self._tasks.get(team_id)
        if t and not t.done():
            t.cancel()
        st = _State(team_id, tg_id, bot)
        self._states[team_id] = st
        self._tasks[team_id] = asyncio.create_task(self._loop(st))

    async def _broadcast(self, tg_id: str, text: str, bot: Bot, *, markdown: bool = True):
        parse_mode = "Markdown" if markdown else None
        try:
            st, roster = await roster_by_tg(tg_id)
        except Exception:
            logging.exception("watcher: roster_by_tg failed")
            roster = None
            st = 0

        if st != 200 or not roster:
            # fallback — хотя бы капитану
            try:
                await bot.send_message(int(tg_id), text, parse_mode=parse_mode)
            except Exception:
                pass
            return

        sent = set()
        for m in (roster.get("members") or []):
            uid = m.get("tg_id")
            if not uid or uid in sent:
                continue
            try:
                await bot.send_message(int(uid), text, parse_mode=parse_mode)
                sent.add(uid)
            except Exception:
                pass

    async def _loop(self, st: _State):
        backoff = 1
        try:
            # Сразу пробуем прислать текущее задание ровно ОДИН раз
            code, data = await current_checkpoint(st.tg_id)
            if code == 200 and isinstance(data, dict) and not data.get("finished"):
                cp = data.get("checkpoint") or {}
                if cp.get("id"):
                    st.last_cp_id = cp["id"]
                    await self._broadcast(st.tg_id, format_task_card(cp), st.bot, markdown=True)

            while True:
                await asyncio.sleep(POLL_SECONDS)
                try:
                    code, data = await current_checkpoint(st.tg_id)
                except (ClientError, asyncio.TimeoutError) as e:
                    logging.warning("watcher: network error (%r), retrying…", e)
                    await asyncio.sleep(min(backoff, 10))
                    backoff = min(backoff * 2, 30)
                    continue

                backoff = 1
                if code != 200 or not isinstance(data, dict):
                    continue

                if data.get("finished"):
                    if not st.finished_sent:
                        await self._broadcast(st.tg_id, FINISH_MSG.format(team="ваша команда"), st.bot, markdown=True)
                        st.finished_sent = True
                    break

                cp = (data or {}).get("checkpoint") or {}
                cp_id = cp.get("id")
                if cp_id and cp_id != st.last_cp_id:
                    await self._broadcast(st.tg_id, format_task_card(cp), st.bot, markdown=True)
                    st.last_cp_id = cp_id

        except asyncio.CancelledError:
            pass
        except Exception:
            logging.exception("watcher loop error (team %s)", st.team_id)

WATCHERS = Watchers()