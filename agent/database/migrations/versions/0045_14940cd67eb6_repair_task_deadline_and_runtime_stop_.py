"""Repair task deadline and runtime stop intent"""

from alembic import op

revision = "14940cd67eb6"
down_revision = "cded32b2d7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE repair_run ADD COLUMN runtime_stop_pending boolean NOT NULL DEFAULT false"
    )
    op.execute("ALTER TABLE repair_run ADD COLUMN runtime_stop_error text")
    op.execute(
        "CREATE INDEX repair_run_pending_stop_idx ON repair_run (ended_at) WHERE runtime_stop_pending"
    )


def downgrade() -> None:
    raise NotImplementedError
