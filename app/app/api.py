# app/app/api.py
import os
import csv
import io
import re
import json
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import (
    APIRouter, Depends, UploadFile, File, HTTPException, Header, Path, Form, Body, Query
)
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from .database import get_db
from . import models
from .schemas import (
    # public
    RegisterIn, RegisterOut, ImportReport, TeamOut, TeamRosterOut,
    # team structs / admin
    TeamMemberInfo, TeamAdminOut, SetCaptainIn, MoveMemberIn,
    # tasks / game (совместимость со старым API)
    TaskOut, TaskCreateIn, TaskUpdateIn, GameScanIn, GameScanOut,
    # rename
    TeamRenameIn, TeamRenameOut,
)

# -----------------------------------------------------------------------------
# Root router: /api
# -----------------------------------------------------------------------------
router = APIRouter(prefix="/api", tags=["api"])

APP_SECRET = os.getenv("APP_SECRET", "change-me-please")
TEAM_SIZE = int(os.getenv("TEAM_SIZE", 7))
PROOFS_DIR = os.getenv("PROOFS_DIR", "/code/data/proofs")
os.makedirs(PROOFS_DIR, exist_ok=True)

# --- security ---
def require_secret(x_app_secret: str | None = Header(default=None, alias="x-app-secret")):
    if not x_app_secret or x_app_secret != APP_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

# !!! объявляем admin-подроутер ТОЛЬКО после require_secret
admin = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_secret)])

# --- helpers ---
def now_utc() -> datetime:
    # проект везде использует naive UTC (без tzinfo)
    return datetime.utcnow()


def norm_phone(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"[^\d+]", "", s.strip())
    if s.startswith("8") and len(s) == 11:
        s = "+7" + s[1:]
    if s.isdigit() and len(s) == 11 and s[0] == "7":
        s = "+" + s
    return s


def dump_team_admin(db: Session, team: models.Team) -> TeamAdminOut:
    rows = (
        db.query(models.TeamMember, models.User)
        .join(models.User, models.User.id == models.TeamMember.user_id)
        .filter(models.TeamMember.team_id == team.id)
        .order_by(models.TeamMember.id.asc())
        .all()
    )
    members: List[TeamMemberInfo] = []
    captain: Optional[TeamMemberInfo] = None
    for m, u in rows:
        item = TeamMemberInfo(
            user_id=u.id,
            role=m.role,
            first_name=u.first_name,
            last_name=u.last_name,
            phone=u.phone,
            tg_id=u.tg_id,
        )
        members.append(item)
        if (m.role or "").upper() == "CAPTAIN":
            captain = item
    return TeamAdminOut(
        team_id=team.id,
        team_name=team.name,
        is_locked=bool(team.is_locked),
        captain=captain,
        members=members,
        color=getattr(team, "color", None),
        route_id=getattr(team, "route_id", None),
    )


def _team_member_count(db: Session, team_id: int) -> int:
    return (
        db.query(func.count(models.TeamMember.id))
        .filter(models.TeamMember.team_id == team_id)
        .scalar()
    ) or 0


def _team_is_full(db: Session, team_id: int) -> bool:
    return _team_member_count(db, team_id) >= TEAM_SIZE


def _ensure_captain_if_full(db: Session, team_id: int) -> None:
    rows = (
        db.query(models.TeamMember)
        .filter(models.TeamMember.team_id == team_id)
        .order_by(models.TeamMember.id.asc())
        .all()
    )
    if not rows or len(rows) < TEAM_SIZE:
        return
    if any((m.role or "").upper() == "CAPTAIN" for m in rows):
        return
    rows[0].role = "CAPTAIN"
    db.commit()


def _next_open_team(db: Session) -> models.Team:
    # незаполнённая разблокированная команда по возрастанию id
    candidates = (
        db.query(models.Team.id)
        .filter(models.Team.is_locked == False)  # noqa: E712
        .order_by(models.Team.id.asc())
        .all()
    )
    for (tid,) in candidates:
        if _team_member_count(db, tid) < TEAM_SIZE:
            return db.get(models.Team, tid)

    # создать новую «Команда №N»
    base_n = (db.query(func.count(models.Team.id)).scalar() or 0) + 1
    n = base_n
    while True:
        name = f"Команда №{n}"
        exists = db.query(models.Team).filter(models.Team.name == name).first()
        if not exists:
            break
        n += 1

    team = models.Team(name=name, is_locked=False)
    db.add(team)
    db.commit()
    db.refresh(team)
    return team


