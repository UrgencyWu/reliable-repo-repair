from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agent.repair.models import EventPayload
from agent.repair.state import DispatchStatus, RepairStatus


class CreateRepairTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    target_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    failing_command: str = Field(min_length=1, max_length=512)
    constraints: str = Field(default="", max_length=4000)


class TaskView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trace_id: UUID
    fixture_id: str
    target_commit: str
    failing_command: str
    constraints: str
    status: RepairStatus
    version: int
    failure_reason: str | None
    deadline_at: datetime
    created_at: datetime
    updated_at: datetime


class RunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    attempt_no: int
    thread_id: UUID
    dispatch_attempts: int
    dispatch_status: DispatchStatus
    runtime_run_id: UUID | None
    runtime_stop_pending: bool
    runtime_stop_error: str | None
    started_at: datetime | None
    ended_at: datetime | None


class EventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sequence: int
    event: str
    payload: EventPayload
    occurred_at: datetime


class TaskPage(BaseModel):
    items: list[TaskView]
    limit: int
    offset: int
    has_more: bool


class RepairError(BaseModel):
    code: str
    message: str


class CandidateView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    repair_run_id: UUID
    base_commit: str
    sha256: str
    files_changed: list[str]
    created_at: datetime
    size_bytes: int


class ValidationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    repair_run_id: UUID
    candidate_id: UUID
    attempt_no: int
    status: Literal["RUNNING", "PASS", "FAIL", "ERROR"]
    error_type: str | None
    duration_seconds: float | None
    started_at: datetime
    ended_at: datetime | None


class CheckView(BaseModel):
    name: str
    argv: list[str]
    exit_code: int
    output: str
    truncated: bool
    timed_out: bool
    duration_seconds: float
    stored_output_bytes: int


class ValidationView(ValidationSummary):
    checks: list[CheckView]
    manifest: dict[str, str]


class ArtifactResult(BaseModel):
    candidate: CandidateView | None
    validations: list[ValidationView]
    log_limit_bytes: int


class TaskDetail(BaseModel):
    task: TaskView
    runs: list[RunView]
    events: list[EventView]
    candidates: list[CandidateView]
    validations: list[ValidationSummary]
