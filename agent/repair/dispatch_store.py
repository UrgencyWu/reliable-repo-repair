from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid7

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.database import postgres
from agent.repair.models import DispatchIntent, RepairRun, RepairTask
from agent.repair.service import append_event, transition_task
from agent.repair.state import TERMINAL_STATUSES, DispatchStatus, RepairStatus


@dataclass(frozen=True)
class Claim:
    intent: DispatchIntent
    run: RepairRun
    task: RepairTask
    token: UUID


async def claim_next(worker_id: str, lease_seconds: int = 30) -> Claim | None:
    if not worker_id or lease_seconds <= 0:
        raise ValueError("Claim requires a worker and positive lease")
    async with postgres.session() as session:
        now = await session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        intent = await session.scalar(
            select(DispatchIntent)
            .where(
                DispatchIntent.status == DispatchStatus.PENDING, DispatchIntent.next_retry_at <= now
            )
            .order_by(DispatchIntent.next_retry_at, DispatchIntent.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if intent is None:
            return None
        return await _claim_locked(session, intent, worker_id, lease_seconds)


async def claim_intent(intent_id: UUID, worker_id: str, lease_seconds: int = 30) -> Claim | None:
    if not worker_id or lease_seconds <= 0:
        raise ValueError("Claim requires a worker and positive lease")
    async with postgres.session() as session:
        intent = await session.scalar(
            select(DispatchIntent)
            .where(
                DispatchIntent.id == intent_id,
                DispatchIntent.status == DispatchStatus.PENDING,
                DispatchIntent.next_retry_at <= func.clock_timestamp(),
            )
            .with_for_update()
        )
        if intent is None:
            return None
        return await _claim_locked(session, intent, worker_id, lease_seconds)


async def _claim_locked(
    session: AsyncSession, intent: DispatchIntent, worker_id: str, lease_seconds: int
) -> Claim | None:
    run = await session.scalar(
        select(RepairRun).where(RepairRun.id == intent.repair_run_id).with_for_update()
    )
    assert run is not None
    task = await session.scalar(
        select(RepairTask).where(RepairTask.id == run.task_id).with_for_update()
    )
    assert task is not None
    now = await session.scalar(select(func.clock_timestamp()))
    assert isinstance(now, datetime)
    if task.status in TERMINAL_STATUSES:
        intent.status = DispatchStatus.FAILED
        intent.last_error = "task_already_terminal"
        return None
    if task.deadline_at <= now:
        intent.status = DispatchStatus.FAILED
        intent.last_error = "task_deadline"
        task.failure_reason = "task_deadline"
        task.updated_at = now
        await transition_task(session, task, run, RepairStatus.TIMEOUT)
        return None
    if task.status == RepairStatus.QUEUED:
        await transition_task(
            session,
            task,
            run,
            RepairStatus.PROVISIONING,
            {"queue_wait_seconds": max(0.0, (now - task.created_at).total_seconds())},
        )
        task.updated_at = now
    intent.status = DispatchStatus.CLAIMED
    intent.attempt_count += 1
    intent.claimed_by = worker_id
    intent.claimed_at = now
    intent.lease_expires_at = now + timedelta(seconds=lease_seconds)
    token = uuid7()
    intent.lease_token = token
    await session.flush()
    return Claim(intent=intent, run=run, task=task, token=token)


async def owned_claim(session: AsyncSession, intent_id: UUID, token: UUID) -> Claim | None:
    intent = await session.scalar(
        select(DispatchIntent).where(DispatchIntent.id == intent_id).with_for_update()
    )
    if intent is None:
        return None
    run = await session.scalar(
        select(RepairRun).where(RepairRun.id == intent.repair_run_id).with_for_update()
    )
    assert run is not None
    task = await session.scalar(
        select(RepairTask).where(RepairTask.id == run.task_id).with_for_update()
    )
    assert task is not None
    # A pre-lock timestamp cannot fence an owner that expires while waiting for any row.
    now = await session.scalar(select(func.clock_timestamp()))
    assert isinstance(now, datetime)
    if (
        intent.status != DispatchStatus.CLAIMED
        or intent.lease_token != token
        or intent.lease_expires_at is None
        or intent.lease_expires_at <= now
        or task.status != RepairStatus.PROVISIONING
        or task.deadline_at <= now
    ):
        return None
    return Claim(intent, run, task, token)


async def record_dispatch(intent_id: UUID, token: UUID, runtime_run_id: UUID) -> bool:
    async with postgres.session() as session:
        claim = await owned_claim(session, intent_id, token)
        if claim is None:
            return False
        intent, run, task = claim.intent, claim.run, claim.task
        now = await session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        run.runtime_run_id = runtime_run_id
        run.started_at = now
        intent.status = DispatchStatus.DISPATCHED
        intent.last_error = None
        task.updated_at = now
        await append_event(
            session,
            task,
            run,
            "RUNTIME_STARTED",
            {
                "runtime_run_id": str(runtime_run_id),
                "thread_id": str(run.thread_id),
                "dispatch_attempts": intent.attempt_count,
                "dispatch_seconds": max(0.0, (now - (intent.claimed_at or now)).total_seconds()),
            },
        )
        return True


async def renew_claim(intent_id: UUID, token: UUID, lease_seconds: int = 30) -> bool:
    if lease_seconds <= 0:
        raise ValueError("Lease duration must be positive")
    async with postgres.session() as session:
        claim = await owned_claim(session, intent_id, token)
        if claim is None:
            return False
        intent = claim.intent
        now = await session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        intent.lease_expires_at = now + timedelta(seconds=lease_seconds)
        return True


async def record_workspace(intent_id: UUID, token: UUID, workspace: Path) -> bool:
    async with postgres.session() as session:
        claim = await owned_claim(session, intent_id, token)
        if claim is None:
            return False
        run, task = claim.run, claim.task
        if run.agent_workspace not in {None, str(workspace)}:
            raise ValueError("Repair run already has a different workspace")
        if run.agent_workspace is None:
            await append_event(
                session,
                task,
                run,
                "WORKSPACE_READY",
                {"workspace_id": f"{run.id}/agent", "provider": "trusted_local_checkout"},
            )
        run.agent_workspace = str(workspace)
        return True


async def unresolved_dispatches() -> list[tuple[DispatchIntent, RepairRun, RepairTask]]:
    async with postgres.session() as session:
        rows = await session.execute(
            select(DispatchIntent, RepairRun, RepairTask)
            .join(RepairRun, RepairRun.id == DispatchIntent.repair_run_id)
            .join(RepairTask, RepairTask.id == RepairRun.task_id)
            .where(
                DispatchIntent.status == DispatchStatus.RECONCILING,
                DispatchIntent.next_retry_at <= func.clock_timestamp(),
                RepairTask.status.not_in(TERMINAL_STATUSES),
            )
            .order_by(DispatchIntent.created_at)
            .limit(20)
        )
        return [(intent, run, task) for intent, run, task in rows.tuples()]


async def record_reconciled(intent_id: UUID, runtime_run_id: UUID) -> bool:
    async with postgres.session() as session:
        now = await session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        intent = await session.scalar(
            select(DispatchIntent)
            .where(
                DispatchIntent.id == intent_id,
                DispatchIntent.status == DispatchStatus.RECONCILING,
            )
            .with_for_update()
        )
        if intent is None:
            return False
        run = await session.scalar(
            select(RepairRun).where(RepairRun.id == intent.repair_run_id).with_for_update()
        )
        assert run is not None
        task = await session.scalar(
            select(RepairTask).where(RepairTask.id == run.task_id).with_for_update()
        )
        assert task is not None
        now = await session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        if task.status in TERMINAL_STATUSES or task.deadline_at <= now:
            return False
        if run.runtime_run_id not in {None, runtime_run_id}:
            raise ValueError("Repair run already has a different Runtime run")
        run.runtime_run_id = runtime_run_id
        run.started_at = run.started_at or intent.claimed_at or now
        intent.status = DispatchStatus.DISPATCHED
        intent.last_error = None
        task.updated_at = now
        await append_event(
            session,
            task,
            run,
            "RUNTIME_RECONCILED",
            {
                "runtime_run_id": str(runtime_run_id),
                "thread_id": str(run.thread_id),
                "dispatch_attempts": intent.attempt_count,
                "reconciliation_seconds": max(
                    0.0, (now - (intent.claimed_at or now)).total_seconds()
                ),
            },
        )
        return True


async def reconcile_expired_claims() -> int:
    async with postgres.session() as session:
        now = await session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        intents = list(
            await session.scalars(
                select(DispatchIntent)
                .where(
                    DispatchIntent.status == DispatchStatus.CLAIMED,
                    DispatchIntent.lease_expires_at <= now,
                )
                .with_for_update(skip_locked=True)
                .limit(100)
            )
        )
        for intent in intents:
            intent.status = DispatchStatus.RECONCILING
            intent.last_error = "claim_expired_create_outcome_unknown"
        return len(intents)


async def record_dispatch_failure(
    intent_id: UUID,
    token: UUID,
    error: str,
    *,
    definitely_not_created: bool,
    retryable: bool,
    max_attempts: int = 3,
) -> bool:
    async with postgres.session() as session:
        claim = await owned_claim(session, intent_id, token)
        if claim is None:
            return False
        intent, run, task = claim.intent, claim.run, claim.task
        now = await session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        intent.last_error = error
        if not definitely_not_created:
            intent.status = DispatchStatus.RECONCILING
            return True
        if task.status in TERMINAL_STATUSES:
            intent.status = DispatchStatus.FAILED
            return False
        if task.deadline_at <= now:
            intent.status = DispatchStatus.FAILED
            task.failure_reason = "task_deadline"
            task.updated_at = now
            await transition_task(session, task, run, RepairStatus.TIMEOUT)
        elif retryable and intent.attempt_count < max_attempts:
            intent.status = DispatchStatus.PENDING
            intent.redis_stream_id = None
            intent.redis_published_at = None
            jitter = (intent.id.int % 1000) / 1000
            intent.next_retry_at = now + timedelta(
                seconds=min(2**intent.attempt_count, 30) + jitter
            )
        else:
            intent.status = DispatchStatus.FAILED
            task.failure_reason = "dispatch_retry_exhausted" if retryable else error
            task.updated_at = now
            await transition_task(session, task, run, RepairStatus.FAILED)
        return True


async def defer_reconciliation_conflict(intent_id: UUID, error: str) -> None:
    async with postgres.session() as session:
        intent = await session.scalar(
            select(DispatchIntent).where(DispatchIntent.id == intent_id).with_for_update()
        )
        if intent is None or intent.status != DispatchStatus.RECONCILING:
            return
        now = await session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        intent.last_error = "reconciliation_conflict: " + error[:1000]
        intent.next_retry_at = now + timedelta(seconds=30)
