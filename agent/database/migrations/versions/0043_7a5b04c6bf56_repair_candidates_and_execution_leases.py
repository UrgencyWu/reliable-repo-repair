"""Repair candidates and execution leases"""

from alembic import op

revision = "7a5b04c6bf56"
down_revision = "9edff2616cd3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in (
        "ALTER TABLE repair_run ADD COLUMN execution_owner text, ADD COLUMN execution_token uuid, ADD COLUMN execution_lease_at timestamptz",
        "CREATE INDEX repair_run_execution_lease ON repair_run (execution_lease_at)",
        """CREATE TABLE repair_candidate (
            id uuid PRIMARY KEY,
            repair_run_id uuid NOT NULL UNIQUE REFERENCES repair_run(id),
            base_commit text NOT NULL CHECK (base_commit ~ '^[0-9a-f]{40}$'),
            sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            patch bytea NOT NULL CHECK (octet_length(patch) BETWEEN 1 AND 5242880),
            files_changed jsonb NOT NULL CHECK (jsonb_typeof(files_changed) = 'array'),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        )""",
        """CREATE FUNCTION reject_candidate_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'repair candidate is immutable'; END $$""",
        "CREATE TRIGGER repair_candidate_immutable BEFORE UPDATE OR DELETE ON repair_candidate FOR EACH ROW EXECUTE FUNCTION reject_candidate_mutation()",
    ):
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError
