"""Persist portfolio entries and their uploaded image bytes."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


SEED_ITEMS = [
    ("Пион", "Бедро", "k01", ["color", "botanical"]),
    ("Любовь", "Кожа", "k02", ["graphic"]),
    ("Ботаника", "Предплечье", "k03", ["graphic", "botanical"]),
    ("Фея", "Плечо", "k04", ["graphic"]),
    ("Птица и лилии", "Спина", "k05", ["color", "botanical"]),
    ("Пион и жуки", "Плечо", "k06", ["color", "botanical"]),
    ("Осенние цветы", "Рука", "k07", ["color", "botanical"]),
    ("Паук и линии", "Грудь", "k08", ["graphic"]),
    ("Стебли", "Бок", "k09", ["graphic", "botanical"]),
    ("Тонкая линия", "Талия", "k10", ["graphic"]),
    ("Орнаментальный рукав", "Рука", "k11", ["black"]),
    ("Крылья и хризантема", "Рука", "k12", ["japanese", "black", "floral"]),
    ("Чёрный зверь", "Нога", "k13", ["black"]),
    ("Пятнистая кошка", "Бедро", "k14", ["black", "animal", "ornamental"]),
    ("Ветвь", "Рука", "k15", ["graphic", "botanical"]),
    ("Леттеринг", "Предплечье", "k16", ["graphic"]),
]


def upgrade() -> None:
    op.create_table(
        "portfolio_item",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("place", sa.String(length=120), nullable=False),
        sa.Column("image_url", sa.String(length=500), nullable=True),
        sa.Column("image_data", sa.LargeBinary(), nullable=True),
        sa.Column("image_content_type", sa.String(length=100), nullable=True),
        sa.Column("tags", postgresql.JSONB().with_variant(sa.JSON(), "sqlite"), nullable=False),
        sa.Column("is_published", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_portfolio_item_published_sort",
        "portfolio_item",
        ["is_published", "sort_order"],
    )

    bind = op.get_bind()
    table = sa.table(
        "portfolio_item",
        sa.column("title", sa.String),
        sa.column("place", sa.String),
        sa.column("image_url", sa.String),
        sa.column("tags", postgresql.JSONB().with_variant(sa.JSON(), "sqlite")),
        sa.column("is_published", sa.Boolean),
        sa.column("sort_order", sa.Integer),
    )
    bind.execute(
        table.insert(),
        [
            {
                "title": title,
                "place": place,
                "image_url": f"assets/portfolio/{image_id}.jpg",
                "tags": tags,
                "is_published": True,
                "sort_order": index,
            }
            for index, (title, place, image_id, tags) in enumerate(SEED_ITEMS)
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_portfolio_item_published_sort", table_name="portfolio_item")
    op.drop_table("portfolio_item")
