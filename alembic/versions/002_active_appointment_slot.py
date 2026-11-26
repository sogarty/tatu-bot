"""Allow cancelled appointments to release their date."""

from alembic import op
import sqlalchemy as sa


revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

_ACTIVE_WHERE = sa.text("status IN ('confirmed', 'done')")


def upgrade() -> None:
    # 001 used a table-wide UNIQUE(slot_id), which also blocked cancelled rows.
    # Batch mode recreates the SQLite table while preserving its data.
    bind = op.get_bind()
    unique_constraints = sa.inspect(bind).get_unique_constraints("appointment")
    indexes = sa.inspect(bind).get_indexes("appointment")
    if any(index.get("name") == "uq_appointment_active_slot_id" for index in indexes):
        return
    slot_constraint = next(
        (
            item
            for item in unique_constraints
            if set(item.get("column_names") or ()) == {"slot_id"}
        ),
        None,
    )

    if bind.dialect.name == "sqlite":
        # SQLite reflects the unnamed constraint from migration 001 as name=None.
        # The naming convention gives Alembic a stable name during table rebuild.
        with op.batch_alter_table(
            "appointment",
            recreate="always",
            naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"},
        ) as batch_op:
            batch_op.drop_constraint(
                (slot_constraint or {}).get("name") or "uq_appointment_slot_id",
                type_="unique",
            )
    elif slot_constraint and slot_constraint.get("name"):
        op.drop_constraint(
            slot_constraint["name"], "appointment", type_="unique"
        )

    op.create_index(
        "uq_appointment_active_slot_id",
        "appointment",
        ["slot_id"],
        unique=True,
        postgresql_where=_ACTIVE_WHERE,
        sqlite_where=_ACTIVE_WHERE,
    )


def downgrade() -> None:
    op.drop_index("uq_appointment_active_slot_id", table_name="appointment")
    with op.batch_alter_table("appointment", recreate="always") as batch_op:
        batch_op.create_unique_constraint("uq_appointment_slot_id", ["slot_id"])
