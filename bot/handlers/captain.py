from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.enums import ContentType
from ..api_client import team_by_tg, team_rename, start_game, submit_photo, current_checkpoint
from ..states import PhotoStates, CaptainStates
from ..watchers import WATCHERS
from ..utils import format_roster
from ..texts import RULES_SHORT
from ..keyboards import ib_start_confirm  # ← NEW

router = Router()

async def _ensure_captain(m: Message) -> tuple[bool, dict | None]:
    st, info = await team_by_tg(m.from_user.id)
    if st != 200 or not info:
        await m.answer("Ты не в команде. Набери /reg.")
        return False, None
    if not info.get("is_captain"):
        await m.answer("Эта команда уже имеет капитана. Со мной общается только капитан.")
        return False, info
    return True, info

async def _start_and_watch(m: Message, team_id: int):
    WATCHERS.start(team_id=team_id, chat_id=m.chat.id, tg_id=m.from_user.id, bot=m.bot)
    st, cur = await current_checkpoint(m.from_user.id)
    if st == 200 and not cur.get("finished"):
        cp = cur["checkpoint"]
        await m.answer(
            f"*Задание {cp['order_num']}/{cp.get('total','?')} — {cp.get('title','')}*\n\n{cp.get('riddle','')}",
            parse_mode="Markdown"
        )

@router.message(CaptainStates.waiting_team_name, F.text)
async def captain_name_from_state(m: Message, state: FSMContext):
    ok, _ = await _ensure_captain(m)
    if not ok:
        return await state.clear()

    new_name = (m.text or "").strip()
    if len(new_name) < 2:
        return await m.answer("Название слишком короткое. Ещё раз:")

    st, resp = await team_rename(m.from_user.id, new_name)
    if st == 200 and resp.get("ok"):
        await state.clear()
        await m.answer(f"Готово! Новое имя команды: *{resp.get('team_name')}*.", parse_mode="Markdown")
        # инструкция без кнопок
        await m.answer(RULES_SHORT, parse_mode="Markdown")
        # ← теперь спрашиваем подтверждение, НО НЕ стартуем сами
        await m.answer("Готовы стартовать?", reply_markup=ib_start_confirm())
    else:
        await m.answer(resp.get("detail") or "Переименование недоступно. Введите другое имя:")

# Фолбек: капитан может просто прислать имя без /rename
@router.message(F.text & ~F.text.regexp(r"^/"))
async def captain_name_fallback(m: Message, state: FSMContext):
    ok, info = await _ensure_captain(m)
    if not ok or not info:
        return
    # Разрешаем ввод названия, пока команда не стартовала
    st, cur = await current_checkpoint(m.from_user.id)
    if st == 200:   # уже стартовали — игнор
        return
    await captain_name_from_state(m, state)

@router.callback_query(F.data == "start_yes")
async def on_start_yes(c: CallbackQuery):
    # проверим, что жмёт именно капитан
    st, info = await team_by_tg(c.from_user.id)
    if st != 200 or not info or not info.get("is_captain"):
        return await c.answer("Только капитан может стартовать", show_alert=True)

    st2, resp = await start_game(c.from_user.id)
    await c.answer()
    if st2 == 200:
        await c.message.answer("🚀 Квест начат!")
        # отправим первое задание сразу
        class _Msg:  # небольшой адаптер, чтобы использовать _start_and_watch
            def __init__(self, c): self.chat=c.message.chat; self.bot=c.bot; self.from_user=c.from_user
            async def answer(self, *a, **kw): return await c.message.answer(*a, **kw)
        await _start_and_watch(_Msg(c), info["team_id"])
    else:
        await c.message.answer(resp.get("detail") or "Старт недоступен.")

@router.callback_query(F.data == "start_no")
async def on_start_no(c: CallbackQuery):
    await c.answer("Ок, нажмите «Стартуем!» когда будете готовы.")
    await c.message.answer("Хорошо, не спешим. Когда команда соберётся — жмите кнопку «Стартуем!» или команду /startquest.")