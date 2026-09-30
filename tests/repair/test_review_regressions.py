import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from langgraph_sdk import get_client
from sqlalchemy import func, select, text

from agent.database import postgres
from agent.repair import dispatch_store, execution_store, store
from agent.repair.adapter import OpenSweAgentAdapter
from agent.repair.api_models import CreateRepairTask
from agent.repair.dispatch import RepairDispatcher
from agent.repair.models import DispatchIntent, RepairRun, RepairTask, ValidationPlan
from agent.users import User

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("registry_db")]


async def create_task(key: str) -> None:
    async with postgres.session() as session:
        owner = User(display_name="Review regression")
        session.add(owner)
        await session.flush()
        owner_id = owner.id
    plan: ValidationPlan = {
        "source_path": "/unused",
        "target_argv": ["false"],
        "regression_argv": [],
        "allowed_patch_paths": ["calc.py"],
    }
    await store.create_task(
        owner_id,
        key,
        CreateRepairTask(fixture_id="review", target_commit="a" * 40, failing_command="test"),
        300,
        plan,
    )


async def cross_expiry(
    model: type[DispatchIntent] | type[RepairRun] | type[RepairTask],
    row_id: UUID,
    expires: datetime,
    operation: Callable[[], Awaitable[bool]],
) -> bool:
    async with postgres.session() as holder:
        await holder.scalar(select(model).where(model.id == row_id).with_for_update())
        pid = await holder.scalar(text("select pg_backend_pid()"))
        job = asyncio.create_task(operation())
        try:
            async with asyncio.timeout(5):
                while True:
                    async with postgres.session() as observer:
                        blocked = await observer.scalar(
                            text(
                                "select count(*) from pg_stat_activity where :pid = any(pg_blocking_pids(pid))"
                            ),
                            {"pid": pid},
                        )
                        now = await observer.scalar(select(func.clock_timestamp()))
                    assert isinstance(now, datetime)
                    if blocked and now >= expires:
                        break
                    await asyncio.sleep(0.02)
            assert not job.done()
        except BaseException:
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)
            raise
    return await asyncio.wait_for(job, 5)


@pytest.mark.parametrize("operation", ["record", "renew", "workspace", "failure", "execution"])
@pytest.mark.parametrize("lock_task", [False, True])
async def test_expiry_during_row_lock_rejects_owner(operation: str, lock_task: bool) -> None:
    await create_task("lease")
    claim = await dispatch_store.claim_next("worker", lease_seconds=2)
    assert claim is not None
    expires = claim.intent.lease_expires_at
    model: type[DispatchIntent] | type[RepairRun] | type[RepairTask] = DispatchIntent
    row_id = claim.intent.id
    if operation == "execution":
        assert await dispatch_store.record_dispatch(claim.intent.id, claim.token, uuid4())
        execution = await execution_store.claim_execution("worker", lease_seconds=2)
        assert execution is not None
        expires = execution.run.execution_lease_at
        model, row_id = RepairRun, execution.run.id

        async def call() -> bool:
            return await execution_store.renew_execution(execution)
    else:

        async def call() -> bool:
            if operation == "record":
                return await dispatch_store.record_dispatch(claim.intent.id, claim.token, uuid4())
            if operation == "renew":
                return await dispatch_store.renew_claim(claim.intent.id, claim.token)
            if operation == "workspace":
                return await dispatch_store.record_workspace(
                    claim.intent.id, claim.token, Path("/unused")
                )
            return await dispatch_store.record_dispatch_failure(
                claim.intent.id,
                claim.token,
                "unknown",
                definitely_not_created=False,
                retryable=True,
            )

    if lock_task:
        model, row_id = RepairTask, claim.task.id
    assert expires is not None
    assert not await cross_expiry(model, row_id, expires, call)


async def test_deadline_during_task_lock_rejects_dispatch() -> None:
    await create_task("deadline")
    claim = await dispatch_store.claim_next("worker")
    assert claim is not None
    async with postgres.session() as session:
        task = await session.get(RepairTask, claim.task.id)
        assert task is not None
        now = await session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        task.deadline_at = expires = now + timedelta(seconds=2)

    async def call() -> bool:
        return await dispatch_store.record_dispatch(claim.intent.id, claim.token, uuid4())

    assert not await cross_expiry(RepairTask, claim.task.id, expires, call)


class DuplicateAdapter(OpenSweAgentAdapter):
    lookups: int = 0

    async def find_run(self, run: RepairRun, intent_id: UUID) -> UUID | None:
        self.lookups += 1
        raise ValueError("Multiple Runtime runs found for one dispatch intent")


class RecordingDispatcher(RepairDispatcher):
    async def dispatch(self, claim: dispatch_store.Claim) -> None:
        self.dispatched = claim


async def test_reconciliation_conflict_does_not_block_other_tasks() -> None:
    await create_task("poison")
    first = await dispatch_store.claim_next("worker")
    assert first is not None
    assert await dispatch_store.record_dispatch_failure(
        first.intent.id, first.token, "unknown", definitely_not_created=False, retryable=True
    )
    await create_task("healthy")
    async with get_client(url="http://127.0.0.1:9") as client:
        adapter = DuplicateAdapter(client)
        worker = RecordingDispatcher(adapter, "replacement")
        await worker.tick()
        assert worker.dispatched.task.id != first.task.id
        await worker.tick()
        assert adapter.lookups == 1
    async with postgres.session() as session:
        intent = await session.get(DispatchIntent, first.intent.id)
        assert intent is not None and intent.status == "RECONCILING"
        assert intent.attempt_count == 1
        assert (
            intent.last_error
            == "reconciliation_conflict: Multiple Runtime runs found for one dispatch intent"
        )
        now = await session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        assert intent.next_retry_at > now
