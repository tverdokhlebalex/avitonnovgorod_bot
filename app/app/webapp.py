# app/app/webapp.py
import os
import hmac
import json
import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from urllib.parse import parse_qsl, unquote_plus
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from .database import get_db
from . import models

# 1) HTML страница /webapp
page_router = APIRouter(tags=["webapp-page"])
# 2) JSON API /api/webapp/*
router = APIRouter(prefix="/api/webapp", tags=["webapp"])

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Базовые пути
PKG_DIR = Path(__file__).resolve().parent      # /code/app/app
APP_DIR = PKG_DIR.parent                        # /code/app
STATIC_DIR = Path(os.getenv("STATIC_DIR", str(APP_DIR / "static")))

# --------------------- Поиск webapp.html ---------------------
def _find_webapp_html() -> Path | None:
    """
    Ищем webapp.html в популярных местах:
      1) WEBAPP_HTML (ENV) — точный путь
      2) ${STATIC_DIR}/webapp.html                (по умолчанию /code/app/static/webapp.html)
      3) ${PKG_DIR}/static/webapp.html            (/code/app/app/static/webapp.html)
    """
    candidates: list[Path] = []
    env_html = os.getenv("WEBAPP_HTML", "").strip()
    if env_html:
        candidates.append(Path(env_html))
    candidates.append(STATIC_DIR / "webapp.html")
    candidates.append(PKG_DIR / "static" / "webapp.html")

    for p in candidates:
        if p.is_file():
            return p
    return None

# --------------------- Telegram WebApp initData verification ------------------
# Док: https://core.telegram.org/bots/webapps#validating-data-received-via-the-web-app

def _calc_telegram_hash(data_check_string: str) -> str:
    # секрет = HMAC_SHA256(key="WebAppData", msg=BOT_TOKEN)
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    # итоговая подпись = HMAC_SHA256(secret_key, data_check_string)
    return hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()


def _verify_init_data(init_data: str) -> Dict[str, Any]:
    if not BOT_TOKEN:
        raise HTTPException(500, "BOT_TOKEN is not configured on server")

    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    provided_hash = parsed.pop("hash", None)
    if not provided_hash:
        raise HTTPException(401, "Missing hash")

    data_check_string = "\n".join(f"{k}={parsed[k]}" for k in sorted(parsed.keys()))
    good_hash = _calc_telegram_hash(data_check_string)
    if not hmac.compare_digest(good_hash, provided_hash):
        raise HTTPException(401, "Bad initData signature")

    # user — JSON-строка
    user_raw = parsed.get("user")
    user = None
    if user_raw:
        try:
            user = json.loads(user_raw)
        except Exception:
            user = json.loads(unquote_plus(user_raw))
    if not user or "id" not in user:
        raise HTTPException(401, "No user in initData")

    parsed["user"] = user
    return parsed


# ------------------------------- DB helpers ----------------------------------

def _tasks_total(db: Session) -> int:
    return (
        db.query(func.count(models.Task.id))
        .filter(models.Task.is_active == True)  # noqa: E712
        .scalar()
    ) or 0


def _solved_count(db: Session, team_id: int) -> int:
    return (
        db.query(func.count(models.TeamTaskProgress.id))
        .filter(
            models.TeamTaskProgress.team_id == team_id,
            models.TeamTaskProgress.status == "APPROVED",
        )
        .scalar()
    ) or 0


def _approved_points(db: Session, team_id: int) -> int:
    return (
        db.query(func.coalesce(func.sum(models.Task.points), 0))
        .select_from(models.TeamTaskProgress)
        .join(models.Task, models.Task.id == models.TeamTaskProgress.task_id)
        .filter(
            models.TeamTaskProgress.team_id == team_id,
            models.TeamTaskProgress.status == "APPROVED",
        )
        .scalar()
    ) or 0


def _current_task(db: Session, team_id: int) -> Optional[models.Task]:
    """Первое активное задание, которое ещё не APPROVED у команды."""
    subq = (
        db.query(models.TeamTaskProgress.task_id)
        .filter(
            models.TeamTaskProgress.team_id == team_id,
            models.TeamTaskProgress.status == "APPROVED",
        )
        .subquery()
    )
    return (
        db.query(models.Task)
        .filter(models.Task.is_active == True)  # noqa: E712
        .filter(~models.Task.id.in_(subq))
        .order_by(func.coalesce(models.Task.order, 10**9), models.Task.id.asc())
        .first()
    )


def _team_for_tg(db: Session, tg_id: str) -> tuple[models.Team, models.TeamMember, models.User]:
    user = db.query(models.User).filter(models.User.tg_id == tg_id).one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    member = db.query(models.TeamMember).filter(models.TeamMember.user_id == user.id).one_or_none()
    if not member:
        raise HTTPException(409, "User has no team")
    team = db.get(models.Team, member.team_id)
    return team, member, user