def _require_team_started(team: models.Team):
    if not getattr(team, "started_at", None):
        raise HTTPException(409, "Team has not started yet")


# ---------- routes helpers ----------
def _routes_with_checkpoints(db: Session) -> list[models.Route]:
    """Вернёт только маршруты, у которых есть хотя бы один чекпоинт."""
    routes = db.query(models.Route).order_by(models.Route.id.asc()).all()
    out: list[models.Route] = []
    for r in routes:
        cnt = (
            db.query(func.count(models.Checkpoint.id))
            .filter(models.Checkpoint.route_id == r.id)
            .scalar()
        ) or 0
        if cnt > 0:
            out.append(r)
    return out


def _auto_assign_route_if_needed(db: Session, team: models.Team) -> bool:
    """
    Если у команды ещё не выбран маршрут — выбрать маршрут
    с минимальным числом уже привязанных команд (среди маршрутов с чекпоинтами).
    Возвращает True, если назначили.
    """
    if getattr(team, "route_id", None):
        return True

    routes = _routes_with_checkpoints(db)
    if not routes:
        return False

    counts: Dict[int, int] = {}
    for r in routes:
        counts[r.id] = (
            db.query(func.count(models.Team.id))
            .filter(models.Team.route_id == r.id)
            .scalar()
        ) or 0

    chosen = min(routes, key=lambda r: counts.get(r.id, 0))
    team.route_id = chosen.id
    db.commit()
    return True


# ---- Маршруты / чекпойнты / доказательства ---------------------------------
def _route_total_checkpoints(db: Session, route_id: int | None) -> int:
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


def _current_checkpoint(db: Session, team: models.Team) -> models.Checkpoint | None:
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


def _is_last_checkpoint(db: Session, team: models.Team) -> bool:
    total = _route_total_checkpoints(db, getattr(team, "route_id", None))
    return bool(total and int(getattr(team, "current_order_num", 0)) >= total)


def _advance_team_to_next_checkpoint(db: Session, team: models.Team) -> None:
    team.current_order_num = int(team.current_order_num or 1) + 1
    db.commit()


# =============================================================================
#                         PUBLIC (requires x-app-secret)

@admin.get("/teams/{team_id}", response_model=TeamAdminOut)
def admin_get_team(team_id: int = Path(..., ge=1), db: Session = Depends(get_db)):
    team = db.get(models.Team, team_id)
    if not team:
        raise HTTPException(404, "Team not found")
    return dump_team_admin(db, team)

@admin.get("/proofs/pending", response_model=list)
def admin_pending(db: Session = Depends(get_db)):
    q = (
        db.query(models.Proof, models.Team, models.Checkpoint, models.Route)
        .join(models.Team, models.Team.id == models.Proof.team_id)
        .join(models.Checkpoint, models.Checkpoint.id == models.Proof.checkpoint_id)
        .join(models.Route, models.Route.id == models.Proof.route_id)
        .filter(models.Proof.status == "PENDING")
        .order_by(models.Proof.created_at.asc())
        .all()
    )
    out = []
    for proof, team, cp, route in q:
        cap_row = (
            db.query(models.TeamMember, models.User)
            .join(models.User, models.User.id == models.TeamMember.user_id)
            .filter(models.TeamMember.team_id == team.id, models.TeamMember.role == "CAPTAIN")
            .one_or_none()
        )
        cap_tg = cap_name = None
        if cap_row:
            _, u = cap_row
            cap_tg   = getattr(u, "tg_id", None)
            cap_name = getattr(u, "first_name", None)

        out.append({
            "id": proof.id,
            "team_id": team.id,
            "team_name": team.name,
            "route": route.code,
            "checkpoint_id": cp.id,
            "order_num": cp.order_num,
            "checkpoint_title": cp.title,
            "photo_file_id": proof.photo_file_id,
            "captain_tg_id": cap_tg,
            "captain_name": cap_name,
            "submitted_by_user_id": getattr(proof, "submitted_by_user_id", None),
            "created_at": proof.created_at.isoformat() if getattr(proof, "created_at", None) else None,
        })
    return out
