"""Separate portfolio folders from tattoo placement."""

from alembic import op
import sqlalchemy as sa


revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "portfolio_item",
        sa.Column(
            "folder",
            sa.String(length=80),
            server_default="Без папки",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("portfolio_item", "folder")
