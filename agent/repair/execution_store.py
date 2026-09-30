import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid7

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from agent.database import postgres
from agent.repair.adapter import MAX_PATCH_BYTES, Candidate
from agent.repair.models import CandidateArtifact, RepairRun, RepairTask
from agent.repair.service import transition_task
from agent.repair.state import RepairStatus


@dataclass(frozen=True)
class ExecutionClaim:
    task: RepairTask
    run: RepairRun
    token: UUID


async def claim_execution(worker_id: str, lease_seconds: int = 30) -> ExecutionClaim | None:
    if not worker_id or lease_seconds <= 0:
        raise ValueError("Execution claim requires a worker and positive lease")
    async with postgres.session() as session:
        now = await session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        run = await session.scalar(
            select(RepairRun)
            .join(RepairTask, RepairTask.id == RepairRun.task_id)
            .where(
                RepairTask.status.in_([RepairStatus.PROVISIONING, RepairStatus.VALIDATING]),
                RepairTask.deadline_at > now,
                RepairRun.runtime_run_id.is_not(None),
                or_(RepairRun.execution_lease_at.is_(None), RepairRun.execution_lease_at <= now),
            )
            .order_by(RepairRun.execution_lease_at.asc().nulls_first(), RepairRun.created_at)
            .with_for_update(of=RepairRun, skip_locked=True)
            .limit(1)
        )
        if run is None:
            return None
        task = await session.get(RepairTask, run.task_id)
        assert task is not None
        token = uuid7()
        run.execution_owner = worker_id
        run.execution_token = token
        run.execution_lease_at = now + timedelta(seconds=lease_seconds)
        await session.flush()
        return ExecutionClaim(task, run, token)


async def owned_run(session: AsyncSession, claim: ExecutionClaim) -> RepairRun | None:
    run = await session.scalar(
        select(RepairRun).where(RepairRun.id == claim.run.id).with_for_update()
    )
    if run is None:
        return None
    task = await session.scalar(
        select(RepairTask).where(RepairTask.id == run.task_id).with_for_update()
    )
    assert task is not None
    now = await session.scalar(select(func.clock_timestamp()))
    assert isinstance(now, datetime)
    if (
        run.execution_token != claim.token
        or run.execution_lease_at is None
        or run.execution_lease_at <= now
        or task.status not in {RepairStatus.PROVISIONING, RepairStatus.VALIDATING}
        or task.deadline_at <= now
    ):
        return None
    return run


async def renew_execution(claim: ExecutionClaim, lease_seconds: int = 30) -> bool:
    if lease_seconds <= 0:
        raise ValueError("Execution lease duration must be positive")
    async with postgres.session() as session:
        run = await owned_run(session, claim)
        if run is None:
            return False
        now = await session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        run.execution_lease_at = now + timedelta(seconds=lease_seconds)
        return True


async def release_execution(claim: ExecutionClaim) -> None:
    async with postgres.session() as session:
        run = await owned_run(session, claim)
        if run is not None:
            run.execution_lease_at = await session.scalar(select(func.clock_timestamp()))
            run.execution_token = None
            run.execution_owner = None


async def store_candidate(claim: ExecutionClaim, candidate: Candidate) -> bool:
    if (
        not 0 < len(candidate.patch) <= MAX_PATCH_BYTES
        or hashlib.sha256(candidate.patch).hexdigest() != candidate.sha256
    ):
        raise ValueError("Candidate hash or size is invalid")
    async with postgres.session() as session:
        run = await owned_run(session, claim)
        if run is None:
            return False
        task = await session.scalar(
            select(RepairTask).where(RepairTask.id == run.task_id).with_for_update()
        )
        assert task is not None
        now = await session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        if task.status != RepairStatus.PROVISIONING or task.deadline_at <= now:
            return False
        if candidate.base_commit != task.target_commit:
            raise ValueError("Candidate base does not match the repair task")
        if not candidate.files_changed or any(
            path not in task.validation_plan["allowed_patch_paths"]
            for path in candidate.files_changed
        ):
            raise ValueError("Candidate file list is outside the task patch policy")
        artifact = await session.scalar(
            insert(CandidateArtifact)
            .values(
                id=uuid7(),
                repair_run_id=run.id,
                base_commit=candidate.base_commit,
                sha256=candidate.sha256,
                patch=candidate.patch,
                files_changed=candidate.files_changed,
            )
            .on_conflict_do_nothing(index_elements=[CandidateArtifact.repair_run_id])
            .returning(CandidateArtifact)
        )
        if artifact is None:
            artifact = await session.scalar(
                select(CandidateArtifact).where(CandidateArtifact.repair_run_id == run.id)
            )
            assert artifact is not None
            if artifact.sha256 != candidate.sha256:
                raise ValueError("A different immutable candidate already exists")
        task.updated_at = now
        await transition_task(
            session,
            task,
            run,
            RepairStatus.VALIDATING,
            {"artifact_id": str(artifact.id), "patch_sha256": candidate.sha256},
        )
        return True


async def fail_execution(claim: ExecutionClaim, reason: str) -> bool:
    async with postgres.session() as session:
        run = await owned_run(session, claim)
        if run is None:
            return False
        task = await session.scalar(
            select(RepairTask).where(RepairTask.id == run.task_id).with_for_update()
        )
        assert task is not None
        if task.status not in {RepairStatus.PROVISIONING, RepairStatus.VALIDATING}:
            return False
        now = await session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        task.failure_reason = reason
        task.updated_at = now
        run.ended_at = now
        await transition_task(session, task, run, RepairStatus.FAILED)
        return True