def _leaderboard(db: Session) -> List[Dict[str, Any]]:
    """
    Счёт: число решённых задач; длительность: finished_at - started_at
    Сортировка:
      1) завершившие — по возрастанию длительности,
      2) затем начатые — по убыванию solved,
      3) затем не начатые — по id.
    """
    now = datetime.now(timezone.utc)
    total = _tasks_total(db)
    teams = db.query(models.Team).order_by(models.Team.id.asc()).all()

    rows: List[Dict[str, Any]] = []
    for t in teams:
        solved = _solved_count(db, t.id)
        started_at = t.started_at
        finished_at = t.finished_at

        if solved == total and total > 0 and not finished_at:
            # если все закрыты, но финал не проставлен — берём последнее completed_at
            max_completed = (
                db.query(func.max(models.TeamTaskProgress.completed_at))
                .filter(
                    models.TeamTaskProgress.team_id == t.id,
                    models.TeamTaskProgress.status == "APPROVED",
                )
                .scalar()
            )
            finished_at = max_completed

        duration_sec: Optional[int] = None
        if started_at:
            end_time = finished_at or now
            try:
                duration_sec = int((end_time - started_at).total_seconds())
            except Exception:
                duration_sec = None

        rows.append({
            "team_id": t.id,
            "team_name": t.name,
            "solved": int(solved),
            "total": int(total),
            "started_at": started_at.isoformat() if started_at else None,
            "finished_at": finished_at.isoformat() if finished_at else None,
            "duration_sec": duration_sec,
        })

    def _key(r: Dict[str, Any]):
        finished = r["finished_at"] is not None
        started = r["started_at"] is not None
        if finished:
            return (0, r["duration_sec"] or 10**12, r["team_id"])
        if started:
            return (1, -int(r["solved"]), r["team_id"])
        return (2, r["team_id"])

    rows.sort(key=_key)
    return rows


def _yandex_url(task: models.Task) -> Optional[str]:
    """Если у задания будут lat/lon — вернём ссылку на Я.Карты. Сейчас вернёт None."""
    if getattr(task, "lat", None) is not None and getattr(task, "lon", None) is not None:
        lat = float(task.lat)
        lon = float(task.lon)
        return f"https://yandex.ru/maps/?ll={lon:.6f},{lat:.6f}&z=17&l=map"
    return None


# --- ХЭНДЛЕР СТРАНИЦЫ ---
@page_router.get("/webapp", response_class=HTMLResponse)
def miniapp_page():
    p = _find_webapp_html()
    if p:
        return FileResponse(str(p), media_type="text/html; charset=utf-8")

    looked = [
        os.getenv("WEBAPP_HTML", "").strip() or "(not set)",
        str(STATIC_DIR / "webapp.html"),
        str(PKG_DIR / "static" / "webapp.html"),
    ]
    return HTMLResponse(
        status_code=404,
        content=json.dumps({"detail": "webapp.html not found", "looked_at": looked}, ensure_ascii=False),
        media_type="application/json; charset=utf-8",
    )

# ------------------------------- JSON API ------------------------------------

@router.get("/summary", response_class=JSONResponse)
def webapp_summary(init_data: str = Query(...), db: Session = Depends(get_db)):
    data = _verify_init_data(init_data)
    tg_id = str(data["user"]["id"])
    team, member, _ = _team_for_tg(db, tg_id)

    total = _tasks_total(db)
    solved = _solved_count(db, team.id)
    points = _approved_points(db, team.id)
    cur_task = _current_task(db, team.id)

    finished_at = team.finished_at
    if solved == total and total > 0 and not finished_at:
        finished_at = (
            db.query(func.max(models.TeamTaskProgress.completed_at))
            .filter(
                models.TeamTaskProgress.team_id == team.id,
                models.TeamTaskProgress.status == "APPROVED",
            )
            .scalar()
        )

    first_task = (
        db.query(models.Task)
        .filter(models.Task.is_active == True)  # noqa: E712
        .order_by(func.coalesce(models.Task.order, 10**9), models.Task.id.asc())
        .first()
    )

    out: Dict[str, Any] = {
        "ok": True,
        "is_captain": ((member.role or "").upper() == "CAPTAIN"),
        "team": {
            "team_id": team.id,
            "team_name": team.name,
            "started_at": team.started_at.isoformat() if team.started_at else None,
            "finished_at": finished_at.isoformat() if finished_at else None,
            "solved": int(solved),
            "total": int(total),
        },
        "score": {  # совместимость
            "done": int(solved),
            "total": int(total),
            "points": int(points),
        },
        "current_task": None,
        "first_task_map": _yandex_url(first_task) if first_task else None,
        "leaderboard": _leaderboard(db),
    }
    if cur_task:
        out["current_task"] = {
            "id": cur_task.id,
            "code": cur_task.code,
            "title": cur_task.title,
            "description": cur_task.description,
            "map_url": _yandex_url(cur_task),
        }
    return JSONResponse(out)


@router.get("/leaderboard", response_class=JSONResponse)
def webapp_leaderboard(db: Session = Depends(get_db)):
    return JSONResponse({"ok": True, "leaderboard": _leaderboard(db)})


@router.post("/start", response_class=JSONResponse)
def webapp_start(body: Dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    init_data = body.get("init_data") or ""
    data = _verify_init_data(init_data)
    tg_id = str(data["user"]["id"])
    team, member, _ = _team_for_tg(db, tg_id)

    if (member.role or "").upper() != "CAPTAIN":
        raise HTTPException(403, "Only captain can start")

    if team.started_at:
        task = _current_task(db, team.id) or (
            db.query(models.Task)
            .filter(models.Task.is_active == True)  # noqa: E712
            .order_by(func.coalesce(models.Task.order, 10**9), models.Task.id.asc())
            .first()
        )
        return JSONResponse({"ok": True, "already": True, "map_url": _yandex_url(task) if task else None})

    team.started_at = datetime.now(timezone.utc)
    db.commit()

    first = _current_task(db, team.id) or (
        db.query(models.Task)
        .filter(models.Task.is_active == True)  # noqa: E712
        .order_by(func.coalesce(models.Task.order, 10**9), models.Task.id.asc())
        .first()
    )
    return JSONResponse({"ok": True, "map_url": _yandex_url(first) if first else None})


__all__ = ["router", "page_router"]