@router.post("/users/register", response_model=RegisterOut, dependencies=[Depends(require_secret)])
def register_or_assign(payload: RegisterIn, db: Session = Depends(get_db)):
    phone = norm_phone(payload.phone)

    # 1) user by tg_id
    user = db.query(models.User).filter(models.User.tg_id == payload.tg_id).one_or_none()

    # 2) create/match by phone
    if not user:
        user = db.query(models.User).filter(models.User.phone == phone).one_or_none()
        if user:
            user.tg_id = payload.tg_id
            user.first_name = payload.first_name
            user.last_name = user.last_name or payload.first_name
        else:
            user = models.User(
                tg_id=payload.tg_id,
                phone=phone,
                first_name=payload.first_name,
                last_name=payload.first_name,
            )
            db.add(user)
        db.flush()

    # 3) membership
    member = db.query(models.TeamMember).filter(models.TeamMember.user_id == user.id).one_or_none()
    if not member:
        team = _next_open_team(db)
        db.add(models.TeamMember(team_id=team.id, user_id=user.id, role="PLAYER"))
        db.commit()
        _ensure_captain_if_full(db, team.id)
    else:
        team = db.get(models.Team, member.team_id)

    # Если команда полная и маршрута нет — назначим автоматически
    if _team_is_full(db, team.id) and not getattr(team, "route_id", None):
        _auto_assign_route_if_needed(db, team)

    return RegisterOut(user_id=user.id, team_id=team.id, team_name=team.name)


