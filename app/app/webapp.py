# app/app/webapp.py
import os
import hmac
import json
import hashlib
from datetime import datetime
from typing import Optional, Dict, Any, List
from urllib.parse import parse_qsl
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from .database import get_db
from . import models

# ------------------- Routers -------------------
page_router = APIRouter(tags=["webapp-page"])                 # HTML /webapp
router = APIRouter(prefix="/api/webapp", tags=["webapp"])     # JSON /api/webapp/*

# ------------------- Config / Paths -------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
TEAM_SIZE = int(os.getenv("TEAM_SIZE", 7))

PKG_DIR = Path(__file__).resolve().parent          # /code/app/app
APP_DIR = PKG_DIR.parent                           # /code/app
STATIC_DIR = Path(os.getenv("STATIC_DIR", str(APP_DIR / "static")))
WEBAPP_HTML = Path(os.getenv("WEBAPP_HTML", str(STATIC_DIR / "webapp.html")))
COORDINATOR_CONTACT = os.getenv("COORDINATOR_CONTACT", "").strip()
COORDINATOR_PHONE = os.getenv("COORDINATOR_PHONE", "").strip()

def _now_utc() -> datetime:
    # проект использует naive UTC
    return datetime.utcnow()


# ------------------- Find webapp.html -------------------
def _find_webapp_html() -> Path | None:
    candidates: List[Path] = []
    if str(WEBAPP_HTML):
        candidates.append(Path(WEBAPP_HTML))
    candidates.append(STATIC_DIR / "webapp.html")
    candidates.append(PKG_DIR / "static" / "webapp.html")
    for p in candidates:
        if p.is_file():
            return p
    return None


# ------------------- Telegram WebApp initData verification -------------------
# https://core.telegram.org/bots/webapps#validating-data-received-via-the-web-app
def _verify_init_data(init_data: str) -> Dict[str, Any]:
    if not BOT_TOKEN:
        raise HTTPException(500, "BOT_TOKEN is not configured on server")

    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    provided_hash = parsed.pop("hash", None)
    if not provided_hash:
        raise HTTPException(401, "Missing hash")

    data_check_string = "\n".join(f"{k}={parsed[k]}" for k in sorted(parsed.keys()))
    # secret_key = HMAC_SHA256(key="WebAppData", msg=BOT_TOKEN)
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, provided_hash):
        raise HTTPException(401, "Bad initData signature")

    user_json = parsed.get("user") or "{}"
    try:
        user = json.loads(user_json)
    except Exception:
        user = {}
    if not user or "id" not in user:
        raise HTTPException(401, "No user in initData")

    parsed["user"] = user
    return parsed


# ------------------- DB helpers (routes / checkpoints / proofs) --------------
def _team_for_tg(db: Session, tg_id: str) -> tuple[models.Team, models.TeamMember, models.User]:
    user = db.query(models.User).filter(models.User.tg_id == tg_id).one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    member = db.query(models.TeamMember).filter(models.TeamMember.user_id == user.id).one_or_none()
    if not member:
        raise HTTPException(409, "User has no team")
    team = db.get(models.Team, member.team_id)
    return team, member, user


def _team_is_full(db: Session, team_id: int) -> bool:
    cnt = (
        db.query(func.count(models.TeamMember.id))
        .filter(models.TeamMember.team_id == team_id)
        .scalar()
    ) or 0
    return cnt >= TEAM_SIZE


def _route_total_checkpoints(db: Session, route_id: Optional[int]) -> int:
    if not route_id:
        return 0
    return (
        db.query(func.count(models.Checkpoint.id))
        .filter(models.Checkpoint.route_id == route_id)
        .scalar()
    ) or 0


def _approved_count_cp(db: Session, team_id: int) -> int:
    return (
        db.query(func.count(models.Proof.id))
        .filter(models.Proof.team_id == team_id, models.Proof.status == "APPROVED")
        .scalar()
    ) or 0


def _current_checkpoint(db: Session, team: models.Team) -> Optional[models.Checkpoint]:
    if not getattr(team, "route_id", None) or not getattr(team, "current_order_num", None):
        return None
    return (
        db.query(models.Checkpoint)
        .filter(
            models.Checkpoint.route_id == team.route_id,
            models.Checkpoint.order_num == team.current_order_num,
        )
        .one_or_none()
    )


