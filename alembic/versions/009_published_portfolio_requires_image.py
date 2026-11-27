"""Require an image source before publishing portfolio work."""

from alembic import op
import sqlalchemy as sa


revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_portfolio_item_published_requires_image"
CONSTRAINT_SQL = (
    "is_published = false "
    "OR (image_url IS NOT NULL AND trim(image_url) <> '') "
    "OR (image_data IS NOT NULL AND image_content_type IS NOT NULL "
    "AND trim(image_content_type) <> '')"
)


def upgrade() -> None:
    # Keep legacy rows with no usable image source out of the public portfolio.
    op.execute(
        sa.text(
            "UPDATE portfolio_item SET is_published = false "
            "WHERE is_published "
            "AND (image_url IS NULL OR trim(image_url) = '') "
            "AND (image_data IS NULL OR image_content_type IS NULL "
            "OR trim(image_content_type) = '')"
        )
    )
    with op.batch_alter_table("portfolio_item") as batch_op:
        batch_op.alter_column(
            "is_published",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.false(),
        )
        batch_op.create_check_constraint(CONSTRAINT_NAME, CONSTRAINT_SQL)


def downgrade() -> None:
    with op.batch_alter_table("portfolio_item") as batch_op:
        batch_op.drop_constraint(CONSTRAINT_NAME, type_="check")
        batch_op.alter_column(
            "is_published",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.true(),
        )
