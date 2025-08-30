# app/app/api.py
import os
import csv
import io
import re
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from fastapi import (
    APIRouter, Depends, UploadFile, File, HTTPException, Header, Path, Form, Body
)
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from .database import get_db
from . import models
from .schemas import (
    # public
    RegisterIn, RegisterOut, ImportReport, TeamOut, TeamRosterOut,
    # team structs / admin
    TeamMemberInfo, TeamAdminOut, SetCaptainIn, MoveMemberIn, AdminTeamUpdateIn,
    # tasks / game
    TaskOut, TaskCreateIn, TaskUpdateIn, GameScanIn, GameScanOut,
    # rename
    TeamRenameIn, TeamRenameOut,
)

router = APIRouter(prefix="/api", tags=["api"])

APP_SECRET = os.getenv("APP_SECRET", "change-me-please")
TEAM_SIZE = int(os.getenv("TEAM_SIZE", 7))
PROOFS_DIR = os.getenv("PROOFS_DIR", "/code/data/proofs")
os.makedirs(PROOFS_DIR, exist_ok=True)


# --- security ---
def require_secret(x_app_secret: str | None = Header(default=None, alias="x-app-secret")):
    if not x_app_secret or x_app_secret != APP_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")


# --- helpers ---
def now_utc() -> datetime:
    return datetime.now(timezone.utc)


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
    """
    Если команда заполнена и капитан ещё не назначен — назначаем
    самым ранним участником (по id TeamMember).
    """
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
    """
    ЛИНЕЙНОЕ назначение:
      - Ищем САМУЮ РАННЮЮ (по id) незаполненную команду с is_locked=false.
      - Если все полные — создаём новую «Команда №N».
    """
    # ищем незаполненную
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
    # считаем N как (кол-во команд + 1), гарантируем уникальность
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


def _total_active_tasks(db: Session) -> int:
    return db.query(func.count(models.Task.id)).filter(models.Task.is_active == True).scalar() or 0  # noqa: E712


def _approved_count(db: Session, team_id: int) -> int:
    return (
        db.query(func.count(models.TeamTaskProgress.id))
        .filter(
            models.TeamTaskProgress.team_id == team_id,
            models.TeamTaskProgress.status == "APPROVED",
        )
        .scalar()
    ) or 0


def _maybe_finish_team(db: Session, team: models.Team):
    total = _total_active_tasks(db)
    done = _approved_count(db, team.id)
    if total > 0 and done >= total and not getattr(team, "finished_at", None):
        team.finished_at = now_utc()
        db.commit()


# ---------- PUBLIC ----------
@router.post("/users/register", response_model=RegisterOut, dependencies=[Depends(require_secret)])
def register_or_assign(payload: RegisterIn, db: Session = Depends(get_db)):
    """
    Регистрация: телефон + имя.
    ЛИНЕЙНО: заполняем самую раннюю незаполненную команду; если все полные — создаём новую «Команда №N».
    Капитан назначается автоматически, когда команда становится полной.
    """
    phone = norm_phone(payload.phone)

    # 1) ищем по tg_id
    user = db.query(models.User).filter(models.User.tg_id == payload.tg_id).one_or_none()

    # 2) если нет — матчим/создаём по телефону
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

    # 3) членство
    member = db.query(models.TeamMember).filter(models.TeamMember.user_id == user.id).one_or_none()
    if not member:
        team = _next_open_team(db)
        db.add(models.TeamMember(team_id=team.id, user_id=user.id, role="PLAYER"))
        db.commit()
        # если стала полной — назначим капитана
        _ensure_captain_if_full(db, team.id)
    else:
        team = db.get(models.Team, member.team_id)

    return RegisterOut(user_id=user.id, team_id=team.id, team_name=team.name)


@router.post("/participants/import", response_model=ImportReport, dependencies=[Depends(require_secret)])
def import_participants(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    CSV со столбцами: phone, first_name (фамилия не требуется).
    """
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

    # капитан
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

    # участники
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


# ---------- TEAM: одноразовое переименование (капитан, только ДО старта и когда команда полная) ----------
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

    # Можно переименовать только если
    #  - команда полная
    #  - ещё не стартовали
    #  - право не использовано
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

    # Требуем предварительного переименования (не «Команда №N» ИЛИ can_rename=False)
    is_default = bool(re.match(r"^Команда №\d+$", team.name or ""))
    if is_default and getattr(team, "can_rename", True):
        raise HTTPException(409, "Set custom team name first")

    team.started_at = now_utc()
    db.commit()
    return {"ok": True, "message": "Started", "team_id": team.id, "team_name": team.name, "started_at": team.started_at.isoformat()}


# ---------- GAME: скан QR ----------
@router.post("/game/scan", response_model=GameScanOut, dependencies=[Depends(require_secret)])
def game_scan(payload: GameScanIn, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.tg_id == payload.tg_id).one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    member = db.query(models.TeamMember).filter(models.TeamMember.user_id == user.id).one_or_none()
    if not member:
        raise HTTPException(status_code=409, detail="User has no team membership")

    if (member.role or "").upper() != "CAPTAIN":
        raise HTTPException(status_code=403, detail="Only captain can submit")

    team = db.get(models.Team, member.team_id)
    _require_team_started(team)

    task = (
        db.query(models.Task)
        .filter(models.Task.code == payload.code, models.Task.is_active == True)
        .one_or_none()
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    prog = (
        db.query(models.TeamTaskProgress)
        .filter_by(team_id=team.id, task_id=task.id)
        .one_or_none()
    )
    already = bool(prog and prog.status == "APPROVED")

    if not prog:
        prog = models.TeamTaskProgress(team_id=team.id, task_id=task.id)
        db.add(prog)

    # QR => автоапрув
    prog.status = "APPROVED"
    prog.proof_type = "QR"
    prog.proof_url = None
    prog.submitted_by_user_id = user.id
    prog.completed_at = now_utc()
    db.commit()

    # возможно, команда завершила все задания
    _maybe_finish_team(db, team)

    total = (
        db.query(func.coalesce(func.sum(models.Task.points), 0))
        .select_from(models.TeamTaskProgress)
        .join(models.Task, models.Task.id == models.TeamTaskProgress.task_id)
        .filter(models.TeamTaskProgress.team_id == team.id, models.TeamTaskProgress.status == "APPROVED")
        .scalar()
    ) or 0

    return GameScanOut(
        ok=True,
        message="OK" if not already else "Already solved",
        already_solved=already,
        team_id=team.id,
        team_name=team.name,
        task_id=task.id,
        task_title=task.title,
        points_earned=int(task.points) if not already else 0,
        team_total_points=int(total),
    )


# Фото: JSON-вариант — кладём в PENDING (только после старта)
@router.post("/game/photo", response_model=dict, dependencies=[Depends(require_secret)])
def submit_photo_json(
    data: Dict[str, Any] = Body(..., example={"tg_id": "123", "task_code": "demo", "tg_file_id": "<file_id>"}),
    db: Session = Depends(get_db),
):
    tg_id = str(data.get("tg_id") or "")
    task_code = str(data.get("task_code") or data.get("code") or "")
    tg_file_id = str(data.get("tg_file_id") or "")

    if not (tg_id and task_code and tg_file_id):
        raise HTTPException(400, "tg_id, task_code and tg_file_id are required")

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

    task = (
        db.query(models.Task)
        .filter(models.Task.code == task_code, models.Task.is_active == True)
        .one_or_none()
    )
    if not task:
        raise HTTPException(404, "Task not found")

    prog = (
        db.query(models.TeamTaskProgress)
        .filter_by(team_id=member.team_id, task_id=task.id)
        .one_or_none()
    )
    if not prog:
        prog = models.TeamTaskProgress(team_id=member.team_id, task_id=task.id)
        db.add(prog)

    prog.status = "PENDING"
    prog.proof_type = "PHOTO"
    # сохраняем именно file_id — файл подтянет админ-бот по этому id
    prog.proof_url = tg_file_id
    prog.submitted_by_user_id = user.id
    db.commit()

    return {"ok": True, "message": "Queued for moderation", "progress_id": prog.id}


# Фото: файловый вариант (multipart) — только после старта
@router.post("/game/submit-photo", response_model=dict, dependencies=[Depends(require_secret)])
def submit_photo_file(
    tg_id: str = Form(...),
    code: str = Form(...),
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

    task = (
        db.query(models.Task)
        .filter(models.Task.code == code, models.Task.is_active == True)
        .one_or_none()
    )
    if not task:
        raise HTTPException(404, "Task not found")

    ts = int(now_utc().timestamp())
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", file.filename or f"proof_{ts}.jpg")
    fname = f"team{member.team_id}_task{task.id}_{ts}_{safe_name}"
    path = os.path.join(PROOFS_DIR, fname)
    with open(path, "wb") as out:
        out.write(file.file.read())

    prog = (
        db.query(models.TeamTaskProgress)
        .filter_by(team_id=member.team_id, task_id=task.id)
        .one_or_none()
    )
    if not prog:
        prog = models.TeamTaskProgress(team_id=member.team_id, task_id=task.id)
        db.add(prog)

    prog.status = "PENDING"
    prog.proof_type = "PHOTO"
    prog.proof_url = path
    prog.submitted_by_user_id = user.id
    db.commit()

    return {"ok": True, "message": "Queued for moderation", "progress_id": prog.id, "file": fname}


# ---------- ADMIN ----------
admin = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_secret)])


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


# ---------- admin: tasks CRUD ----------
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
    data: TaskUpdateIn = None,
    db: Session = Depends(get_db),
):
    obj = db.get(models.Task, task_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Task not found")

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
    db.query(models.TeamTaskProgress).delete()
    db.commit()
    return {"ok": True}


# ---------- ЛИДЕРБОРД ----------
@router.get("/leaderboard", response_model=list, dependencies=[Depends(require_secret)])
def leaderboard(db: Session = Depends(get_db)):
    """
    Возвращает массив записей:
      {
        team_id, team_name,
        tasks_done, total_tasks,
        started_at, finished_at,
        elapsed_seconds,  # если не финишировали — идёт от started_at до now
      }
    Сортировка:
      1) Завершившие по возрастанию elapsed_seconds
      2) В процессе — по tasks_done убыв.
      3) Не стартовавшие — в конце (по team_id).
    """
    total_tasks = _total_active_tasks(db)
    teams = db.query(models.Team).order_by(models.Team.id.asc()).all()

    def elapsed(t: models.Team) -> Optional[int]:
        st = getattr(t, "started_at", None)
        if not st:
            return None
        fin = getattr(t, "finished_at", None)
        dt_end = fin or now_utc()
        return int((dt_end - st).total_seconds())

    rows = []
    for t in teams:
        done = _approved_count(db, t.id)
        rows.append({
            "team_id": t.id,
            "team_name": t.name,
            "tasks_done": int(done),
            "total_tasks": int(total_tasks),
            "started_at": getattr(t, "started_at", None).isoformat() if getattr(t, "started_at", None) else None,
            "finished_at": getattr(t, "finished_at", None).isoformat() if getattr(t, "finished_at", None) else None,
            "elapsed_seconds": elapsed(t),
        })

    # сортировка
    def sort_key(r):
        started = r["started_at"] is not None
        finished = r["finished_at"] is not None
        if finished:
            return (0, r["elapsed_seconds"], 0)  # блок 0 — финиш, дальше по времени
        if started:
            return (1, -(r["tasks_done"]), r["team_id"])  # блок 1 — идут, по прогрессу
        return (2, r["team_id"])  # блок 2 — не стартовали

    rows.sort(key=sort_key)
    return rows


# ---------- МОДЕРАЦИЯ ФОТО ----------
@admin.get("/proofs/pending", response_model=list)
def admin_pending(db: Session = Depends(get_db)):
    q = (
        db.query(models.TeamTaskProgress, models.Team, models.Task)
        .join(models.Team, models.Team.id == models.TeamTaskProgress.team_id)
        .join(models.Task, models.Task.id == models.TeamTaskProgress.task_id)
        .filter(models.TeamTaskProgress.status == "PENDING")
        .order_by(models.TeamTaskProgress.created_at.asc())
        .all()
    )
    out = []
    for prog, team, task in q:
        out.append({
            "id": prog.id,
            "team_id": team.id,
            "team_name": team.name,
            "task_id": task.id,
            "task_title": task.title,
            "proof_type": prog.proof_type,
            "proof_url": prog.proof_url,
            "submitted_by_user_id": prog.submitted_by_user_id,
            "created_at": prog.created_at.isoformat() if prog.created_at else None,
        })
    return out


def _recalc_score(db: Session, team_id: int) -> int:
    total = (
        db.query(func.coalesce(func.sum(models.Task.points), 0))
        .select_from(models.TeamTaskProgress)
        .join(models.Task, models.Task.id == models.TeamTaskProgress.task_id)
        .filter(models.TeamTaskProgress.team_id == team_id, models.TeamTaskProgress.status == "APPROVED")
        .scalar()
    ) or 0
    return int(total)


@admin.post("/proofs/{progress_id}/approve", response_model=dict)
def admin_approve(progress_id: int = Path(..., ge=1), db: Session = Depends(get_db)):
    prog = db.get(models.TeamTaskProgress, progress_id)
    if not prog:
        raise HTTPException(404, "Progress not found")
    prog.status = "APPROVED"
    prog.completed_at = now_utc()
    db.commit()

    # если это было последнее задание — закрываем команду
    team = db.get(models.Team, prog.team_id)
    _maybe_finish_team(db, team)

    return {"ok": True, "team_total_points": _recalc_score(db, prog.team_id)}


@admin.post("/proofs/{progress_id}/reject", response_model=dict)
def admin_reject(progress_id: int = Path(..., ge=1), db: Session = Depends(get_db)):
    prog = db.get(models.TeamTaskProgress, progress_id)
    if not prog:
        raise HTTPException(404, "Progress not found")
    prog.status = "REJECTED"
    db.commit()
    return {"ok": True}


# --- UPDATE TEAM (admin) ---
@admin.patch("/teams/{team_id}", response_model=TeamAdminOut)
def admin_update_team(
    team_id: int = Path(..., ge=1),
    data: AdminTeamUpdateIn | None = None,
    db: Session = Depends(get_db),
):
    team = db.get(models.Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    if data is None:
        data = AdminTeamUpdateIn()

    if data.name is not None:
        new_name = (data.name or "").strip()
        if len(new_name) < 2:
            raise HTTPException(400, "Name is too short")
        exists = (
            db.query(models.Team)
            .filter(models.Team.name == new_name, models.Team.id != team.id)
            .first()
        )
        if exists:
            raise HTTPException(409, "Team name already exists")
        team.name = new_name

    if data.color is not None and hasattr(team, "color"):
        team.color = (data.color or "").strip() or None

    if data.route_id is not None and hasattr(team, "route_id"):
        try:
            team.route_id = int(data.route_id) if data.route_id is not None else None
        except ValueError:
            raise HTTPException(400, "route_id must be integer")

    if data.is_locked is not None:
        team.is_locked = bool(data.is_locked)

    if data.can_rename is not None and hasattr(team, "can_rename"):
        team.can_rename = bool(data.can_rename)

    db.commit()
    return dump_team_admin(db, team)


# подключаем admin-router
router.include_router(admin)
