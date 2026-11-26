"""Protect queue positions from duplicate active ranks."""

from alembic import op
import sqlalchemy as sa


revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None

_ACTIVE = "status IN ('accepted', 'in_progress', 'scheduled')"


def upgrade() -> None:
    bind = op.get_bind()
    # Repair legacy duplicates deterministically before adding the constraint.
    # Both supported databases provide ROW_NUMBER() in current versions.
    bind.execute(
        sa.text(
            "WITH ranked AS ("
            " SELECT id, ROW_NUMBER() OVER (ORDER BY queue_rank, created_at, id) AS new_rank"
            " FROM tattoo_request"
            f" WHERE {_ACTIVE} AND queue_rank IS NOT NULL"
            ") UPDATE tattoo_request AS request"
            " SET queue_rank = ranked.new_rank, queue_order = ranked.new_rank"
            " FROM ranked WHERE request.id = ranked.id"
        )
    )

    indexes = sa.inspect(bind).get_indexes("tattoo_request")
    if not any(index.get("name") == "uq_active_queue_rank" for index in indexes):
        op.create_index(
            "uq_active_queue_rank",
            "tattoo_request",
            ["queue_rank"],
            unique=True,
            postgresql_where=sa.text(
                "queue_rank IS NOT NULL AND " + _ACTIVE
            ),
            sqlite_where=sa.text(
                "queue_rank IS NOT NULL AND " + _ACTIVE
            ),
        )


def downgrade() -> None:
    op.drop_index("uq_active_queue_rank", table_name="tattoo_request")
