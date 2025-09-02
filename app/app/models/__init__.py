# app/app/models/__init__.py
from sqlalchemy import (
    Column, Integer, BigInteger, String, Boolean, DateTime, ForeignKey, Text, Float,
    UniqueConstraint, Index, func,
)
from sqlalchemy.orm import relationship
from ..database import Base



# ========= common =========

class TimestampMixin:
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


# ========= new route/checkpoint/proof model =========

class Route(Base, TimestampMixin):
    __tablename__ = "routes"
    __table_args__ = (
        UniqueConstraint("code", name="uq_route_code"),
        Index("ix_routes_active", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    code = Column(String(1), nullable=False, index=True)  # 'A'|'B'|'C'
    name = Column(String(64), nullable=False)
    is_active = Column(Boolean, nullable=False, server_default="1")

    # relations
    checkpoints = relationship("Checkpoint", back_populates="route", cascade="all, delete-orphan")
    teams = relationship("Team", back_populates="route")

    def __repr__(self) -> str:
        return f"<Route id={self.id} code={self.code!r} name={self.name!r} active={self.is_active}>"


class Checkpoint(Base, TimestampMixin):
    __tablename__ = "checkpoints"
    __table_args__ = (
        UniqueConstraint("route_id", "order_num", name="uq_checkpoint_route_order"),
        Index("ix_checkpoint_route_order", "route_id", "order_num"),
    )

    id = Column(Integer, primary_key=True)
    route_id = Column(Integer, ForeignKey("routes.id", ondelete="CASCADE"), nullable=False, index=True)
    order_num = Column(Integer, nullable=False)  # 1..N внутри маршрута
    title = Column(String(128), nullable=False)
    riddle = Column(Text, nullable=False)
    photo_hint = Column(Text, nullable=True)

    # relations
    route = relationship("Route", back_populates="checkpoints")
    proofs = relationship("Proof", back_populates="checkpoint", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Checkpoint id={self.id} route_id={self.route_id} order={self.order_num} title={self.title!r}>"


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

    # Линейный маршрут (теперь полноценная связь)
    route_id = Column(Integer, ForeignKey("routes.id", ondelete="SET NULL"), nullable=True, index=True)
    # Текущий порядковый номер точки (линейка)
    current_order_num = Column(Integer, nullable=False, server_default="1")

    # Капитан может один раз задать название (после формирования команды)
    can_rename = Column(Boolean, nullable=False, server_default="1")

    # Тайминги прохождения квеста
    started_at = Column(DateTime, nullable=True, index=True)
    finished_at = Column(DateTime, nullable=True, index=True)

    # relations
    members = relationship("TeamMember", back_populates="team", cascade="all, delete-orphan")
    progress = relationship("TeamTaskProgress", back_populates="team", cascade="all, delete-orphan")
    proofs = relationship("Proof", back_populates="team", cascade="all, delete-orphan")
    route = relationship("Route", back_populates="teams")

    def __repr__(self) -> str:
        return (
            f"<Team id={self.id} name={self.name!r} locked={self.is_locked} "
            f"route={self.route_id} current={self.current_order_num} can_rename={self.can_rename} "
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

    # relations
    teams = relationship("TeamMember", back_populates="user", cascade="all, delete-orphan")
    submissions = relationship("TeamTaskProgress", back_populates="submitted_by", cascade="all, delete-orphan")
    proofs_submitted = relationship("Proof", back_populates="submitted_by_user", cascade="all, delete-orphan")

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


# ========= legacy tasks (оставлены для совместимости/админки) =========

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

    # координаты точки задания (для ссылки на Яндекс.Карты в mini app)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)

    def __repr__(self):
        return (
            f"<Task id={self.id} code={self.code!r} order={self.order} "
            f"points={self.points} lat={self.lat} lon={self.lon}>"
        )


# ========= legacy progress (QR / PHOTO + модерация) =========

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


# ========= new proof flow (фото как единственный ответ) =========

class Proof(Base, TimestampMixin):
    __tablename__ = "proofs"
    __table_args__ = (
        UniqueConstraint("team_id", "checkpoint_id", name="uq_proof_team_checkpoint"),
        Index("ix_proof_team", "team_id"),
        Index("ix_proof_status", "status"),
        Index("ix_proof_checkpoint", "checkpoint_id"),
    )

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    route_id = Column(Integer, ForeignKey("routes.id", ondelete="CASCADE"), nullable=False)
    checkpoint_id = Column(Integer, ForeignKey("checkpoints.id", ondelete="CASCADE"), nullable=False)

    photo_file_id = Column(String(256), nullable=False)  # Telegram file_id или локальный путь
    status = Column(String(16), nullable=False, server_default="PENDING")  # PENDING|APPROVED|REJECTED

    submitted_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    judged_by = Column(BigInteger, nullable=True)  # tg admin id (можно 0)
    judged_at = Column(DateTime, nullable=True)
    comment = Column(Text, nullable=True)

    # relations
    team = relationship("Team", back_populates="proofs")
    route = relationship("Route")
    checkpoint = relationship("Checkpoint", back_populates="proofs")
    submitted_by_user = relationship("User", back_populates="proofs_submitted")

    def __repr__(self) -> str:
        return (
            f"<Proof id={self.id} team_id={self.team_id} cp_id={self.checkpoint_id} "
            f"status={self.status!r}>"
        )


__all__ = [
    "Route", "Checkpoint", "Proof",
    "Team", "User", "TeamMember",
    "Task", "TeamTaskProgress",
]