def _leaderboard(db: Session, route_code: Optional[str]) -> List[Dict[str, Any]]:
    teams_q = db.query(models.Team)
    if route_code:
        route = db.query(models.Route).filter(models.Route.code == route_code.upper()).one_or_none()
        if not route:
            raise HTTPException(404, "Route not found")
        teams_q = teams_q.filter(models.Team.route_id == route.id)

    teams = teams_q.order_by(models.Team.id.asc()).all()

    def elapsed(t: models.Team) -> Optional[int]:
        st = getattr(t, "started_at", None)
        if not st:
            return None
        fin = getattr(t, "finished_at", None)
        dt_end = fin or _now_utc()
        try:
            return int((dt_end - st).total_seconds())
        except Exception:
            return None

    rows: List[Dict[str, Any]] = []
    for t in teams:
        total = _route_total_checkpoints(db, getattr(t, "route_id", None))
        done = _approved_count_cp(db, t.id)
        rows.append({
            "team_id": t.id,
            "team_name": t.name,
            "tasks_done": int(done),
            "total_tasks": int(total),
            "started_at": t.started_at.isoformat() if getattr(t, "started_at", None) else None,
            "finished_at": t.finished_at.isoformat() if getattr(t, "finished_at", None) else None,
            "elapsed_seconds": elapsed(t),
        })

    def sort_key(r):
        started = r["started_at"] is not None
        finished = r["finished_at"] is not None
        if finished:
            return (0, r["elapsed_seconds"] or 10**12, r["team_id"])
        if started:
            return (1, -(r["tasks_done"]), r["team_id"])
        return (2, r["team_id"])

    rows.sort(key=sort_key)
    return rows


# ------------------- PAGE: /webapp -------------------------------------------
@page_router.get("/webapp", response_class=HTMLResponse)
def miniapp_page():
    p = _find_webapp_html()
    if p:
        return FileResponse(str(p), media_type="text/html; charset=utf-8")
    looked = [
        str(WEBAPP_HTML),
        str(STATIC_DIR / "webapp.html"),
        str(PKG_DIR / "static" / "webapp.html"),
    ]
    return JSONResponse(status_code=404, content={"detail": "webapp.html not found", "looked_at": looked})


# ------------------- JSON API ------------------------------------------------
@router.get("/summary", response_class=JSONResponse)
def webapp_summary(init_data: str = Query(...), db: Session = Depends(get_db)):
    data = _verify_init_data(init_data)
    tg_id = str(data["user"]["id"])

    team, member, user = _team_for_tg(db, tg_id)

    route = db.get(models.Route, getattr(team, "route_id", None)) if getattr(team, "route_id", None) else None

    # чекпойнты маршрута
    cps: List[models.Checkpoint] = []
    if route:
        cps = (
            db.query(models.Checkpoint)
            .filter(models.Checkpoint.route_id == route.id)
            .order_by(models.Checkpoint.order_num.asc())
            .all()
        )

    # статусы пруфов по команде
    proofs = db.query(models.Proof).filter(models.Proof.team_id == team.id).all()
    st_by_cp: dict[int, str] = {}
    completed_by_cp: dict[int, datetime] = {}
    for p in proofs:
        st_by_cp[p.checkpoint_id] = p.status
        if p.status == "APPROVED" and getattr(p, "judged_at", None):
            completed_by_cp[p.checkpoint_id] = p.judged_at

    # список заданий + счётчики
    tasks_out: List[Dict[str, Any]] = []
    done = 0
    total = len(cps)
    for cp in cps:
        st = st_by_cp.get(cp.id, "NONE")
        if st == "APPROVED":
            done += 1
        tasks_out.append({
            "id": cp.id,
            "code": f"{route.code}-{cp.order_num}" if route else f"{cp.id}",
            "title": cp.title,
            "points": 1,
            "is_active": True,
            "status": st,
            "completed_at": completed_by_cp.get(cp.id).isoformat() if cp.id in completed_by_cp else None,
        })

    # ТЕКУЩЕЕ ЗАДАНИЕ для мини-аппы (важно!)
    current_task = None
    if getattr(team, "started_at", None) and not getattr(team, "finished_at", None):
        cp = _current_checkpoint(db, team)
        if cp:
            current_task = {
                "id": cp.id,
                "code": f"{route.code}-{cp.order_num}" if route else str(cp.id),
                "title": cp.title,
                "description": getattr(cp, "riddle", "") or "",  # фронт ждёт "description"
                "map_url": getattr(cp, "map_url", None) or None, # если карты нет — скроется
            }

    out: Dict[str, Any] = {
        "ok": True,
        "user": {
            "id": user.id,
            "tg_id": user.tg_id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "phone": user.phone,
        },
        "is_captain": ((member.role or "").upper() == "CAPTAIN"),
        "team": {
            "team_id": team.id,
            "team_name": team.name,
            "route_code": route.code if route else None,
            "current_order_num": getattr(team, "current_order_num", None),
            "started_at": team.started_at.isoformat() if getattr(team, "started_at", None) else None,
            "finished_at": team.finished_at.isoformat() if getattr(team, "finished_at", None) else None,
            # дадим надёжный счётчик прямо в team (у фронта на него приоритет)
            "solved": int(done),
            "total": int(total),
        },
        "tasks": tasks_out,
        "score": {"done": int(done), "total": int(total), "points": int(done)},  # совместимость
        "current_task": current_task,  # <<< ключевое поле
        "leaderboard": _leaderboard(db, route_code=route.code if route else None),
        "coordinator": {
            "tg": COORDINATOR_CONTACT,
            "phone": COORDINATOR_PHONE,
        },
    }
    return JSONResponse(out)


