"""Independent repair validation evidence"""

from alembic import op

revision = "cded32b2d7d8"
down_revision = "7a5b04c6bf56"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE repair_validation (
        id uuid PRIMARY KEY,
        repair_run_id uuid NOT NULL REFERENCES repair_run(id),
        candidate_id uuid NOT NULL REFERENCES repair_candidate(id),
        attempt_no integer NOT NULL CHECK (attempt_no > 0),
        execution_token uuid NOT NULL,
        workspace text NOT NULL,
        status text NOT NULL CHECK (status IN ('RUNNING', 'PASS', 'FAIL', 'ERROR')),
        error_type text,
        checks jsonb NOT NULL DEFAULT '[]'::jsonb,
        manifest jsonb NOT NULL DEFAULT '{}'::jsonb,
        duration_seconds double precision,
        started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        ended_at timestamptz,
        UNIQUE (repair_run_id, attempt_no)
    )""")


def downgrade() -> None:
    raise NotImplementedError
