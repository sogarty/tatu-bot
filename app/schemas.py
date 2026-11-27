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
    image_content_type: str | None = None
    has_uploaded_image: bool = False


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
    slot_date: date | None = None
    status: str
    master_note: str | None = None
    created_at: datetime


# ─── Tattoo Request ──────────────────────────────────────────────────────────

RequestStatus = Literal[
    "draft", "new", "accepted", "in_progress",
    "scheduled", "completed", "rejected", "cancelled",
]


class TattooRequestBase(BaseModel):
    description: str = Field(min_length=10, max_length=5000)
    location: str = Field(min_length=3, max_length=100)
    size: str = Field(min_length=1, max_length=50)
    color_mode: Literal["bw", "color"]
    is_urgent: bool = False
    urgent_surcharge: float | None = None
    brief_answers: dict | None = None

    @field_validator("description", "location", "size")
    @classmethod
    def strip_text_fields(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Поле не может быть пустым")
        return value


class TattooRequestCreate(TattooRequestBase):
    """Данные заявки от клиента.

    user_id и created_by сюда НЕ входят: личность берётся из подписанного
    Telegram initData на сервере. Иначе любой мог бы отправить заявку
    от чужого имени, подставив чужой id.
    """


class TattooRequestAdminCreate(TattooRequestBase):
    """Создание заявки мастером от имени клиента."""

    user_id: int
    created_by: int | None = None


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

    @field_validator("description", "location", "size")
    @classmethod
    def strip_optional_text_fields(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Поле не может быть пустым")
        return value


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
    # Кто клиент: мастеру нужно видеть имя, а не только числовой id.
    client_name: str | None = None
    client_username: str | None = None
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
    idempotency_key: str | None = None
    references: list[RequestReferenceOut] = Field(default_factory=list)
    brief_questions: list[BriefQuestionOut] = Field(default_factory=list)
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


# ─── Portfolio ───────────────────────────────────────────────────────────────


class PortfolioItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    place: str = Field(min_length=1, max_length=120)
    folder: str = Field(default="Без папки", min_length=1, max_length=80)
    image_url: str | None = Field(default=None, max_length=500)
    categories: list[Literal["graphic", "color", "black", "botanical"]] = Field(default_factory=list, max_length=4)
    tags: list[str] = Field(default_factory=list, max_length=12)
    is_published: bool = False
    sort_order: int = Field(default=0, ge=-100000, le=100000)

    @field_validator("title", "place", "folder")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Поле не может быть пустым")
        return value

    @field_validator("image_url")
    @classmethod
    def validate_image_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if value.startswith("//") or not (
            value.startswith("/")
            or value.startswith("http://")
            or value.startswith("https://")
            or value.startswith("assets/")
        ):
            raise ValueError("image_url должен быть URL или путём к assets")
        return value

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, values: list[str]) -> list[str]:
        cleaned = [tag.strip() for tag in values]
        if any(not tag or len(tag) > 40 for tag in cleaned):
            raise ValueError("Теги должны содержать от 1 до 40 символов")
        return cleaned


class PortfolioItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    place: str | None = Field(default=None, min_length=1, max_length=120)
    folder: str | None = Field(default=None, min_length=1, max_length=80)
    image_url: str | None = Field(default=None, max_length=500)
    categories: list[Literal["graphic", "color", "black", "botanical"]] | None = Field(default=None, max_length=4)
    tags: list[str] | None = Field(default=None, max_length=12)
    is_published: bool | None = None
    sort_order: int | None = Field(default=None, ge=-100000, le=100000)

    @field_validator("title", "place", "folder")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("image_url")
    @classmethod
    def validate_optional_image_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if value.startswith("//") or not (
            value.startswith("/")
            or value.startswith("http://")
            or value.startswith("https://")
            or value.startswith("assets/")
        ):
            raise ValueError("image_url должен быть URL или путём к assets")
        return value

    @field_validator("tags")
    @classmethod
    def clean_optional_tags(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        cleaned = [tag.strip() for tag in values]
        if any(not tag or len(tag) > 40 for tag in cleaned):
            raise ValueError("Теги должны содержать от 1 до 40 символов")
        return cleaned


class PortfolioItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    place: str
    folder: str = "Без папки"
    image_url: str | None = None
    categories: list[str]
    tags: list[str]
    is_published: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


class PortfolioItemAdminOut(PortfolioItemOut):
    has_uploaded_image: bool = False
    image_content_type: str | None = None


class PortfolioFolderRename(BaseModel):
    old_folder: str = Field(min_length=1, max_length=80)
    new_folder: str = Field(min_length=1, max_length=80)

    @field_validator("old_folder", "new_folder")
    @classmethod
    def strip_folder_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Название папки не может быть пустым")
        return value
