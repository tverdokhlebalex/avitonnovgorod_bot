import os
import re
import sys
import csv
import json
import asyncio
import logging
from typing import Dict, Tuple, Optional, List, Any

import aiohttp
from aiogram import Bot, Dispatcher, Router, F
from aiogram.enums import ContentType
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
)
from aiogram.types.error_event import ErrorEvent

# --------------------
# Конфиг и логирование
# --------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN or not re.match(r"^\d+:[\w-]+$", BOT_TOKEN):
    logging.critical("BOT_TOKEN отсутствует или некорректен. Проверь .env / env_file.")
    sys.exit(1)

_api_base = os.getenv("API_BASE") or os.getenv("API_URL", "http://app:8000")
API_BASE = _api_base.rstrip("/")
APP_SECRET = os.getenv("APP_SECRET", "change-me-please")

# Строгий белый список
STRICT_WHITELIST = os.getenv("STRICT_WHITELIST", "true").lower() in ("1", "true", "yes", "y")

# Размер команды
TEAM_SIZE = int(os.getenv("TEAM_SIZE", "7"))

# WebApp URL (для Telegram нужен HTTPS; локально http + ?dev_tg=…)
WEBAPP_URL = (os.getenv("WEBAPP_URL") or f"{API_BASE}/webapp").strip()

# CSV с участниками
PARTICIPANTS_CSV = os.getenv("PARTICIPANTS_CSV", "/code/data/participants.csv")
PARTICIPANTS_CSV_FALLBACK = "/code/data/participants_template.csv"

# HTTP клиент
CLIENT_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=5, sock_connect=5, sock_read=10)
HTTP: Optional[aiohttp.ClientSession] = None

# --------------------
# Утилиты
# --------------------
def norm_phone(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"[^\d+]", "", s.strip())
    if s.startswith("8") and len(s) == 11:
        s = "+7" + s[1:]
    if s.isdigit() and len(s) == 11 and s[0] == "7":
        s = "+" + s
    return s


def parse_name_simple(text: str) -> Tuple[str, Optional[str]]:
    """
    Берём первое слово как имя, остальное — фамилия (опционально).
    """
    t = " ".join((text or "").replace(",", " ").replace(".", " ").split()).strip()
    if not t:
        return "", None
    parts = t.split()
    first = parts[0].title()
    last = " ".join(parts[1:]).title() if len(parts) > 1 else None
    return first, last


def api_url(path: str) -> str:
    return f"{API_BASE}{path}"


def headers_json() -> dict:
    return {"x-app-secret": APP_SECRET, "Content-Type": "application/json"}


def build_webapp_url(tg_id: int | str) -> str:
    """
    Для полноценного Telegram WebApp нужен публичный HTTPS.
    Локально (http/localhost/127.0.0.1) — добавляем ?dev_tg=… для dev-режима.
    """
    url = WEBAPP_URL
    low = url.lower()
    if low.startswith("http://") or "localhost" in low or "127.0.0.1" in low:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}dev_tg={tg_id}"
    return url


def webapp_markup(tg_id: int | str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="Открыть мини-приложение",
                web_app=WebAppInfo(url=build_webapp_url(tg_id))
            )
        ]]
    )


async def get_http() -> aiohttp.ClientSession:
    global HTTP
    if HTTP is None or HTTP.closed:
        HTTP = aiohttp.ClientSession(timeout=CLIENT_TIMEOUT)
    return HTTP


async def api_get(path: str) -> tuple[int, str]:
    url = api_url(path)
    s = await get_http()
    try:
        async with s.get(url, headers={"x-app-secret": APP_SECRET}) as resp:
            txt = await resp.text()
            return resp.status, txt
    except aiohttp.ClientError as e:
        logging.error("GET %s failed: %r", url, e)
        raise


async def api_post(path: str, payload: dict) -> tuple[int, str]:
    url = api_url(path)
    s = await get_http()
    try:
        async with s.post(url, headers=headers_json(), json=payload) as resp:
            txt = await resp.text()
            return resp.status, txt
    except aiohttp.ClientError as e:
        logging.error("POST %s failed: %r", url, e)
        raise


