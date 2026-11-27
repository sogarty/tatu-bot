"""Separate portfolio browsing categories from descriptive tags."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_type = postgresql.JSONB().with_variant(sa.JSON(), "sqlite")
    with op.batch_alter_table("portfolio_item") as batch_op:
        batch_op.add_column(
            sa.Column(
                "categories",
                json_type,
                server_default=sa.text("'[]'"),
                nullable=False,
            )
        )

    portfolio = sa.table(
        "portfolio_item",
        sa.column("id", sa.Integer),
        sa.column("tags", json_type),
        sa.column("categories", json_type),
    )
    connection = op.get_bind()
    for item_id, tags in connection.execute(
        sa.select(portfolio.c.id, portfolio.c.tags)
    ):
        valid_categories = {"graphic", "color", "black", "botanical"}
        categories = [tag for tag in (tags or []) if tag in valid_categories]
        connection.execute(
            portfolio.update()
            .where(portfolio.c.id == item_id)
            .values(categories=categories)
        )


def downgrade() -> None:
    with op.batch_alter_table("portfolio_item") as batch_op:
        batch_op.drop_column("categories")
