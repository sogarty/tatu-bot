from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ─── Common ──────────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str = "ok"
    database: str = "connected"


class ErrorResponse(BaseModel):
    detail: str


# ─── TgUser ──────────────────────────────────────────────────────────────────


class TgUserBase(BaseModel):
    tg_id: int
    username: str | None = None
    first_name: str
    last_name: str | None = None
    is_regular: bool = False
    is_active: bool = True


class TgUserCreate(TgUserBase):
    pass


class TgUserOut(TgUserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


# ─── Request Reference ───────────────────────────────────────────────────────


class RequestReferenceBase(BaseModel):
    order_index: int
    file_id: str


class RequestReferenceCreate(RequestReferenceBase):
    pass


class RequestReferenceOut(RequestReferenceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


# ─── Brief Question ──────────────────────────────────────────────────────────


class BriefQuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: int
    question_key: str
    answer_text: str | None = None
    answer_json: dict | None = None
    answered_at: datetime


# ─── Bot Settings ────────────────────────────────────────────────────────────


class BotSettingsUpdate(BaseModel):
    urgent_price: float | None = None
    portfolio_url: str | None = None
    channel_url: str | None = None
    welcome_message: str | None = None


class BotSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    urgent_price: float
    portfolio_url: str | None = None
    channel_url: str | None = None
    welcome_message: str | None = None
    updated_at: datetime


# ─── Master Slot ─────────────────────────────────────────────────────────────


class MasterSlotCreate(BaseModel):
    slot_date: date
    is_blocked: bool = False
    master_note: str | None = None


class MasterSlotUpdate(BaseModel):
    is_blocked: bool | None = None
    master_note: str | None = None


class MasterSlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slot_date: date
    is_blocked: bool
    master_note: str | None = None
    created_at: datetime


# ─── Appointment ─────────────────────────────────────────────────────────────


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: int
    slot_id: int
    status: str
    master_note: str | None = None
    created_at: datetime


# ─── Tattoo Request ──────────────────────────────────────────────────────────

RequestStatus = Literal[
    "draft", "new", "accepted", "in_progress",
    "scheduled", "completed", "rejected", "cancelled",
]


class TattooRequestBase(BaseModel):
    description: str = Field(min_length=10)
    location: str = Field(min_length=3, max_length=100)
    size: str = Field(min_length=1, max_length=50)
    color_mode: Literal["bw", "color"]
    is_urgent: bool = False
    urgent_surcharge: float | None = None
    brief_answers: dict | None = None


class TattooRequestCreate(TattooRequestBase):
    user_id: int
    created_by: int


class TattooRequestDraftUpdate(BaseModel):
    """Частичное обновление черновика."""
    description: str | None = None
    location: str | None = None
    size: str | None = None
    color_mode: Literal["bw", "color"] | None = None
    is_urgent: bool | None = None
    urgent_surcharge: float | None = None
    brief_answers: dict | None = None
    status: Literal["draft"] | None = None


class TattooRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    description: str
    location: str
    size: str
    color_mode: str
    is_urgent: bool
    urgent_surcharge: float | None = None
    status: str
    created_by: int
    brief_answers: dict | None = None
    queue_order: int | None = None
    queue_rank: int | None = None
    created_at: datetime
    accepted_at: datetime | None = None
    assigned_at: datetime | None = None
    rejected_at: datetime | None = None
    completed_at: datetime | None = None
    rejection_reason: str | None = None
    updated_at: datetime
    is_archived: bool
    references: list[RequestReferenceOut] = []
    brief_questions: list[BriefQuestionOut] = []
    appointment: AppointmentOut | None = None


# ─── Request Reference batch create ──────────────────────────────────────────


class RequestReferenceBatchCreate(BaseModel):
    references: list[RequestReferenceCreate] = Field(
        min_length=1, max_length=5
    )


# ─── Requests list filter ────────────────────────────────────────────────────


class RequestsFilter(BaseModel):
    status: RequestStatus | None = None
    user_id: int | None = None
    archived: bool | None = None
    limit: int = Field(default=20, le=100, ge=1)
    offset: int = Field(default=0, ge=0)


# ─── Notification Log ────────────────────────────────────────────────────────


class NotificationLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: int
    type: str
    tg_chat_id: int
    sent_at: datetime
    status: str
    error_msg: str | None = None


# ─── Admin / Whitelist ───────────────────────────────────────────────────────


class WhitelistAdd(BaseModel):
    tg_id: int


class AdminDashboard(BaseModel):
    new_count: int = 0
    accepted_count: int = 0
    in_progress_count: int = 0
    scheduled_count: int = 0
    completed_count: int = 0
    rejected_count: int = 0
    total_count: int = 0