async def api_post_form(path: str, form_data: dict) -> tuple[int, str]:
    url = api_url(path)
    s = await get_http()
    try:
        async with s.post(url, headers={"x-app-secret": APP_SECRET}, data=form_data) as resp:
            txt = await resp.text()
            return resp.status, txt
    except aiohttp.ClientError as e:
        logging.error("POST %s (form) failed: %r", url, e)
        raise


async def register_user_via_api(tg_id: int | str, phone: str, first_name: str, last_name: Optional[str]) -> dict:
    """
    1) Проверяем /api/teams/by-tg/{tg_id}.
    2) Если 404 — создаём через /api/users/register.
    """
    st, txt = await api_get(f"/api/teams/by-tg/{tg_id}")
    if st == 200:
        logging.info("GET /api/teams/by-tg -> 200: %s", txt)
        return json.loads(txt)

    if st not in (404,):
        logging.error("GET /api/teams/by-tg/%s -> %s\n%s", tg_id, st, txt)
        raise RuntimeError(f"API GET error {st}: {txt}")

    payload = {"tg_id": str(tg_id), "phone": phone, "first_name": first_name, "last_name": last_name}
    st, txt = await api_post("/api/users/register", payload)
    if st == 200:
        logging.info("POST /api/users/register -> 200: %s", txt)
        return json.loads(txt)
    if st == 423:
        raise PermissionError("REGISTRATION_LOCKED")
    logging.error("POST /api/users/register payload=%s -> %s\n%s", payload, st, txt)
    raise RuntimeError(f"API POST error {st}: {txt}")

# --------------------
# Белый список (CSV)
# --------------------
# phone -> (last_name, first_name)
KNOWN: Dict[str, Tuple[Optional[str], Optional[str]]] = {}


def load_participants(path: str) -> None:
    KNOWN.clear()
    src = path if os.path.exists(path) else PARTICIPANTS_CSV_FALLBACK
    if not os.path.exists(src):
        logging.warning("Нет ни %s, ни %s — белый список пуст.", path, PARTICIPANTS_CSV_FALLBACK)
        return
    with open(src, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            p = norm_phone(row.get("phone", ""))
            ln = (row.get("last_name") or "").strip() or None
            fn = (row.get("first_name") or "").strip() or None
            if p:
                KNOWN[p] = (ln, fn)
    logging.info("Загружено участников из CSV (бот): %d (STRICT_WHITELIST=%s)", len(KNOWN), STRICT_WHITELIST)


load_participants(PARTICIPANTS_CSV)

# --------------------
# FSM
# --------------------
class RegStates(StatesGroup):
    waiting_phone = State()
    waiting_name = State()


class PhotoStates(StatesGroup):
    waiting_photo = State()  # ждём фото для указанного task_code


router = Router()

# --------------------
# Помощники: roster / captain
# --------------------
async def fetch_team_roster_for_tg(tg_id: int | str) -> Optional[dict]:
    st, txt = await api_get(f"/api/teams/roster/by-tg/{tg_id}")
    if st == 200:
        return json.loads(txt)

    # fallback: через /api/teams/by-tg + /api/admin/teams (если публичный ростер недоступен)
    st0, txt0 = await api_get(f"/api/teams/by-tg/{tg_id}")
    if st0 != 200:
        return None
    base = json.loads(txt0)
    st2, txt2 = await api_get("/api/admin/teams")
    if st2 != 200:
        return {"team_id": base["team_id"], "team_name": base.get("team_name"), "is_locked": False,
                "members": [], "captain": None}
    teams: List[dict] = json.loads(txt2)
    for t in teams:
        if t.get("team_id") == base["team_id"]:
            return t
    return {"team_id": base["team_id"], "team_name": base.get("team_name"),
            "is_locked": False, "members": [], "captain": None}


async def fetch_team_info_for_tg(tg_id: int | str) -> Optional[dict]:
    st, txt = await api_get(f"/api/teams/by-tg/{tg_id}")
    if st != 200:
        return None
    return json.loads(txt)


async def is_user_captain(tg_id: int | str) -> bool:
    info = await fetch_team_info_for_tg(tg_id)
    if info and "is_captain" in info:
        return bool(info["is_captain"])

    roster = await fetch_team_roster_for_tg(tg_id)
    if not roster:
        return False
    cap = roster.get("captain")
    if cap and str(cap.get("tg_id")) == str(tg_id):
        return True
    for m in roster.get("members") or []:
        if (m.get("role") or "").upper() == "CAPTAIN" and str(m.get("tg_id")) == str(tg_id):
            return True
    return False


def format_team_roster(team: dict) -> str:
    """
    Телеграм-стиль, без цвета/маршрута. Показываем состав и статус заполненности.
    """
    team_name = team.get("team_name", "Команда")
    is_locked = team.get("is_locked", False)
    lock_emoji = "🔒" if is_locked else "🔓"

    members: List[dict] = team.get("members") or []
    if not isinstance(members, list):
        members = []
    members_count = len(members)

    lines = []
    cap = team.get("captain")
    if cap:
        full = f"{(cap.get('last_name') or '').strip()} {(cap.get('first_name') or '').strip()}".strip() or "Без имени"
        lines.append(f"👑 {full}")

    for m in members:
        if cap and m.get("user_id") == cap.get("user_id"):
            continue
        role = (m.get("role") or "").upper()
        marker = "👑" if role == "CAPTAIN" else "•"
        full = f"{(m.get('last_name') or '').strip()} {(m.get('first_name') or '').strip()}".strip() or "Без имени"
        lines.append(f"{marker} {full}")

    body = "\n".join(lines) if lines else "_Пока нет участников._"
    status_line = f"\n\nУчастников: *{members_count}* из *{TEAM_SIZE}*"
    return f"*Твоя команда:* {team_name} {lock_emoji}{status_line}\n\n*Состав:*\n{body}"


# === QR support: парсинг payload из /start ===
def get_start_payload(message: Message) -> str | None:
    t = (message.text or "").strip()
    if not t.startswith("/start"):
        return None
    parts = t.split(maxsplit=1)
    if len(parts) < 2:
        return None
    return parts[1].strip() or None


QR_PREFIX = "qr_"

async def handle_qr_payload(message: Message, payload: str):
    st_check, _ = await api_get(f"/api/teams/by-tg/{message.from_user.id}")
    if st_check == 404:
        await message.answer("Ты ещё не зарегистрирован. Нажми /reg и вернись к QR.")
        return
    if st_check != 200:
        await message.answer("Сервис недоступен, попробуй позже.")
        return

    if not await is_user_captain(message.from_user.id):
        await message.answer(
            "Сканировать коды может только капитан команды.\n"
            "Передай QR капитану или попроси его отправить /scan <код>."
        )
        return

    code = payload[len(QR_PREFIX):] if payload.startswith(QR_PREFIX) else payload

    st, txt = await api_post("/api/game/scan", {"tg_id": str(message.from_user.id), "code": code})
    try:
        data = json.loads(txt) if txt else {}
    except json.JSONDecodeError:
        data = {}

    if st == 200:
        already = bool(data.get("already_solved"))
        task_title = data.get("task_title", "Задание")
        points = int(data.get("points_earned") or 0)
        total = int(data.get("team_total_points") or 0)
        if already:
            await message.answer(
                f"ℹ️ Это задание уже зачтено:\n*{task_title}*\n\n"
                f"Очки команды: *{total}*.",
                parse_mode="Markdown",
            )
        else:
            await message.answer(
                f"✅ Принято!\n*{task_title}*\n+{points} очк.\n"
                f"Сумма очков команды: *{total}*.",
                parse_mode="Markdown",
            )
        return

    detail = (data.get("detail") or "").strip().lower()
    if st == 404:
        await message.answer("QR не распознан: задание не найдено.")
        return
    if st == 409:
        if "not started" in detail:
            await message.answer(
                "Ваша команда ещё *не стартовала*.\n"
                "Капитан должен: 1) задать *своё имя команды* (/rename НовоеИмя), 2) нажать */startquest*.",
                parse_mode="Markdown",
            )
        else:
            await message.answer(data.get("detail") or "Нельзя засчитать это задание сейчас.")
        return
    if st == 423:
        await message.answer("Игра сейчас закрыта. Обратись к координатору.")
        return
    await message.answer(f"Ошибка сервера ({st}). Попробуй позже.")

# --------------------
# Хендлеры
# --------------------
@router.message(CommandStart())
async def start(message: Message):
    payload = get_start_payload(message)
    if payload:
        return await handle_qr_payload(message, payload)

    await message.answer(
        "Привет! Я квест-бот.\n"
        "• /reg — регистрация\n"
        "• /team — показать состав команды\n"
        "• /rename <новое имя> — переименовать команду (только капитан, один раз до старта)\n"
        "• /startquest — начать квест (только капитан, при полной команде и после переименования)\n"
        "• /scan <код> — ввести код с QR (только капитан)\n"
        "• /photo <код> — отправить фото-доказательство (только капитан)\n"
        "• /lb — лидерборд\n"
        "• /app — открыть мини-приложение\n"
        "• /cancel — отменить регистрацию",
        reply_markup=webapp_markup(message.from_user.id),
    )

@router.message(F.text == "/app")
async def open_app(message: Message):
    await message.answer(
        "Открой мини-приложение (встроенное в Telegram):",
        reply_markup=webapp_markup(message.from_user.id),
    )

@router.message(F.text == "/reg")
async def reg_flow(message: Message, state: FSMContext):
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отправить телефон", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await state.set_state(RegStates.waiting_phone)
    await message.answer("Шаг 1/2: поделись номером телефона (кнопка ниже).", reply_markup=kb)

@router.message(F.text.regexp(r"^/scan(\s+.+)?$"))
async def manual_scan(message: Message):
    txt = (message.text or "")
    parts = txt.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return await message.answer("Использование: `/scan <код>`", parse_mode="Markdown")
    payload = parts[1].strip()
    await handle_qr_payload(message, payload)

@router.message(F.text.regexp(r"^/rename(\s+.+)?$"))
async def rename_team(message: Message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return await message.answer("Использование: `/rename Новое имя команды`", parse_mode="Markdown")

    if not await is_user_captain(message.from_user.id):
        return await message.answer("Переименовать команду может только капитан (до старта).")

    new_name = parts[1].strip()
    st, txt = await api_post("/api/team/rename", {"tg_id": str(message.from_user.id), "new_name": new_name})
    try:
        data: Dict[str, Any] = json.loads(txt) if txt else {}
    except json.JSONDecodeError:
        data = {}

    if st == 200 and data.get("ok"):
        team_name = data.get("team_name") or new_name
        return await message.answer(f"Готово! Новое имя команды: *{team_name}*.", parse_mode="Markdown")
    if st == 403:
        return await message.answer("Переименовать команду может только капитан.")
    if st == 409:
        return await message.answer(data.get("detail") or "Переименование недоступно.")
    if st == 404:
        return await message.answer("Пользователь не найден. Нужна повторная регистрация /reg.")
    await message.answer("Сервис недоступен, попробуй позже.")

@router.message(F.text == "/startquest")
async def start_quest(message: Message):
    """
    Капитан стартует квест. Сервер проверит:
    - команда полная,
    - имя задано (не «Команда №N»),
    - не стартовали ранее.
    """
    if not await is_user_captain(message.from_user.id):
        return await message.answer("Начать квест может только капитан своей команды.")

    st, txt = await api_post_form("/api/game/start", {"tg_id": str(message.from_user.id)})
    try:
        data = json.loads(txt) if txt else {}
    except json.JSONDecodeError:
        data = {}

    if st == 200 and data.get("ok"):
        return await message.answer("🚀 Квест начат! Удачи!")
    if st == 200 and (data.get("message") or "").lower().startswith("already"):
        return await message.answer("Квест уже был начат. Увидимся на точках!")
    if st == 409:
        detail = data.get("detail") or ""
        if detail:
            return await message.answer(detail)
        return await message.answer(
            "Старт недоступен. Убедись, что команда *полная* и у неё задано своё имя через /rename.",
            parse_mode="Markdown",
        )
    if st == 404:
        return await message.answer("Пользователь не найден. Пройди /reg.")
    return await message.answer("Сервис недоступен, попробуй позже.")

@router.message(F.text.regexp(r"^/photo(\s+.+)?$"))
async def photo_command(message: Message, state: FSMContext):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return await message.answer("Использование: `/photo <task_code>` — затем пришли фото.", parse_mode="Markdown")

    if not await is_user_captain(message.from_user.id):
        return await message.answer("Фото засчитывает только капитан.")

    task_code = parts[1].strip()
    await state.update_data(photo_task_code=task_code)
    await state.set_state(PhotoStates.waiting_photo)
    await message.answer("Ок! Теперь пришли *фото* по этому заданию одной картинкой.", parse_mode="Markdown")

@router.message(StateFilter(PhotoStates.waiting_photo), F.content_type == ContentType.PHOTO)
async def on_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    task_code = data.get("photo_task_code")
    if not task_code:
        await state.clear()
        return await message.answer("Что-то пошло не так. Отправь команду /photo ещё раз.")

    photo = message.photo[-1] if message.photo else None
    if not photo:
        return await message.answer("Не вижу фото. Пришли картинку одним сообщением.")

    payload = {"tg_id": str(message.from_user.id), "task_code": task_code, "tg_file_id": photo.file_id}
    st, txt = await api_post("/api/game/photo", payload)
    try:
        data = json.loads(txt) if txt else {}
    except json.JSONDecodeError:
        data = {}

    if st == 200:
        await state.clear()
        return await message.answer("Фото отправлено на модерацию. Спасибо!")
    if st in (403, 409, 423):
        await state.clear()
        detail = (data.get("detail") or "").lower()
        if "not started" in detail:
            return await message.answer(
                "Ваша команда ещё не стартовала. Капитану нужно нажать */startquest* после переименования.",
                parse_mode="Markdown",
            )
        return await message.answer(data.get("detail") or "Не удалось отправить фото сейчас.")
    if st == 404:
        await state.clear()
        return await message.answer("Задание не найдено. Проверь код и попробуй ещё раз.")
    await message.answer("Сервис недоступен, попробуй позже.")

@router.message(F.text == "/cancel")
async def cancel_flow(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Ок, регистрацию отменил. В любой момент набери /reg.")

@router.message(F.content_type == ContentType.CONTACT)
async def on_contact(message: Message, state: FSMContext):
    c = message.contact
    if c and c.user_id and message.from_user and c.user_id != message.from_user.id:
        return await message.answer("Пожалуйста, отправь *свой* номер через кнопку.", parse_mode="Markdown")

    phone = norm_phone(c.phone_number if c else "")
    if not phone:
        await message.answer("Не удалось распознать номер. Попробуй ещё раз через /reg.")
        return
    await state.update_data(phone=phone)
    await state.set_state(RegStates.waiting_name)
    await message.answer("Шаг 2/2: пришли *имя* (как тебя записать в команде).", parse_mode="Markdown")

@router.message(StateFilter(RegStates.waiting_name), F.text)
async def on_name(message: Message, state: FSMContext):
    first_name, last_name = parse_name_simple(message.text or "")
    if not first_name or len(first_name) < 2:
        return await message.answer("Имя слишком короткое. Пришли понятное имя (минимум 2 символа).")

    data = await state.get_data()
    phone = data.get("phone", "")

    if not phone:
        await state.set_state(RegStates.waiting_phone)
        return await message.answer("Давай начнём сначала. Нажми /reg и поделись своим номером телефона.")

    if STRICT_WHITELIST and phone not in KNOWN:
        return await message.answer(
            "Не нашёл тебя в списке. Проверь номер и попробуй ещё раз.\n"
            "Или обратись к координатору."
        )

    try:
        info = await register_user_via_api(
            tg_id=message.from_user.id, phone=phone, first_name=first_name, last_name=last_name
        )
        team = await fetch_team_roster_for_tg(message.from_user.id)
        if team:
            await message.answer(format_team_roster(team), parse_mode="Markdown")
            members_count = len(team.get("members") or [])
            if await is_user_captain(message.from_user.id) and members_count >= TEAM_SIZE:
                await message.answer(
                    "Команда выглядит полной. Задай имя: `/rename <Название>` и запусти квест командой */startquest*.",
                    parse_mode="Markdown",
                )
        else:
            team_name = (info or {}).get("team_name", "твоя команда")
            await message.answer(f"Готово! Ты в команде: *{team_name}*.", parse_mode="Markdown")
        await state.clear()
    except PermissionError:
        await message.answer("Регистрация закрыта. Обратись к координатору.")
        await state.clear()
    except Exception:
        logging.exception("Register API error")
        await message.answer("Сервер регистрации временно недоступен. Попробуй ещё раз через минутку.")

@router.message(F.text == "/team")
async def my_team(message: Message):
    try:
        team = await fetch_team_roster_for_tg(message.from_user.id)
        if not team:
            return await message.answer("Ты ещё не зарегистрирован. Набери /reg.")
        text = format_team_roster(team)
        return await message.answer(text, parse_mode="Markdown")
    except Exception:
        return await message.answer("Сервис недоступен, попробуй позже.")

@router.message(F.text.in_({"/lb", "/leaderboard"}))
async def leaderboard(message: Message):
    try:
        st, txt = await api_get("/api/leaderboard")
        if st != 200:
            return await message.answer("Лидерборд временно недоступен.")
        rows: List[dict] = json.loads(txt)
        if not rows:
            return await message.answer("Лидерборд пока пуст.")
        out_lines = ["*Лидерборд* (по времени прохождения):"]
        for i, r in enumerate(rows[:10], start=1):
            name = r.get("team_name", f"Команда #{r.get('team_id')}")
            done = r.get("tasks_done", 0)
            total = r.get("total_tasks", 0)
            elapsed = r.get("elapsed_seconds")
            if r.get("finished_at"):
                t_line = f"{elapsed}s"
                out_lines.append(f"{i}. *{name}* — {done}/{total}, ⏱ {t_line}")
            elif r.get("started_at"):
                t_line = f"{elapsed}s"
                out_lines.append(f"{i}. *{name}* — {done}/{total} (в процессе, {t_line})")
            else:
                out_lines.append(f"{i}. *{name}* — не стартовали")
        await message.answer("\n".join(out_lines), parse_mode="Markdown")
    except Exception:
        logging.exception("leaderboard error")
        await message.answer("Не удалось получить лидерборд.")

@router.message(F.text == "/ping")
async def ping_api(message: Message):
    try:
        st, txt = await api_get("/health")
        await message.answer(f"API /health → {st}: {txt}")
    except Exception as e:
        await message.answer(f"API error: {e!r}")

# --------------------
# Обработчик ошибок (v3)
# --------------------
@router.errors()
async def on_error(event: ErrorEvent):
    exc = event.exception

    # Пользователь заблокировал бота — штатная ситуация
    if isinstance(exc, TelegramForbiddenError):
        logging.info("Ignored Forbidden: user blocked the bot")
        return True  # помечаем как обработанную

    # Остальные исключения логируем
    logging.exception("Unhandled exception in bot", exc_info=exc)
    return True

# --------------------
# Entry point
# --------------------
async def main():
    logging.info("Starting aiogram polling...")
    bot = Bot(BOT_TOKEN, parse_mode=None)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    global HTTP
    HTTP = aiohttp.ClientSession(timeout=CLIENT_TIMEOUT)
    try:
        await dp.start_polling(bot, polling_timeout=30, drop_pending_updates=True)
    finally:
        try:
            if HTTP and not HTTP.closed:
                await HTTP.close()
        except Exception:
            pass

if __name__ == "__main__":
    asyncio.run(main())