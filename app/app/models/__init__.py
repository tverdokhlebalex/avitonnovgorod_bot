from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Float,
    UniqueConstraint, Index, func,
)
from sqlalchemy.orm import relationship
from app.database import Base


# ========= common =========

class TimestampMixin:
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


# ========= core entities =========

class Team(Base, TimestampMixin):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True)
    # Имя по умолчанию будет задаваться в API как «Команда №N»
    name = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)

    # Набор открыт/закрыт
    is_locked = Column(Boolean, nullable=False, server_default="0")

    # Устарело (браслеты отменили) — оставляем колонку, чтобы не мигрировать лишний раз
    color = Column(String(32), nullable=True, index=True)  # DEPRECATED

    # На будущее: линейные сценарии/маршруты (опционально)
    route_id = Column(Integer, nullable=True, index=True)

    # Капитан может один раз задать название (после формирования команды)
    can_rename = Column(Boolean, nullable=False, server_default="1")

    # Тайминги прохождения квеста
    started_at = Column(DateTime, nullable=True, index=True)
    finished_at = Column(DateTime, nullable=True, index=True)

    # Связи
    members = relationship("TeamMember", back_populates="team", cascade="all, delete-orphan")
    progress = relationship("TeamTaskProgress", back_populates="team", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return (
            f"<Team id={self.id} name={self.name!r} locked={self.is_locked} "
            f"route={self.route_id} can_rename={self.can_rename} "
            f"started_at={self.started_at} finished_at={self.finished_at}>"
        )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    tg_id = Column(String(64), nullable=True, unique=True, index=True)
    phone = Column(String(32), nullable=True, index=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default="1")

    # Связи
    teams = relationship("TeamMember", back_populates="user", cascade="all, delete-orphan")
    submissions = relationship("TeamTaskProgress", back_populates="submitted_by", cascade="all, delete-orphan")

    __table_args__ = (
        # Оставляем для совместимости: уникальность по телефону + ФИО
        UniqueConstraint("phone", "last_name", "first_name", name="uq_user_phone_fio"),
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} tg_id={self.tg_id!r} phone={self.phone!r}>"


class TeamMember(Base, TimestampMixin):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_user"),)

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(50), nullable=True)  # PLAYER / CAPTAIN

    team = relationship("Team", back_populates="members")
    user = relationship("User", back_populates="teams")

    def __repr__(self) -> str:
        return f"<TeamMember team_id={self.team_id} user_id={self.user_id} role={self.role!r}>"


# ========= tasks =========

class Task(Base, TimestampMixin):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("code", name="uq_task_code"),
        Index("ix_task_order", "order"),
    )

    id = Column(Integer, primary_key=True)
    code = Column(String(128), nullable=False)              # код из QR
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    order = Column(Integer, nullable=True)
    points = Column(Integer, nullable=False, server_default="1")
    is_active = Column(Boolean, nullable=False, server_default="1")

    # NEW: координаты точки задания (для ссылки на Яндекс.Карты в mini app)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)

    def __repr__(self):
        return (
            f"<Task id={self.id} code={self.code!r} order={self.order} "
            f"points={self.points} lat={self.lat} lon={self.lon}>"
        )


# ========= progress (QR / PHOTO + модерация) =========

class TeamTaskProgress(Base, TimestampMixin):
    """
    Единая запись прогресса по заданию для команды (team_id + task_id уникально).
    - QR: сразу APPROVED + completed_at.
    - Фото: PENDING до модерации, затем APPROVED/REJECTED.
    """
    __tablename__ = "team_task_progress"
    __table_args__ = (
        UniqueConstraint("team_id", "task_id", name="uq_ttp_team_task"),
        Index("ix_ttp_team", "team_id"),
        Index("ix_ttp_status", "status"),
    )

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)

    status = Column(String(16), nullable=False, server_default="APPROVED")  # PENDING / APPROVED / REJECTED
    proof_type = Column(String(16), nullable=True)   # 'QR' | 'PHOTO'
    proof_url = Column(Text, nullable=True)          # путь к файлу фото (если есть)

    submitted_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    completed_at = Column(DateTime, nullable=True)   # момент зачёта (для APPROVED)

    team = relationship("Team", back_populates="progress")
    task = relationship("Task")
    submitted_by = relationship("User", back_populates="submissions")

    def __repr__(self) -> str:
        return (
            f"<TeamTaskProgress team_id={self.team_id} task_id={self.task_id} "
            f"status={self.status!r} proof={self.proof_type!r}>"
        )


__all__ = ["Team", "User", "TeamMember", "Task", "TeamTaskProgress"]