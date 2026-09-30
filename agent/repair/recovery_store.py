from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select

from agent.database import postgres
from agent.repair.models import DispatchIntent, RepairRun, RepairTask, ValidationRecord
from agent.repair.service import transition_task
from agent.repair.state import TERMINAL_STATUSES, DispatchStatus, RepairStatus


@dataclass(frozen=True)
class StopIntent:
    run: RepairRun
    task: RepairTask
    dispatch_id: UUID


async def expire_tasks() -> int:
    async with postgres.session() as session:
        now = await session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        intents = list(
            await session.scalars(
                select(DispatchIntent)
                .join(RepairRun, RepairRun.id == DispatchIntent.repair_run_id)
                .join(RepairTask, RepairTask.id == RepairRun.task_id)
                .where(RepairTask.status.not_in(TERMINAL_STATUSES), RepairTask.deadline_at <= now)
                .with_for_update(of=DispatchIntent, skip_locked=True)
                .limit(100)
            )
        )
        count = 0
        for intent in intents:
            run = await session.scalar(
                select(RepairRun).where(RepairRun.id == intent.repair_run_id).with_for_update()
            )
            assert run is not None
            task = await session.scalar(
                select(RepairTask).where(RepairTask.id == run.task_id).with_for_update()
            )
            assert task is not None
            if task.status in TERMINAL_STATUSES:
                continue
            run.runtime_stop_pending = run.runtime_run_id is not None or intent.status in {
                DispatchStatus.CLAIMED,
                DispatchStatus.RECONCILING,
            }
            run.execution_token = None
            run.execution_owner = None
            run.execution_lease_at = None
            run.ended_at = now
            task.failure_reason = (
                "task_deadline_create_outcome_unknown"
                if run.runtime_stop_pending and run.runtime_run_id is None
                else "task_deadline"
            )
            task.updated_at = now
            intent.status = DispatchStatus.FAILED
            intent.lease_token = None
            intent.last_error = task.failure_reason
            records = await session.scalars(
                select(ValidationRecord).where(
                    ValidationRecord.repair_run_id == run.id, ValidationRecord.status == "RUNNING"
                )
            )
            for record in records:
                record.status = "ERROR"
                record.error_type = "task_deadline"
                record.ended_at = now
            await transition_task(session, task, run, RepairStatus.TIMEOUT)
            count += 1
        return count


async def pending_stops() -> list[StopIntent]:
    async with postgres.session() as session:
        rows = await session.execute(
            select(RepairRun, RepairTask, DispatchIntent.id)
            .join(RepairTask, RepairTask.id == RepairRun.task_id)
            .join(DispatchIntent, DispatchIntent.repair_run_id == RepairRun.id)
            .where(RepairRun.runtime_stop_pending.is_(True))
            .order_by(RepairRun.ended_at)
            .limit(20)
        )
        return [StopIntent(run, task, dispatch_id) for run, task, dispatch_id in rows.tuples()]


async def record_stop(
    run_id: UUID, *, finished: bool, error: str | None = None, runtime_id: UUID | None = None
) -> None:
    async with postgres.session() as session:
        run = await session.scalar(
            select(RepairRun).where(RepairRun.id == run_id).with_for_update()
        )
        if run is None or not run.runtime_stop_pending:
            return
        if runtime_id is not None:
            if run.runtime_run_id not in {None, runtime_id}:
                raise ValueError("Timeout reconciliation found a conflicting Runtime run")
            run.runtime_run_id = runtime_id
        run.runtime_stop_pending = not finished
        run.runtime_stop_error = error
