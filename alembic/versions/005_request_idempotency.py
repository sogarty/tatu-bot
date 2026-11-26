"""Persist client idempotency keys for request creation retries."""

from alembic import op
import sqlalchemy as sa


revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tattoo_request",
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
    )
    op.create_index(
        "uq_tattoo_request_user_idempotency",
        "tattoo_request",
        ["user_id", "idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_tattoo_request_user_idempotency",
        "tattoo_request",
    )
    op.drop_column("tattoo_request", "idempotency_key")
