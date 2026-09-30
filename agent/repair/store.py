import hashlib
import json
from datetime import datetime, timedelta
from uuid import UUID, uuid7

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from agent.database import postgres
from agent.repair.api_models import (
    ArtifactResult,
    CandidateView,
    CheckView,
    CreateRepairTask,
    EventView,
    RunView,
    TaskDetail,
    TaskPage,
    TaskView,
    ValidationSummary,
    ValidationView,
)
from agent.repair.models import (
    CandidateArtifact,
    DispatchIntent,
    RepairEvent,
    RepairRun,
    RepairTask,
    ValidationPlan,
    ValidationRecord,
)
from agent.repair.state import RepairStatus, require_transition


class IdempotencyConflict(ValueError):
    pass


async def create_task(
    owner_id: UUID,
    key: str,
    body: CreateRepairTask,
    timeout_seconds: int,
    validation_plan: ValidationPlan,
) -> TaskView:
    digest = hashlib.sha256(
        json.dumps(body.model_dump(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    async with postgres.session() as session:
        now = await session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        task = await session.scalar(
            insert(RepairTask)
            .values(
                id=uuid7(),
                owner_id=owner_id,
                trace_id=uuid7(),
                **body.model_dump(),
                idempotency_key=key,
                input_sha256=digest,
                deadline_at=now + timedelta(seconds=timeout_seconds),
                validation_plan=validation_plan,
                status=RepairStatus.RECEIVED,
                version=0,
            )
            .on_conflict_do_nothing(
                index_elements=[RepairTask.owner_id, RepairTask.idempotency_key]
            )
            .returning(RepairTask)
        )
        if task is None:
            existing = await session.scalar(
                select(RepairTask).where(
                    RepairTask.owner_id == owner_id, RepairTask.idempotency_key == key
                )
            )
            assert existing is not None
            if existing.input_sha256 != digest:
                raise IdempotencyConflict("Idempotency-Key already used with different input")
            return TaskView.model_validate(existing)
        run = RepairRun(task_id=task.id)
        session.add(run)
        await session.flush()
        session.add(DispatchIntent(repair_run_id=run.id))
        session.add(
            RepairEvent(
                task_id=task.id, repair_run_id=run.id, sequence=1, event=RepairStatus.RECEIVED
            )
        )
        await require_transition(task.status, RepairStatus.QUEUED)
        task.status = RepairStatus.QUEUED
        task.version = 2
        task.updated_at = now
        session.add(
            RepairEvent(
                task_id=task.id, repair_run_id=run.id, sequence=2, event=RepairStatus.QUEUED
            )
        )
        await session.flush()
        return TaskView.model_validate(task)


async def get_task(owner_id: UUID, task_id: UUID) -> TaskDetail | None:
    async with postgres.session() as session:
        task = await session.scalar(
            select(RepairTask).where(RepairTask.id == task_id, RepairTask.owner_id == owner_id)
        )
        if task is None:
            return None
        runs = await session.execute(
            select(RepairRun, DispatchIntent)
            .join(DispatchIntent, DispatchIntent.repair_run_id == RepairRun.id)
            .where(RepairRun.task_id == task_id)
            .order_by(RepairRun.attempt_no)
        )
        events = await session.scalars(
            select(RepairEvent).where(RepairEvent.task_id == task_id).order_by(RepairEvent.sequence)
        )
        candidates = await candidate_metadata(session, task_id)
        validations = await session.scalars(
            select(ValidationRecord)
            .options(
                load_only(
                    ValidationRecord.id,
                    ValidationRecord.repair_run_id,
                    ValidationRecord.candidate_id,
                    ValidationRecord.attempt_no,
                    ValidationRecord.status,
                    ValidationRecord.error_type,
                    ValidationRecord.duration_seconds,
                    ValidationRecord.started_at,
                    ValidationRecord.ended_at,
                )
            )
            .join(RepairRun, RepairRun.id == ValidationRecord.repair_run_id)
            .where(RepairRun.task_id == task_id)
            .order_by(ValidationRecord.started_at)
        )
        return TaskDetail(
            task=TaskView.model_validate(task),
            runs=[
                RunView(
                    id=run.id,
                    attempt_no=run.attempt_no,
                    thread_id=run.thread_id,
                    runtime_run_id=run.runtime_run_id,
                    dispatch_attempts=intent.attempt_count,
                    dispatch_status=intent.status,
                    runtime_stop_pending=run.runtime_stop_pending,
                    runtime_stop_error=run.runtime_stop_error,
                    started_at=run.started_at,
                    ended_at=run.ended_at,
                )
                for run, intent in runs.tuples()
            ],
            events=[EventView.model_validate(event) for event in events],
            candidates=candidates,
            validations=[
                ValidationSummary.model_validate(validation) for validation in validations
            ],
        )


async def list_tasks(owner_id: UUID, limit: int, offset: int) -> TaskPage:
    async with postgres.session() as session:
        tasks = list(
            await session.scalars(
                select(RepairTask)
                .where(RepairTask.owner_id == owner_id)
                .order_by(RepairTask.created_at.desc(), RepairTask.id.desc())
                .limit(limit + 1)
                .offset(offset)
            )
        )
        return TaskPage(
            items=[TaskView.model_validate(task) for task in tasks[:limit]],
            limit=limit,
            offset=offset,
            has_more=len(tasks) > limit,
        )


LOG_LIMIT_BYTES = 64 * 1024


async def candidate_metadata(session: AsyncSession, task_id: UUID) -> list[CandidateView]:
    rows = await session.execute(
        select(
            CandidateArtifact.id,
            CandidateArtifact.repair_run_id,
            CandidateArtifact.base_commit,
            CandidateArtifact.sha256,
            CandidateArtifact.files_changed,
            CandidateArtifact.created_at,
            func.octet_length(CandidateArtifact.patch).label("size_bytes"),
        )
        .join(RepairRun, RepairRun.id == CandidateArtifact.repair_run_id)
        .where(RepairRun.task_id == task_id)
        .order_by(CandidateArtifact.created_at)
    )
    return [CandidateView.model_validate(row) for row in rows.mappings()]


async def get_patch(
    owner_id: UUID, task_id: UUID
) -> tuple[TaskView, CandidateArtifact | None] | None:
    async with postgres.session() as session:
        task = await session.scalar(
            select(RepairTask).where(RepairTask.id == task_id, RepairTask.owner_id == owner_id)
        )
        if task is None:
            return None
        candidate = await session.scalar(
            select(CandidateArtifact)
            .join(RepairRun, RepairRun.id == CandidateArtifact.repair_run_id)
            .where(RepairRun.task_id == task_id)
            .order_by(CandidateArtifact.created_at.desc())
            .limit(1)
        )
        return TaskView.model_validate(task), candidate


async def get_artifacts(owner_id: UUID, task_id: UUID) -> ArtifactResult | None:
    async with postgres.session() as session:
        task = await session.scalar(
            select(RepairTask).where(RepairTask.id == task_id, RepairTask.owner_id == owner_id)
        )
        if task is None:
            return None
        candidates = await candidate_metadata(session, task_id)
        records = await session.scalars(
            select(ValidationRecord)
            .join(RepairRun, RepairRun.id == ValidationRecord.repair_run_id)
            .where(RepairRun.task_id == task_id)
            .order_by(ValidationRecord.started_at)
        )
        remaining = LOG_LIMIT_BYTES
        validations: list[ValidationView] = []
        for record in records:
            checks: list[CheckView] = []
            for check in record.checks:
                raw = check["output"].encode()
                output = raw[:remaining].decode(errors="ignore")
                remaining -= len(output.encode())
                checks.append(
                    CheckView(
                        name=check["name"],
                        argv=check["argv"],
                        exit_code=check["exit_code"],
                        output=output,
                        truncated=check["truncated"] or len(raw) > len(output.encode()),
                        timed_out=check["timed_out"],
                        duration_seconds=check["duration_seconds"],
                        stored_output_bytes=len(raw),
                    )
                )
            validations.append(
                ValidationView(
                    **ValidationSummary.model_validate(record).model_dump(),
                    checks=checks,
                    manifest=record.manifest,
                )
            )
        return ArtifactResult(
            candidate=candidates[-1] if candidates else None,
            validations=validations,
            log_limit_bytes=LOG_LIMIT_BYTES,
        )
