# app/webapp_api.py
import os
import re
import hmac, hashlib, json, urllib.parse
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .database import get_db
from . import models

router = APIRouter(prefix="/api/webapp", tags=["webapp"])

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
TEAM_SIZE = int(os.getenv("TEAM_SIZE", "7"))

def _now(): return datetime.now(timezone.utc)

def _verify_init_data(init_data_raw: str) -> Dict[str, Any]:
    """Telegram WebApp auth: https://core.telegram.org/bots/webapps#initializing-mini-apps"""
    if not init_data_raw:
        raise HTTPException(401, "Missing init_data")
    try:
        pairs = urllib.parse.parse_qsl(init_data_raw, keep_blank_values=True)
        data = {k: v for k, v in pairs}
        hash_hex = data.pop("hash")
    except Exception:
        raise HTTPException(401, "Bad init_data")

    check_string = "\n".join(f"{k}={data[k]}" for k in sorted(data.keys()))
    secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
    check_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(check_hash, hash_hex):
        raise HTTPException(401, "Bad hash")

    try:
        user = json.loads(data.get("user") or "{}")
    except Exception:
        raise HTTPException(401, "Bad user")
    if not user.get("id"):
        raise HTTPException(401, "No user id")
    return {"tg_id": str(user["id"]), "user": user, "raw": data}

def _total_active_tasks(db: Session) -> int:
    return db.query(func.count(models.Task.id)).filter(models.Task.is_active == True).scalar() or 0  # noqa

def _approved_count(db: Session, team_id: int) -> int:
    return (
        db.query(func.count(models.TeamTaskProgress.id))
        .filter(
            models.TeamTaskProgress.team_id == team_id,
            models.TeamTaskProgress.status == "APPROVED",
        ).scalar()
    ) or 0

def _team_is_full(db: Session, team_id: int) -> bool:
    cnt = db.query(func.count(models.TeamMember.id)).filter(models.TeamMember.team_id == team_id).scalar() or 0
    return cnt >= TEAM_SIZE

@router.get("/summary")
def webapp_summary(init_data: str = Query(...), db: Session = Depends(get_db)):
    auth = _verify_init_data(init_data)
    tg_id = auth["tg_id"]

    user = db.query(models.User).filter(models.User.tg_id == tg_id).one_or_none()
    if not user:
        # фронту удобно различать "не зарегистрирован"
        return {"registered": False}

    member = db.query(models.TeamMember).filter(models.TeamMember.user_id == user.id).one_or_none()
    if not member:
        return {"registered": False}

    team = db.get(models.Team, member.team_id)
    is_captain = (member.role or "").upper() == "CAPTAIN"

    total = _total_active_tasks(db)
    done = _approved_count(db, team.id)

    default_name = bool(re.match(r"^Команда №\d+$", team.name or ""))
    can_start = (
        is_captain
        and not getattr(team, "started_at", None)
        and _team_is_full(db, team.id)
        and (not default_name or not getattr(team, "can_rename", True))
    )

    return {
        "registered": True,
        "team_id": team.id,
        "team_name": team.name,
        "is_captain": is_captain,
        "status": "finished" if team.finished_at else ("started" if team.started_at else "not_started"),
        "started_at": team.started_at.isoformat() if team.started_at else None,
        "finished_at": team.finished_at.isoformat() if team.finished_at else None,
        "done": int(done),
        "total": int(total),
        "can_start": bool(can_start),
    }

@router.get("/leaderboard")
def webapp_leaderboard(db: Session = Depends(get_db)):
    total = _total_active_tasks(db)
    teams = db.query(models.Team).order_by(models.Team.id.asc()).all()

    def elapsed(t) -> Optional[int]:
        if not t.started_at:
            return None
        end = t.finished_at or _now()
        return int((end - t.started_at).total_seconds())

    rows = []
    for t in teams:
        done = _approved_count(db, t.id)
        rows.append({
            "team_id": t.id,
            "team_name": t.name,
            "done": int(done),
            "total": int(total),
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "finished_at": t.finished_at.isoformat() if t.finished_at else None,
            "elapsed_seconds": elapsed(t),
        })
    # отсортируем: финиш → идут → не стартовали
    def key(r):
        if r["finished_at"] is not None:
            return (0, r["elapsed_seconds"] or 10**9)
        if r["started_at"] is not None:
            return (1, -(r["done"]), r["team_id"])
        return (2, r["team_id"])
    rows.sort(key=key)
    return rows