@router.post("/participants/import", response_model=ImportReport, dependencies=[Depends(require_secret)])
def import_participants(file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        content = file.file.read().decode("utf-8")
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to read CSV as UTF-8")

    reader = csv.DictReader(io.StringIO(content))
    total = loaded = skipped = 0

    for row in reader:
        total += 1
        phone = norm_phone(row.get("phone", ""))
        first_name = (row.get("first_name") or "").strip()
        if not (phone and first_name):
            skipped += 1
            continue

        exists = db.query(models.User).filter(models.User.phone == phone).first()
        if exists:
            skipped += 1
            continue

        db.add(models.User(
            tg_id=f"pending:{phone}",
            phone=phone,
            first_name=first_name,
            last_name=first_name,
        ))
        loaded += 1

    db.commit()
    return ImportReport(total=total, loaded=loaded, skipped=skipped)


@router.get("/teams/by-tg/{tg_id}", response_model=TeamOut, dependencies=[Depends(require_secret)])
def get_team_by_tg(tg_id: str, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.tg_id == tg_id).one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    member = db.query(models.TeamMember).filter(models.TeamMember.user_id == user.id).one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Team not assigned")

    team = db.get(models.Team, member.team_id)
    return TeamOut(
        team_id=team.id,
        team_name=team.name,
        role=member.role,
        is_captain=(member.role or "").upper() == "CAPTAIN",
        color=getattr(team, "color", None),
        route_id=getattr(team, "route_id", None),
    )


@router.get("/teams/roster/by-tg/{tg_id}", response_model=TeamRosterOut, dependencies=[Depends(require_secret)])
def get_roster_by_tg(tg_id: str, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.tg_id == tg_id).one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    member = db.query(models.TeamMember).filter(models.TeamMember.user_id == user.id).one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Team not assigned")

    team = db.get(models.Team, member.team_id)

    cap_row = (
        db.query(models.TeamMember, models.User)
        .join(models.User, models.User.id == models.TeamMember.user_id)
        .filter(models.TeamMember.team_id == team.id, models.TeamMember.role == "CAPTAIN")
        .one_or_none()
    )
    captain = None
    if cap_row:
        m, u = cap_row
        captain = TeamMemberInfo(
            user_id=u.id, role=m.role, first_name=u.first_name, last_name=u.last_name,
            phone=u.phone, tg_id=u.tg_id,
        )

    rows = (
        db.query(models.TeamMember, models.User)
        .join(models.User, models.User.id == models.TeamMember.user_id)
        .filter(models.TeamMember.team_id == team.id)
        .order_by(models.TeamMember.id.asc())
        .all()
    )
    members = [
        TeamMemberInfo(
            user_id=u.id, role=m.role, first_name=u.first_name, last_name=u.last_name, phone=u.phone, tg_id=u.tg_id
        )
        for m, u in rows
    ]

    return TeamRosterOut(
        team_id=team.id,
        team_name=team.name,
        is_locked=bool(team.is_locked),
        captain=captain,
        members=members,
        color=getattr(team, "color", None),
        route_id=getattr(team, "route_id", None),
        can_rename=getattr(team, "can_rename", True),
    )


# ---------- TEAM: одноразовое переименование ----------
def _rename_core(data: TeamRenameIn, db: Session) -> TeamRenameOut:
    user = db.query(models.User).filter_by(tg_id=data.tg_id).one_or_none()
    if not user:
        raise HTTPException(404, "User not found")

    member = db.query(models.TeamMember).filter_by(user_id=user.id).one_or_none()
    if not member:
        raise HTTPException(409, "User has no team")

    if (member.role or "").upper() != "CAPTAIN":
        raise HTTPException(403, "Only captain can rename")

    team = db.get(models.Team, member.team_id)

    if not _team_is_full(db, team.id):
        raise HTTPException(409, "Team is not full yet")
    if getattr(team, "started_at", None):
        raise HTTPException(409, "Team already started")
    if not getattr(team, "can_rename", True):
        raise HTTPException(409, "Rename already used")

    new_name = (data.new_name or "").strip()
    if len(new_name) < 2:
        raise HTTPException(400, "New name is too short")

    exists = (
        db.query(models.Team)
        .filter(models.Team.name == new_name, models.Team.id != team.id)
        .one_or_none()
    )
    if exists:
        raise HTTPException(409, "Team name already exists")

    team.name = new_name
    team.can_rename = False
    db.commit()

    return TeamRenameOut(ok=True, team_id=team.id, team_name=team.name, renamed=True)


@router.post("/team/rename", response_model=TeamRenameOut, dependencies=[Depends(require_secret)])
def team_rename_single(data: TeamRenameIn, db: Session = Depends(get_db)):
    return _rename_core(data, db)


@router.post("/teams/rename", response_model=TeamRenameOut, dependencies=[Depends(require_secret)])
def team_rename_plural(data: TeamRenameIn, db: Session = Depends(get_db)):
    return _rename_core(data, db)


# ---------- GAME: старт капитаном ----------
@router.post("/game/start", response_model=dict, dependencies=[Depends(require_secret)])
def game_start(
    tg_id: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter_by(tg_id=tg_id).one_or_none()
    if not user:
        raise HTTPException(404, "User not found")

    member = db.query(models.TeamMember).filter_by(user_id=user.id).one_or_none()
    if not member:
        raise HTTPException(409, "User has no team")

    if (member.role or "").upper() != "CAPTAIN":
        raise HTTPException(403, "Only captain can start")

    team = db.get(models.Team, member.team_id)

    if getattr(team, "started_at", None):
        return {"ok": True, "message": "Already started", "team_id": team.id, "team_name": team.name}

    if not _team_is_full(db, team.id):
        raise HTTPException(409, "Team is not full yet")

    # Гарантируем маршрут: если ещё не назначен — назначим
    if not getattr(team, "route_id", None):
        ok = _auto_assign_route_if_needed(db, team)
        if not ok:
            raise HTTPException(409, "Route is not assigned for this team")

    # Нельзя стартовать с именем по умолчанию, если переименование ещё доступно
    is_default = bool(re.match(r"^Команда №\d+$", team.name or ""))
    if is_default and getattr(team, "can_rename", True):
        raise HTTPException(409, "Set custom team name first")

    team.started_at = now_utc()
    if not getattr(team, "current_order_num", None):
        team.current_order_num = 1
    db.commit()
    return {
        "ok": True,
        "message": "Started",
        "team_id": team.id,
        "team_name": team.name,
        "started_at": team.started_at.isoformat(),
    }


# ---------- GAME: текущая точка (бот / интеграции) ----------
@router.get("/game/current", response_model=dict, dependencies=[Depends(require_secret)])
def game_current(tg_id: str = Query(...), db: Session = Depends(get_db)):
    user = db.query(models.User).filter_by(tg_id=tg_id).one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    member = db.query(models.TeamMember).filter_by(user_id=user.id).one_or_none()
    if not member:
        raise HTTPException(409, "User has no team")

    team = db.get(models.Team, member.team_id)

    # ✅ если финиш — сразу говорим об этом
    if getattr(team, "finished_at", None):
        return {"finished": True, "checkpoint": None}

    _require_team_started(team)

    cp = _current_checkpoint(db, team)
    if not cp:
        return {"finished": True, "checkpoint": None}

    total = _route_total_checkpoints(db, team.route_id)
    return {
        "finished": False,
        "checkpoint": {
            "id": cp.id,
            "order_num": cp.order_num,
            "title": cp.title,
            "riddle": cp.riddle,
            "photo_hint": getattr(cp, "photo_hint", None),
            "total": total,
        },
    }

# ---------- GAME: QR отключён (только фото) ----------
@router.post("/game/scan", response_model=GameScanOut, dependencies=[Depends(require_secret)])
def game_scan(_: GameScanIn, __: Session = Depends(get_db)):
    raise HTTPException(status_code=410, detail="QR flow disabled: answers are photos only")


# ---------- Фото: JSON — Proof(PENDING) на текущую точку ----------
@router.post("/game/photo", response_model=dict, dependencies=[Depends(require_secret)])
def submit_photo_json(
    data: Dict[str, Any] = Body(..., example={"tg_id": "123", "tg_file_id": "<file_id>"}),
    db: Session = Depends(get_db),
):
    tg_id = str(data.get("tg_id") or "")
    tg_file_id = str(data.get("tg_file_id") or "")

    if not (tg_id and tg_file_id):
        raise HTTPException(400, "tg_id and tg_file_id are required")

    user = db.query(models.User).filter_by(tg_id=tg_id).one_or_none()
    if not user:
        raise HTTPException(404, "User not found")

    member = db.query(models.TeamMember).filter_by(user_id=user.id).one_or_none()
    if not member:
        raise HTTPException(409, "User has no team")

    if (member.role or "").upper() != "CAPTAIN":
        raise HTTPException(403, "Only captain can submit")

    team = db.get(models.Team, member.team_id)
    _require_team_started(team)

    cp = _current_checkpoint(db, team)
    if not cp:
        return {"ok": False, "message": "Route already finished"}

    # Единственная запись на чекпоинт: переиспользуем, а не создаём ещё одну
    existing = db.query(models.Proof).filter(
        models.Proof.team_id == team.id,
        models.Proof.checkpoint_id == cp.id,
    ).one_or_none()

    if existing:
        # Если уже зачтено — не даём перезаливать
        if existing.status == "APPROVED":
            return {"ok": False, "message": "Already approved"}

        # Сбрасываем и ставим обратно в очередь с новым файлом
        existing.photo_file_id = tg_file_id
        existing.status = "PENDING"
        existing.submitted_by_user_id = user.id
        existing.judged_by = None
        existing.judged_at = None
        existing.comment = None
        db.commit()
        db.refresh(existing)
        return {"ok": True, "message": "Requeued for moderation", "proof_id": existing.id}

    # Первичная подача для этого чекпоинта
    proof = models.Proof(
        team_id=team.id,
        route_id=team.route_id,
        checkpoint_id=cp.id,
        photo_file_id=tg_file_id,         # Telegram file_id
        status="PENDING",
        submitted_by_user_id=user.id,
    )
    db.add(proof)
    db.commit()
    db.refresh(proof)
    return {"ok": True, "message": "Queued for moderation", "proof_id": proof.id}

# ---------- Фото: multipart — сохраняем файл локально и тоже Proof ----------
@router.post("/game/submit-photo", response_model=dict, dependencies=[Depends(require_secret)])
def submit_photo_file(
    tg_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter_by(tg_id=tg_id).one_or_none()
    if not user:
        raise HTTPException(404, "User not found")

    member = db.query(models.TeamMember).filter_by(user_id=user.id).one_or_none()
    if not member:
        raise HTTPException(409, "User has no team")

    if (member.role or "").upper() != "CAPTAIN":
        raise HTTPException(403, "Only captain can submit")

    team = db.get(models.Team, member.team_id)
    _require_team_started(team)

    cp = _current_checkpoint(db, team)
    if not cp:
        return {"ok": False, "message": "Route already finished"}

    ts = int(now_utc().timestamp())
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", file.filename or f"proof_{ts}.jpg")
    fname = f"team{team.id}_cp{cp.id}_{ts}_{safe_name}"
    path = os.path.join(PROOFS_DIR, fname)
    with open(path, "wb") as out:
        out.write(file.file.read())

    existing = db.query(models.Proof).filter(
        models.Proof.team_id == team.id,
        models.Proof.checkpoint_id == cp.id,
    ).one_or_none()

    if existing:
        if existing.status == "APPROVED":
            return {"ok": False, "message": "Already approved"}
        existing.photo_file_id = path           # локальный путь
        existing.status = "PENDING"
        existing.submitted_by_user_id = user.id
        existing.judged_by = None
        existing.judged_at = None
        existing.comment = None
        db.commit()
        db.refresh(existing)
        return {"ok": True, "message": "Requeued for moderation", "proof_id": existing.id, "file": fname}

    proof = models.Proof(
        team_id=team.id,
        route_id=team.route_id,
        checkpoint_id=cp.id,
        photo_file_id=path,                     # локальный путь
        status="PENDING",
        submitted_by_user_id=user.id,
    )
    db.add(proof)
    db.commit()
    db.refresh(proof)
    return {"ok": True, "message": "Queued for moderation", "proof_id": proof.id, "file": fname}

# ---------- ЛИДЕРБОРД по маршруту ----------
@router.get("/leaderboard", response_model=list, dependencies=[Depends(require_secret)])
def leaderboard(
    route: Optional[str] = Query(None, description="Route code A|B|C (optional)"),
    db: Session = Depends(get_db),
):
    route_row = None
    if route:
        route_row = db.query(models.Route).filter(models.Route.code == route.upper()).one_or_none()
        if not route_row:
            raise HTTPException(404, "Route not found")

    teams_q = db.query(models.Team)
    if route_row:
        teams_q = teams_q.filter(models.Team.route_id == route_row.id)
    teams = teams_q.order_by(models.Team.id.asc()).all()

    def elapsed(t: models.Team) -> Optional[int]:
        st = getattr(t, "started_at", None)
        if not st:
            return None
        fin = getattr(t, "finished_at", None)
        dt_end = fin or now_utc()
        return int((dt_end - st).total_seconds())

    rows = []
    for t in teams:
        total = _route_total_checkpoints(db, getattr(t, "route_id", None))
        done = _approved_count_cp(db, t.id)
        rows.append({
            "team_id": t.id,
            "team_name": t.name,
            "tasks_done": int(done),
            "total_tasks": int(total),
            "started_at": getattr(t, "started_at", None).isoformat() if getattr(t, "started_at", None) else None,
            "finished_at": getattr(t, "finished_at", None).isoformat() if getattr(t, "finished_at", None) else None,
            "elapsed_seconds": elapsed(t),
        })

    def sort_key(r):
        started = r["started_at"] is not None
        finished = r["finished_at"] is not None
        if finished:
            return (0, r["elapsed_seconds"], 0)
        if started:
            return (1, -(r["tasks_done"]), r["team_id"])
        return (2, r["team_id"])

    rows.sort(key=sort_key)
    return rows


# ---------- ADMIN ----------


@admin.get("/teams", response_model=List[TeamAdminOut])
def admin_list_teams(db: Session = Depends(get_db)):
    teams = db.query(models.Team).order_by(models.Team.id.asc()).all()
    return [dump_team_admin(db, t) for t in teams]


@admin.post("/teams/lock", response_model=List[TeamAdminOut])
def admin_lock_all(db: Session = Depends(get_db)):
    teams = db.query(models.Team).all()
    for t in teams:
        t.is_locked = True
        _ensure_captain_if_full(db, t.id)
    db.commit()
    teams = db.query(models.Team).order_by(models.Team.id.asc()).all()
    return [dump_team_admin(db, t) for t in teams]


@admin.post("/teams/unlock", response_model=List[TeamAdminOut])
def admin_unlock_all(db: Session = Depends(get_db)):
    db.execute(update(models.Team).values(is_locked=False))
    db.commit()
    teams = db.query(models.Team).order_by(models.Team.id.asc()).all()
    return [dump_team_admin(db, t) for t in teams]


@admin.post("/teams/{team_id}/set-captain", response_model=TeamAdminOut)
def admin_set_captain(
    data: SetCaptainIn,
    team_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
):
    if not data.user_id and not data.tg_id:
        raise HTTPException(400, "Provide user_id or tg_id")

    q = db.query(models.User)
    q = q.filter(models.User.id == data.user_id) if data.user_id else q.filter(models.User.tg_id == str(data.tg_id))
    user = q.one_or_none()
    if not user:
        raise HTTPException(404, "User not found")

    member = (
        db.query(models.TeamMember)
        .filter(models.TeamMember.team_id == team_id, models.TeamMember.user_id == user.id)
        .one_or_none()
    )
    if not member:
        raise HTTPException(409, "User is not a member of this team")

    db.query(models.TeamMember).filter(
        models.TeamMember.team_id == team_id, models.TeamMember.role == "CAPTAIN"
    ).update({models.TeamMember.role: "PLAYER"})
    member.role = "CAPTAIN"
    db.commit()

    team = db.get(models.Team, team_id)
    return dump_team_admin(db, team)


@admin.post("/teams/{team_id}/unset-captain", response_model=TeamAdminOut)
def admin_unset_captain(team_id: int = Path(..., ge=1), db: Session = Depends(get_db)):
    db.query(models.TeamMember).filter(
        models.TeamMember.team_id == team_id, models.TeamMember.role == "CAPTAIN"
    ).update({models.TeamMember.role: "PLAYER"})
    db.commit()
    team = db.get(models.Team, team_id)
    return dump_team_admin(db, team)


@admin.post("/members/move", response_model=TeamAdminOut)
def admin_move_member(data: MoveMemberIn, db: Session = Depends(get_db)):
    if not data.user_id and not data.tg_id:
        raise HTTPException(400, "Provide user_id or tg_id")

    q = db.query(models.User)
    q = q.filter(models.User.id == data.user_id) if data.user_id else q.filter(models.User.tg_id == str(data.tg_id))
    user = q.one_or_none()
    if not user:
        raise HTTPException(404, "User not found")

    member = db.query(models.TeamMember).filter(models.TeamMember.user_id == user.id).one_or_none()
    if not member:
        raise HTTPException(409, "User has no team membership")

    dest = db.get(models.Team, data.dest_team_id)
    if not dest:
        raise HTTPException(404, "Destination team not found")

    member.team_id = dest.id
    member.role = "CAPTAIN" if data.make_captain else "PLAYER"
    db.commit()

    return dump_team_admin(db, dest)


# ---------- admin: tasks CRUD (совместимость со старым UI) ----------
@admin.get("/tasks", response_model=List[TaskOut])
def admin_tasks_list(db: Session = Depends(get_db)):
    items = (
        db.query(models.Task)
        .order_by(func.coalesce(models.Task.order, 10**9), models.Task.id.asc())
        .all()
    )
    return items


@admin.post("/tasks", response_model=TaskOut)
def admin_tasks_create(data: TaskCreateIn, db: Session = Depends(get_db)):
    exists = db.query(models.Task).filter(models.Task.code == data.code).one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="Task code already exists")

    obj = models.Task(
        code=data.code.strip(),
        title=data.title.strip(),
        description=data.description,
        points=int(data.points) if data.points is not None else 1,
        is_active=True if data.is_active is None else bool(data.is_active),
        order=data.order,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@admin.patch("/tasks/{task_id}", response_model=TaskOut)
def admin_tasks_update(
    task_id: int = Path(..., ge=1),
    data: TaskUpdateIn | None = Body(None),
    db: Session = Depends(get_db),
):
    obj = db.get(models.Task, task_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Task not found")

    if data is None:
        data = TaskUpdateIn()

    if data.code is not None:
        exists = (
            db.query(models.Task)
            .filter(models.Task.code == data.code, models.Task.id != obj.id)
            .one_or_none()
        )
        if exists:
            raise HTTPException(status_code=409, detail="Task code already exists")
        obj.code = data.code.strip()

    if data.title is not None:
        obj.title = data.title.strip()
    if data.description is not None:
        obj.description = data.description
    if data.points is not None:
        obj.points = int(data.points)
    if data.is_active is not None:
        obj.is_active = bool(data.is_active)
    if data.order is not None:
        obj.order = data.order

    db.commit()
    db.refresh(obj)
    return obj


@admin.delete("/tasks/{task_id}", response_model=dict)
def admin_tasks_delete(task_id: int = Path(..., ge=1), db: Session = Depends(get_db)):
    obj = db.get(models.Task, task_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Task not found")
    db.delete(obj)
    db.commit()
    return {"ok": True}


@admin.post("/tasks/reset-progress", response_model=dict)
def admin_tasks_reset_progress(db: Session = Depends(get_db)):
    # Старый прогресс больше не используется, но ручку оставляем no-op совместимой
    db.query(models.TeamTaskProgress).delete()
    db.commit()
    return {"ok": True}


# ---------- МОДЕРАЦИЯ ФОТО (Proof) ----------
@admin.get("/proofs/pending", response_model=list)
def admin_pending(db: Session = Depends(get_db)):
    q = (
        db.query(models.Proof, models.Team, models.Checkpoint, models.Route, models.User)
        .join(models.Team, models.Team.id == models.Proof.team_id)
        .join(models.Checkpoint, models.Checkpoint.id == models.Proof.checkpoint_id)
        .join(models.Route, models.Route.id == models.Proof.route_id)
        .join(models.User, models.User.id == models.Proof.submitted_by_user_id, isouter=True)
        .filter(models.Proof.status == "PENDING")
        .order_by(models.Proof.created_at.asc())
        .all()
    )
    out = []
    for proof, team, cp, route, user in q:
        out.append({
            "id": proof.id,
            "team_id": team.id,
            "team_name": team.name,
            "route": route.code,
            "checkpoint_id": cp.id,
            "order_num": cp.order_num,
            "checkpoint_title": cp.title,
            "photo_file_id": proof.photo_file_id,
            "submitted_by_user_id": getattr(proof, "submitted_by_user_id", None),
            "submitted_by_tg_id": getattr(user, "tg_id", None),     # <-- добавили
            "created_at": proof.created_at.isoformat() if getattr(proof, "created_at", None) else None,
        })
    return out


def _progress_tuple(db: Session, team: models.Team) -> Dict[str, int]:
    done = _approved_count_cp(db, team.id)
    total = _route_total_checkpoints(db, getattr(team, "route_id", None))
    return {"done": int(done), "total": int(total)}


@admin.post("/proofs/{proof_id}/approve", response_model=dict)
def admin_approve(proof_id: int = Path(..., ge=1), db: Session = Depends(get_db)):
    proof = db.get(models.Proof, proof_id)
    if not proof:
        raise HTTPException(404, "Proof not found")
    if proof.status != "PENDING":
        return {"ok": False, "message": "Already processed"}

    proof.status = "APPROVED"
    proof.judged_by = 0
    proof.judged_at = now_utc()
    db.commit()

    team = db.get(models.Team, proof.team_id)

    if _is_last_checkpoint(db, team):
        if not getattr(team, "finished_at", None):
            team.finished_at = now_utc()
            # НЕ трогаем team.current_order_num — колонка NOT NULL
            db.commit()
    else:
        _advance_team_to_next_checkpoint(db, team)

    return {"ok": True, "progress": _progress_tuple(db, team)}

@admin.post("/proofs/{proof_id}/reject", response_model=dict)
def admin_reject(proof_id: int = Path(..., ge=1), db: Session = Depends(get_db)):
    proof = db.get(models.Proof, proof_id)
    if not proof:
        raise HTTPException(404, "Proof not found")
    if proof.status != "PENDING":
        return {"ok": False, "message": "Already processed"}

    proof.status = "REJECTED"
    proof.judged_by = 0
    proof.judged_at = now_utc()
    db.commit()
    team = db.get(models.Team, proof.team_id)
    return {"ok": True, "progress": _progress_tuple(db, team)}


# Подключаем ТОЛЬКО админский саброутер
router.include_router(admin)
