from datetime import datetime
from typing import TypedDict
from uuid import UUID, uuid7

from sqlalchemy import Enum, ForeignKey, LargeBinary, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agent.database.orm import NOW, Base
from agent.repair.state import DispatchStatus, RepairStatus

type EventPayload = dict[str, str | int | float | bool | None]


class ValidationPlan(TypedDict):
    source_path: str
    target_argv: list[str]
    regression_argv: list[list[str]]
    allowed_patch_paths: list[str]


class CheckPayload(TypedDict):
    name: str
    argv: list[str]
    exit_code: int
    output: str
    truncated: bool
    timed_out: bool
    duration_seconds: float


class RepairTask(Base):
    __tablename__ = "repair_task"

    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    fixture_id: Mapped[str]
    target_commit: Mapped[str]
    failing_command: Mapped[str]
    constraints: Mapped[str]
    idempotency_key: Mapped[str]
    input_sha256: Mapped[str]
    validation_plan: Mapped[ValidationPlan] = mapped_column(JSONB)
    deadline_at: Mapped[datetime]
    id: Mapped[UUID] = mapped_column(primary_key=True, default_factory=uuid7)
    trace_id: Mapped[UUID] = mapped_column(default_factory=uuid7)
    status: Mapped[RepairStatus] = mapped_column(
        Enum(RepairStatus, native_enum=False, length=20), default=RepairStatus.RECEIVED
    )
    version: Mapped[int] = mapped_column(default=0)
    failure_reason: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=NOW, init=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=NOW, init=False)


class RepairRun(Base):
    __tablename__ = "repair_run"

    task_id: Mapped[UUID] = mapped_column(ForeignKey("repair_task.id"))
    id: Mapped[UUID] = mapped_column(primary_key=True, default_factory=uuid7)
    attempt_no: Mapped[int] = mapped_column(default=1)
    thread_id: Mapped[UUID] = mapped_column(default_factory=uuid7)
    runtime_run_id: Mapped[UUID | None] = mapped_column(default=None)
    agent_workspace: Mapped[str | None] = mapped_column(default=None)
    runtime_stop_pending: Mapped[bool] = mapped_column(default=False)
    runtime_stop_error: Mapped[str | None] = mapped_column(default=None)
    execution_owner: Mapped[str | None] = mapped_column(default=None)
    execution_token: Mapped[UUID | None] = mapped_column(default=None)
    execution_lease_at: Mapped[datetime | None] = mapped_column(default=None)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    ended_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=NOW, init=False)


class DispatchIntent(Base):
    __tablename__ = "repair_dispatch_intent"

    repair_run_id: Mapped[UUID] = mapped_column(ForeignKey("repair_run.id"), unique=True)
    id: Mapped[UUID] = mapped_column(primary_key=True, default_factory=uuid7)
    status: Mapped[DispatchStatus] = mapped_column(
        Enum(DispatchStatus, native_enum=False, length=20), default=DispatchStatus.PENDING
    )
    attempt_count: Mapped[int] = mapped_column(default=0)
    next_retry_at: Mapped[datetime] = mapped_column(server_default=NOW, init=False)
    claimed_by: Mapped[str | None] = mapped_column(default=None)
    claimed_at: Mapped[datetime | None] = mapped_column(default=None)
    lease_expires_at: Mapped[datetime | None] = mapped_column(default=None)
    lease_token: Mapped[UUID | None] = mapped_column(default=None)
    last_error: Mapped[str | None] = mapped_column(default=None)
    redis_stream_id: Mapped[str | None] = mapped_column(default=None)
    redis_published_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=NOW, init=False)


class RepairEvent(Base):
    __tablename__ = "repair_event"

    task_id: Mapped[UUID] = mapped_column(ForeignKey("repair_task.id"))
    repair_run_id: Mapped[UUID] = mapped_column(ForeignKey("repair_run.id"))
    sequence: Mapped[int]
    event: Mapped[str] = mapped_column(Text)
    id: Mapped[UUID] = mapped_column(primary_key=True, default_factory=uuid7)
    payload: Mapped[EventPayload] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default_factory=dict
    )
    occurred_at: Mapped[datetime] = mapped_column(server_default=NOW, init=False)


class CandidateArtifact(Base):
    __tablename__ = "repair_candidate"

    repair_run_id: Mapped[UUID] = mapped_column(ForeignKey("repair_run.id"), unique=True)
    base_commit: Mapped[str]
    sha256: Mapped[str]
    patch: Mapped[bytes] = mapped_column(LargeBinary)
    files_changed: Mapped[list[str]] = mapped_column(JSONB)
    id: Mapped[UUID] = mapped_column(primary_key=True, default_factory=uuid7)
    created_at: Mapped[datetime] = mapped_column(server_default=NOW, init=False)


class ValidationRecord(Base):
    __tablename__ = "repair_validation"

    repair_run_id: Mapped[UUID] = mapped_column(ForeignKey("repair_run.id"))
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("repair_candidate.id"))
    attempt_no: Mapped[int]
    execution_token: Mapped[UUID]
    workspace: Mapped[str]
    id: Mapped[UUID] = mapped_column(primary_key=True, default_factory=uuid7)
    status: Mapped[str] = mapped_column(default="RUNNING")
    error_type: Mapped[str | None] = mapped_column(default=None)
    checks: Mapped[list[CheckPayload]] = mapped_column(JSONB, default_factory=list)
    manifest: Mapped[dict[str, str]] = mapped_column(JSONB, default_factory=dict)
    duration_seconds: Mapped[float | None] = mapped_column(default=None)
    started_at: Mapped[datetime] = mapped_column(server_default=NOW, init=False)
    ended_at: Mapped[datetime | None] = mapped_column(default=None)
