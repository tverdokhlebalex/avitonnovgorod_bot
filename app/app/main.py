# app/app/main.py
from __future__ import annotations

import os
import csv
import re
from pathlib import Path
from typing import Dict, Any, Set

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse

from .database import engine
from .models import Base

# Роутеры
from .api import router as api_router                 # /api/...
from .webapp_api import router as webapp_api_router   # /api/webapp/...
from .webapp import page_router as webapp_page        # /webapp (HTML)


# --- helpers -----------------------------------------------------------------
def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")

def _norm_phone(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"[^\d+]", "", s.strip())
    if s.startswith("8") and len(s) == 11:
        s = "+7" + s[1:]
    if s.isdigit() and len(s) == 11 and s[0] == "7":
        s = "+" + s
    return s

def _count_whitelist(path: str) -> int:
    """Безопасно читаем CSV (phone,first_name) и считаем уникальные номера."""
    p = Path(path)
    if not p.exists() or not p.is_file():
        return 0
    phones: Set[str] = set()
    try:
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            # терпим к регистру заголовков
            fn = {name.lower(): name for name in (reader.fieldnames or [])}
            phone_key = fn.get("phone") or "phone"
            for row in reader:
                ph = _norm_phone(row.get(phone_key, ""))
                if ph:
                    phones.add(ph)
    except Exception:
        return 0
    return len(phones)


# --- ENV ---------------------------------------------------------------------
STRICT_WHITELIST: bool = _env_bool("STRICT_WHITELIST", "false")
WHITELIST_PATH: str = os.getenv("WHITELIST_PATH", "./data/participants_template.csv").strip()
PROOFS_DIR: str = os.getenv("PROOFS_DIR", "/code/data/proofs").strip()


# --- APP ---------------------------------------------------------------------
app = FastAPI(title="QuestBot")

# Роутеры
app.include_router(api_router)            # /api/...
app.include_router(webapp_api_router)     # /api/webapp/...
app.include_router(webapp_page)           # /webapp

# CORS (при необходимости можно сузить список источников)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    """
    Создаём схему БД, монтируем админку (если есть),
    готовим каталог для фото-доказательств.
    """
    Base.metadata.create_all(bind=engine)

    # Админка опциональна — не валим приложение, если её нет
    try:
        from .admin import mount_admin  # type: ignore
        mount_admin(app)
    except Exception:
        pass

    # Подготовить каталог с фото
    try:
        Path(PROOFS_DIR).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


@app.get("/health", tags=["core"])
def health() -> Dict[str, Any]:
    """
    Проверка живости + краткая диагностика.
    Размер whitelist читаем напрямую из CSV — это не влияет на логику API.
    """
    return {
        "status": "ok",
        "strict_whitelist": bool(STRICT_WHITELIST),
        "whitelist_size": _count_whitelist(WHITELIST_PATH),
        "proofs_dir": PROOFS_DIR,
    }


@app.get("/", include_in_schema=False)
def index_redirect():
    """Удобный редирект на WebApp при заходе на корень домена."""
    return RedirectResponse(url="/webapp")