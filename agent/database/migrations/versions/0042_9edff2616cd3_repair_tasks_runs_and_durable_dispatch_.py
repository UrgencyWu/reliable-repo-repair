"""Repair tasks runs and durable dispatch intents"""

from alembic import op

revision = "9edff2616cd3"
down_revision = "ec8eaeed6158"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = """
        CREATE TABLE repair_task (
            id uuid PRIMARY KEY,
            owner_id uuid NOT NULL REFERENCES users(id),
            fixture_id text NOT NULL,
            target_commit text NOT NULL CHECK (target_commit ~ '^[0-9a-f]{40}$'),
            failing_command text NOT NULL,
            constraints text NOT NULL,
            idempotency_key text NOT NULL,
            input_sha256 text NOT NULL CHECK (input_sha256 ~ '^[0-9a-f]{64}$'),
            validation_plan jsonb NOT NULL,
            deadline_at timestamptz NOT NULL,
            trace_id uuid NOT NULL,
            status varchar(20) NOT NULL CHECK (status IN (
                'RECEIVED', 'QUEUED', 'PROVISIONING', 'VALIDATING', 'COMPLETED', 'FAILED', 'TIMEOUT'
            )),
            version integer NOT NULL DEFAULT 0 CHECK (version >= 0),
            failure_reason text,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (owner_id, idempotency_key)
        );
        CREATE INDEX repair_task_owner_recent ON repair_task (owner_id, created_at DESC, id DESC);
        CREATE INDEX repair_task_status ON repair_task (status, deadline_at);
        CREATE TABLE repair_run (
            id uuid PRIMARY KEY,
            task_id uuid NOT NULL REFERENCES repair_task(id),
            attempt_no integer NOT NULL CHECK (attempt_no > 0),
            thread_id uuid NOT NULL UNIQUE,
            runtime_run_id uuid,
            agent_workspace text,
            started_at timestamptz,
            ended_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (task_id, attempt_no)
        );
        CREATE TABLE repair_dispatch_intent (
            id uuid PRIMARY KEY,
            repair_run_id uuid NOT NULL UNIQUE REFERENCES repair_run(id),
            status varchar(20) NOT NULL CHECK (status IN (
                'PENDING', 'CLAIMED', 'RECONCILING', 'DISPATCHED', 'FAILED'
            )),
            attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            next_retry_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            claimed_by text,
            claimed_at timestamptz,
            lease_expires_at timestamptz,
            lease_token uuid,
            last_error text,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CHECK (status != 'CLAIMED' OR (
                claimed_by IS NOT NULL AND claimed_at IS NOT NULL
                AND lease_expires_at IS NOT NULL AND lease_token IS NOT NULL
            ))
        );
        CREATE INDEX repair_dispatch_due ON repair_dispatch_intent (status, next_retry_at, id);
        CREATE INDEX repair_dispatch_lease ON repair_dispatch_intent (lease_expires_at)
            WHERE status = 'CLAIMED';
        CREATE TABLE repair_event (
            id uuid PRIMARY KEY,
            task_id uuid NOT NULL REFERENCES repair_task(id),
            repair_run_id uuid NOT NULL REFERENCES repair_run(id),
            sequence integer NOT NULL CHECK (sequence > 0),
            event text NOT NULL,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (task_id, sequence)
        )
    """
    for statement in statements.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError
