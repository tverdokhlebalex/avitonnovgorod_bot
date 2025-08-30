from typing import Optional, Literal, List
from pydantic import BaseModel, Field

# --- совместимость pydantic v1/v2 для from_attributes/orm_mode ---
try:
    from pydantic import ConfigDict
    FROM_ATTR = {"model_config": ConfigDict(from_attributes=True)}
except Exception:  # pydantic v1
    class _Cfg:  # noqa: N801
        orm_mode = True
    FROM_ATTR = {"Config": _Cfg}


# ========== Публичные модели ==========

class RegisterIn(BaseModel):
    """
    Регистрация участника через бота.
    Теперь нужно только: телефон и Имя. tg_id обязателен для связки с Telegram.
    Фамилия опциональна (для совместимости с импортом CSV).
    """
    tg_id: str
    phone: str
    first_name: str
    last_name: Optional[str] = None


class RegisterOut(BaseModel):
    user_id: int
    team_id: int
    team_name: str


class ImportReport(BaseModel):
    total: int
    loaded: int
    skipped: int


class TeamOut(BaseModel):
    """Быстрый ответ про команду пользователя (для /api/teams/by-tg)."""
    team_id: int
    team_name: str
    role: Optional[str] = None
    is_captain: bool = False
    # опционально, если API вернёт:
    color: Optional[str] = None
    route_id: Optional[int] = None


# --- элементы состава команды ---

class TeamMemberInfo(BaseModel):
    user_id: int
    role: Optional[str] = None
    first_name: str
    last_name: Optional[str] = None
    phone: str
    tg_id: str


# --- публичный полный ростер ---

class TeamRosterOut(BaseModel):
    team_id: int
    team_name: str
    is_locked: bool
    captain: Optional[TeamMemberInfo] = None
    members: List[TeamMemberInfo] = Field(default_factory=list)
    # оформление/маршрут и флаг одноразового переименования
    color: Optional[str] = None
    route_id: Optional[int] = None
    can_rename: Optional[bool] = None


# ========== Админ-модели (выгрузка команд) ==========

class AdminTeamOut(BaseModel):
    team_id: int
    team_name: str
    is_locked: bool
    captain: Optional[TeamMemberInfo] = None
    members: List[TeamMemberInfo] = Field(default_factory=list)
    color: Optional[str] = None
    route_id: Optional[int] = None

# Алиасы для обратной совместимости
TeamAdminOut = AdminTeamOut
AdminTeamMemberOut = TeamMemberInfo


class AdminLockRequest(BaseModel):
    assign_captains: bool = True
    algorithm: Literal["earliest", "random"] = "earliest"


# --- действия админки над участниками/командами ---

class SetCaptainIn(BaseModel):
    # укажи ИЛИ user_id, ИЛИ tg_id
    user_id: Optional[int] = None
    tg_id: Optional[str] = None


class MoveMemberIn(BaseModel):
    dest_team_id: int
    user_id: Optional[int] = None
    tg_id: Optional[str] = None
    make_captain: bool = False


class AdminTeamUpdateIn(BaseModel):
    """Универсальное обновление полей команды из админки (по одной или несколько)."""
    name: Optional[str] = None
    color: Optional[str] = None
    route_id: Optional[int] = None
    is_locked: Optional[bool] = None
    can_rename: Optional[bool] = None


# ========== Задачи / CRUD ==========

class TaskOut(BaseModel):
    id: int
    code: str
    title: str
    description: Optional[str] = None
    points: int
    is_active: bool
    order: Optional[int] = None
    # поддержка возврата ORM-объектов
    locals().update(FROM_ATTR)  # type: ignore


class TaskCreateIn(BaseModel):
    code: str
    title: str
    description: Optional[str] = None
    points: Optional[int] = 1
    is_active: bool = True
    order: Optional[int] = None


class TaskUpdateIn(BaseModel):
    code: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    points: Optional[int] = None
    is_active: Optional[bool] = None
    order: Optional[int] = None


# ========== Игра: скан QR / фото ==========

class GameScanIn(BaseModel):
    tg_id: str
    code: str


class GameScanOut(BaseModel):
    ok: bool
    message: str
    already_solved: bool
    team_id: int
    team_name: str
    task_id: int
    task_title: str
    points_earned: int
    team_total_points: int


class PhotoSubmitIn(BaseModel):
    """
    Отправка фото капитаном (если задание требует фото).
    Для текущей реализации API используется multipart/form-data (Form+File),
    этот класс оставляем на будущее для JSON-варианта.
    """
    tg_id: str
    task_code: str
    photo_url: Optional[str] = None
    tg_file_id: Optional[str] = None


class TeamTaskOut(BaseModel):
    """Карточка выполнения задания командой (для списка на модерацию и истории)."""
    id: int
    team_id: int
    team_name: Optional[str] = None
    task_id: int
    task_title: Optional[str] = None
    status: Literal["PENDING", "APPROVED", "REJECTED"]
    proof_type: Optional[str] = None  # 'QR' | 'PHOTO'
    proof_url: Optional[str] = None
    submitted_by_user_id: Optional[int] = None
    completed_at: Optional[str] = None
    locals().update(FROM_ATTR)  # type: ignore


class ModerateTaskIn(BaseModel):
    """Кнопки модерации в админ-боте."""
    action: Literal["approve", "reject"]
    reason: Optional[str] = None


# ========== Капитан: одноразовое переименование ==========

class TeamRenameIn(BaseModel):
    """ВАЖНО: API ожидает и tg_id, и новое имя."""
    tg_id: str
    new_name: str = Field(min_length=2, max_length=255)


class TeamRenameOut(BaseModel):
    """Под текущий API: ok + итоговое имя."""
    ok: bool
    team_id: int
    team_name: str
    renamed: bool


__all__ = [
    # public
    "RegisterIn", "RegisterOut", "ImportReport",
    "TeamOut", "TeamRosterOut", "TeamMemberInfo",
    # admin teams
    "AdminTeamOut", "TeamAdminOut", "AdminTeamMemberOut",
    "AdminLockRequest", "SetCaptainIn", "MoveMemberIn", "AdminTeamUpdateIn",
    # tasks / game
    "TaskOut", "TaskCreateIn", "TaskUpdateIn",
    "GameScanIn", "GameScanOut", "PhotoSubmitIn",
    "TeamTaskOut", "ModerateTaskIn",
    # captain rename
    "TeamRenameIn", "TeamRenameOut",
]