"""Initial migration — создаёт все таблицы БД.

P0-2: UNIQUE(slot_id) на appointment
P0-4: CHECK constraints на status
"""

from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── tg_user ───────────────────────────────────────────────────────
    op.create_table(
        "tg_user",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("tg_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(32), nullable=True),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=True),
        sa.Column("is_regular", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tg_id"),
    )
    op.create_index("ix_tg_user_username", "tg_user", ["username"])

    # ─── bot_settings ──────────────────────────────────────────────────
    op.create_table(
        "bot_settings",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column(
            "urgent_price",
            sa.Numeric(10, 2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("portfolio_url", sa.Text(), nullable=True),
        sa.Column("channel_url", sa.Text(), nullable=True),
        sa.Column("welcome_message", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_bot_settings_id_one"),
    )

    # ─── tattoo_request ────────────────────────────────────────────────
    op.create_table(
        "tattoo_request",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("location", sa.String(100), nullable=False),
        sa.Column("size", sa.String(50), nullable=False),
        sa.Column("color_mode", sa.String(10), nullable=False),
        sa.Column(
            "is_urgent", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("urgent_surcharge", sa.Numeric(10, 2), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("brief_answers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("queue_order", sa.Integer(), nullable=True),
        sa.Column("queue_rank", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "is_archived", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('draft', 'new', 'accepted', 'in_progress', "
            "'scheduled', 'completed', 'rejected', 'cancelled')",
            name="ck_tattoo_request_status",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["tg_user.tg_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["tg_user.tg_id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_tattoo_request_user_id", "tattoo_request", ["user_id"])
    op.create_index("ix_tattoo_request_status", "tattoo_request", ["status"])
    op.create_index("ix_tattoo_request_queue_rank", "tattoo_request", ["queue_rank"])
    op.create_index("ix_tattoo_request_created_at", "tattoo_request", ["created_at"])

    # ─── request_reference ─────────────────────────────────────────────
    op.create_table(
        "request_reference",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.BigInteger(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", "order_index", name="uq_ref_request_order"),
        sa.ForeignKeyConstraint(
            ["request_id"], ["tattoo_request.id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_request_reference_request_id", "request_reference", ["request_id"])

    # ─── brief_question ────────────────────────────────────────────────
    op.create_table(
        "brief_question",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.BigInteger(), nullable=False),
        sa.Column("question_key", sa.String(100), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("answer_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "answered_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["request_id"], ["tattoo_request.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_brief_question_request_id", "brief_question", ["request_id"]
    )

    # ─── master_slot ───────────────────────────────────────────────────
    op.create_table(
        "master_slot",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("slot_date", sa.Date(), nullable=False),
        sa.Column(
            "is_blocked", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("master_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slot_date"),
    )
    op.create_index("ix_master_slot_slot_date", "master_slot", ["slot_date"])
    op.create_index("ix_master_slot_is_blocked", "master_slot", ["is_blocked"])

    # ─── appointment ───────────────────────────────────────────────────
    op.create_table(
        "appointment",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.BigInteger(), nullable=False),
        sa.Column("slot_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="confirmed"),
        sa.Column("master_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
        sa.UniqueConstraint("slot_id"),  # P0-2: КРИТИЧЕСКИ ВАЖНО!
        sa.CheckConstraint(
            "status IN ('confirmed', 'cancelled', 'done')",
            name="ck_appointment_status",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"], ["tattoo_request.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["slot_id"], ["master_slot.id"], ondelete="RESTRICT"
        ),
    )
    op.create_index("ix_appointment_slot_id", "appointment", ["slot_id"])
    op.create_index("ix_appointment_request_id", "appointment", ["request_id"])
    op.create_index("ix_appointment_status", "appointment", ["status"])

    # ─── notification_log ──────────────────────────────────────────────
    op.create_table(
        "notification_log",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("tg_chat_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("status", sa.String(10), nullable=False, server_default="sent"),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('sent', 'failed')",
            name="ck_notification_log_status",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"], ["tattoo_request.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_notification_log_request_id", "notification_log", ["request_id"]
    )
    op.create_index(
        "ix_notification_log_tg_chat_id_sent",
        "notification_log",
        ["tg_chat_id", "sent_at"],
    )

    # ─── master_whitelist ──────────────────────────────────────────────
    op.create_table(
        "master_whitelist",
        sa.Column("tg_id", sa.BigInteger(), primary_key=True, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("master_whitelist")
    op.drop_table("notification_log")
    op.drop_table("appointment")
    op.drop_table("master_slot")
    op.drop_table("brief_question")
    op.drop_table("request_reference")
    op.drop_table("tattoo_request")
    op.drop_table("bot_settings")
    op.drop_table("tg_user")
