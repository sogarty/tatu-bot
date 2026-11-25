from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TEXT
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

if TYPE_CHECKING:
    from typing import Sequence


# ─── Типы ключей ─────────────────────────────────────────────────────────────
# SQLite автоинкрементит ТОЛЬКО колонку типа INTEGER PRIMARY KEY.
# BIGINT в SQLite не получает автонумерацию и вставка падает с
# "NOT NULL constraint failed: <table>.id".
# Поэтому: INTEGER в SQLite, BIGINT в PostgreSQL.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


# ─── Base ────────────────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    pass


# ─── Mixin ───────────────────────────────────────────────────────────────────


class TimestampMixin:
    """Добавляет created_at / updated_at."""

    __table_args__: tuple = ()

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
    )


# ─── tg_user ─────────────────────────────────────────────────────────────────


class TgUser(Base):
    __tablename__ = "tg_user"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_regular: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    requests_created: Mapped[list["TattooRequest"]] = relationship(
        back_populates="creator", foreign_keys="TattooRequest.created_by"
    )
    requests_as_user: Mapped[list["TattooRequest"]] = relationship(
        back_populates="user", foreign_keys="TattooRequest.user_id"
    )

    def __repr__(self) -> str:
        return f"<TgUser tg_id={self.tg_id} username={self.username}>"


# ─── tattoo_request ──────────────────────────────────────────────────────────

REQUEST_STATUSES: tuple[str, ...] = (
    "draft",
    "new",
    "accepted",
    "in_progress",
    "scheduled",
    "completed",
    "rejected",
    "cancelled",
)


class TattooRequest(Base):
    __tablename__ = "tattoo_request"

    __table_args__ = (
        CheckConstraint(
            f"status IN {tuple(REQUEST_STATUSES)}",
            name="ck_tattoo_request_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tg_user.tg_id", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[str] = mapped_column(String(50), nullable=False)
    color_mode: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # 'bw' | 'color'
    is_urgent: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    urgent_surcharge: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    created_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tg_user.tg_id", ondelete="CASCADE"), nullable=False
    )
    brief_answers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    queue_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    queue_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    accepted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
    )
    is_archived: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)

    # Relationships
    user: Mapped["TgUser"] = relationship(
        back_populates="requests_as_user",
        foreign_keys="TattooRequest.user_id"
    )
    creator: Mapped["TgUser"] = relationship(
        back_populates="requests_created",
        foreign_keys="TattooRequest.created_by"
    )
    references: Mapped[list["RequestReference"]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )
    brief_questions: Mapped[list["BriefQuestion"]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )
    appointment: Mapped["Appointment | None"] = relationship(
        back_populates="request", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<TattooRequest id={self.id} status={self.status}>"


# ─── request_reference ───────────────────────────────────────────────────────


class RequestReference(Base):
    __tablename__ = "request_reference"

    __table_args__ = (
        UniqueConstraint("request_id", "order_index", name="uq_ref_request_order"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tattoo_request.id", ondelete="CASCADE"),
        nullable=False,
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    file_id: Mapped[str] = mapped_column(TEXT, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    # Relationships
    request: Mapped["TattooRequest"] = relationship(back_populates="references")

    def __repr__(self) -> str:
        return f"<RequestReference id={self.id} index={self.order_index}>"


# ─── brief_question ──────────────────────────────────────────────────────────


class BriefQuestion(Base):
    __tablename__ = "brief_question"

    __table_args__ = (
        # Index on (request_id, question_key)
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tattoo_request.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_key: Mapped[str] = mapped_column(String(100), nullable=False)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    answered_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    # Relationships
    request: Mapped["TattooRequest"] = relationship(back_populates="brief_questions")

    def __repr__(self) -> str:
        return f"<BriefQuestion key={self.question_key}>"


# ─── master_slot ─────────────────────────────────────────────────────────────


class MasterSlot(Base):
    __tablename__ = "master_slot"

    __table_args__ = (
        # UNIQUE on slot_date — один слот на день
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    slot_date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    master_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    # Relationships
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="slot")

    def __repr__(self) -> str:
        return f"<MasterSlot date={self.slot_date} blocked={self.is_blocked}>"


# ─── appointment ─────────────────────────────────────────────────────────────

APPOINTMENT_STATUSES: tuple[str, ...] = ("confirmed", "cancelled", "done")


class Appointment(Base):
    __tablename__ = "appointment"

    __table_args__ = (
        CheckConstraint(
            f"status IN {tuple(APPOINTMENT_STATUSES)}",
            name="ck_appointment_status",
        ),
        UniqueConstraint("slot_id", name="uq_appointment_slot_id"),  # P0 — критично!
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tattoo_request.id", ondelete="CASCADE"),
        unique=True,  # одна заявка = одна запись
        nullable=False,
    )
    slot_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("master_slot.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="confirmed")
    master_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    # Relationships
    request: Mapped["TattooRequest"] = relationship(back_populates="appointment")
    slot: Mapped["MasterSlot"] = relationship(back_populates="appointments")

    def __repr__(self) -> str:
        return f"<Appointment id={self.id} slot={self.slot_id} status={self.status}>"


# ─── notification_log ────────────────────────────────────────────────────────

NOTIFICATION_STATUS_VALUES = ("sent", "failed")


class NotificationLog(Base):
    __tablename__ = "notification_log"

    __table_args__ = (
        CheckConstraint(
            f"status IN {tuple(NOTIFICATION_STATUS_VALUES)}",
            name="ck_notification_log_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tattoo_request.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    tg_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="sent"
    )
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<NotificationLog id={self.id} type={self.type}>"


# ─── bot_settings ────────────────────────────────────────────────────────────


class BotSettings(Base):
    __tablename__ = "bot_settings"

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_bot_settings_id_one"),
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    urgent_price: Mapped[float] = mapped_column(
        Numeric(10, 2), server_default="0", nullable=False
    )
    portfolio_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    welcome_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"<BotSettings urgent_price={self.urgent_price}>"


# ─── master_whitelist ────────────────────────────────────────────────────────


class MasterWhitelist(Base):
    __tablename__ = "master_whitelist"

    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False)

    def __repr__(self) -> str:
        return f"<MasterWhitelist tg_id={self.tg_id}>"
