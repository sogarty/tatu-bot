"""Allow Mini App clients to store uploaded reference images in PostgreSQL."""

from alembic import op
import sqlalchemy as sa


revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("request_reference", sa.Column("image_data", sa.LargeBinary(), nullable=True))
    op.add_column(
        "request_reference",
        sa.Column("image_content_type", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "request_reference",
        sa.Column("has_uploaded_image", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("request_reference", "has_uploaded_image")
    op.drop_column("request_reference", "image_content_type")
    op.drop_column("request_reference", "image_data")
