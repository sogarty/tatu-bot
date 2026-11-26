"""Correct captions for two identifiable seeded portfolio images."""

from alembic import op
import sqlalchemy as sa


revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    portfolio = sa.table(
        "portfolio_item",
        sa.column("title", sa.String),
        sa.column("place", sa.String),
        sa.column("image_url", sa.String),
        sa.column("tags", sa.JSON),
    )
    op.execute(
        portfolio.update()
        .where(
            sa.and_(
                portfolio.c.image_url == "assets/portfolio/k12.jpg",
                portfolio.c.title == "Чёрный рукав",
            )
        )
        .values(
            title="Крылья и хризантема",
            place="Рука",
            tags=["japanese", "black", "floral"],
        )
    )
    op.execute(
        portfolio.update()
        .where(
            sa.and_(
                portfolio.c.image_url == "assets/portfolio/k14.jpg",
                portfolio.c.title == "Пантера",
            )
        )
        .values(
            title="Пятнистая кошка",
            place="Бедро",
            tags=["black", "animal", "ornamental"],
        )
    )


def downgrade() -> None:
    portfolio = sa.table(
        "portfolio_item",
        sa.column("title", sa.String),
        sa.column("image_url", sa.String),
        sa.column("tags", sa.JSON),
    )
    op.execute(
        portfolio.update()
        .where(
            sa.and_(
                portfolio.c.image_url == "assets/portfolio/k12.jpg",
                portfolio.c.title == "Крылья и хризантема",
            )
        )
        .values(title="Чёрный рукав", tags=["black"])
    )
    op.execute(
        portfolio.update()
        .where(
            sa.and_(
                portfolio.c.image_url == "assets/portfolio/k14.jpg",
                portfolio.c.title == "Пятнистая кошка",
            )
        )
        .values(title="Пантера", tags=["black"])
    )
