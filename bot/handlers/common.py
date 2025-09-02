from aiogram import Router, F
from aiogram.types import Message
from ..api_client import roster_by_tg, leaderboard, team_by_tg
from ..utils import format_roster
from ..keyboards import ib_leaderboard
from ..texts import HELP_CONTACTS

router = Router()

@router.message(F.text == "/team")
async def cmd_team(m: Message):
    st, r = await roster_by_tg(m.from_user.id)
    if st != 200 or not r:
        return await m.answer("Ты ещё не зарегистрирован. Набери /reg.")
    await m.answer(format_roster(r), parse_mode="Markdown")

@router.message(F.text.in_({"/lb","/leaderboard","Лидерборд"}))
async def cmd_lb(m: Message):
    # просто покажем WebApp-кнопку
    await m.answer(".", reply_markup=ib_leaderboard(m.from_user.id))

@router.message(F.text.in_({"Статус"}))
async def cmd_status(m: Message):
    st_t, info = await team_by_tg(m.from_user.id)
    if st_t != 200:
        return await m.answer("Ты ещё не зарегистрирован. /reg")
    st, rows = await leaderboard()
    done, total, place = 0, 0, "—"
    if st == 200 and isinstance(rows, list):
        for idx, r in enumerate(rows, 1):
            if r.get("team_id") == info["team_id"]:
                done, total = r.get("tasks_done", 0), r.get("total_tasks", 0)
                place = str(idx)
                break
    await m.answer(f"Статус: {done}/{total}\nЛидерборд: {place} место.")

@router.message(F.text.in_({"Поддержка"}))
async def cmd_support(m: Message):
    await m.answer(HELP_CONTACTS.format(name="@usemefor", phone="+79890876902"))