@router.get("/current", response_class=JSONResponse)
def webapp_current(init_data: str = Query(...), db: Session = Depends(get_db)):
    data = _verify_init_data(init_data)
    tg_id = str(data["user"]["id"])
    team, member, _ = _team_for_tg(db, tg_id)

    if not getattr(team, "started_at", None):
        return JSONResponse({"ok": True, "finished": False, "not_started": True, "checkpoint": None})

    cp = _current_checkpoint(db, team)
    if not cp:
        return JSONResponse({"ok": True, "finished": True, "checkpoint": None})

    total = _route_total_checkpoints(db, getattr(team, "route_id", None))
    return JSONResponse({
        "ok": True,
        "finished": False,
        "checkpoint": {
            "id": cp.id,
            "order_num": cp.order_num,
            "title": cp.title,
            "riddle": cp.riddle,
            "photo_hint": getattr(cp, "photo_hint", None),
            "total": total,
        },
        "is_captain": ((member.role or "").upper() == "CAPTAIN"),
    })


@router.post("/start", response_class=JSONResponse)
def webapp_start(body: Dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    """
    Старт маршрута капитаном. Мини-аппа дергает эту ручку.
    """
    init_data = body.get("init_data") or ""
    data = _verify_init_data(init_data)
    tg_id = str(data["user"]["id"])
    team, member, _ = _team_for_tg(db, tg_id)

    if (member.role or "").upper() != "CAPTAIN":
        raise HTTPException(403, "Only captain can start")

    if getattr(team, "started_at", None):
        return JSONResponse({"ok": True, "already": True})

    if not _team_is_full(db, team.id):
        raise HTTPException(409, "Team is not full yet")

    if not getattr(team, "route_id", None):
        raise HTTPException(409, "Route is not assigned for this team")

    # Запрет на дефолтное имя, если переименование ещё доступно
    if (team.name or "").startswith("Команда №") and getattr(team, "can_rename", True):
        raise HTTPException(409, "Set custom team name first")

    team.started_at = _now_utc()
    if not getattr(team, "current_order_num", None):
        team.current_order_num = 1
    db.commit()

    return JSONResponse({"ok": True, "started_at": team.started_at.isoformat()})


@router.get("/leaderboard", response_class=JSONResponse)
def webapp_leaderboard(route: Optional[str] = Query(None), db: Session = Depends(get_db)):
    return JSONResponse({"ok": True, "leaderboard": _leaderboard(db, route_code=route)})


__all__ = ["router", "page_router"]
