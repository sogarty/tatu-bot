"""Scheduled requests no longer occupy queue positions."""

from alembic import op
import sqlalchemy as sa


revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None

_ACTIVE = "status IN ('accepted', 'in_progress')"


def upgrade() -> None:
    bind = op.get_bind()

    # Existing deployments may have assigned ranks while the old index also
    # included scheduled requests. Those ranks are stale once the appointment
    # owns the user's place in the calendar.
    bind.execute(
        sa.text(
            "UPDATE tattoo_request SET queue_rank = NULL, queue_order = NULL "
            "WHERE status = 'scheduled'"
        )
    )
    op.drop_index("uq_active_queue_rank", table_name="tattoo_request")
    op.create_index(
        "uq_active_queue_rank",
        "tattoo_request",
        ["queue_rank"],
        unique=True,
        postgresql_where=sa.text("queue_rank IS NOT NULL AND " + _ACTIVE),
        sqlite_where=sa.text("queue_rank IS NOT NULL AND " + _ACTIVE),
    )


def downgrade() -> None:
    op.drop_index("uq_active_queue_rank", table_name="tattoo_request")
    op.create_index(
        "uq_active_queue_rank",
        "tattoo_request",
        ["queue_rank"],
        unique=True,
        postgresql_where=sa.text(
            "queue_rank IS NOT NULL AND status IN "
            "('accepted', 'in_progress', 'scheduled')"
        ),
        sqlite_where=sa.text(
            "queue_rank IS NOT NULL AND status IN "
            "('accepted', 'in_progress', 'scheduled')"
        ),
    )
