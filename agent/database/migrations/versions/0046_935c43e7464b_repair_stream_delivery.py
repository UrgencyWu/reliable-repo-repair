"""Repair stream delivery"""

from alembic import op

revision = "935c43e7464b"
down_revision = "14940cd67eb6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE repair_dispatch_intent "
        "ADD COLUMN redis_stream_id text, "
        "ADD COLUMN redis_published_at timestamptz"
    )


def downgrade() -> None:
    raise NotImplementedError
