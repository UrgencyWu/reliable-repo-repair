import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from agent.database import postgres
from agent.repair import dispatch_store, store
from agent.repair.api_models import CreateRepairTask, TaskView
from agent.repair.models import DispatchIntent, RepairRun, RepairTask, ValidationPlan
from agent.repair.state import DispatchStatus, RepairStatus
from agent.users import User

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("registry_db")]


@pytest.fixture
async def task() -> TaskView:
    async with postgres.session() as session:
        owner = User(display_name="Dispatcher Test")
        session.add(owner)
        await session.flush()
        owner_id = owner.id
    body = CreateRepairTask(
        fixture_id="arithmetic", target_commit="a" * 40, failing_command="python3 -m unittest"
    )
    plan: ValidationPlan = {
        "source_path": "/configured",
        "target_argv": ["python3"],
        "regression_argv": [],
        "allowed_patch_paths": ["calc.py"],
    }
    return await store.create_task(owner_id, "dispatch", body, 300, plan)


async def test_concurrent_claims_have_one_owner_and_one_runtime_reference(task: TaskView) -> None:
    results = await asyncio.gather(
        *(dispatch_store.claim_next(f"worker-{index}") for index in range(8))
    )
    claims = [claim for claim in results if claim is not None]
    assert len(claims) == 1
    claim = claims[0]
    assert await dispatch_store.renew_claim(claim.intent.id, uuid4()) is False
    assert await dispatch_store.renew_claim(claim.intent.id, claim.token) is True
    runtime_id = uuid4()
    assert await dispatch_store.record_dispatch(claim.intent.id, uuid4(), runtime_id) is False
    assert await dispatch_store.record_dispatch(claim.intent.id, claim.token, runtime_id) is True
    assert await dispatch_store.record_dispatch(claim.intent.id, claim.token, uuid4()) is False
    assert await dispatch_store.renew_claim(claim.intent.id, claim.token) is False
    async with postgres.session() as session:
        saved = await session.get(RepairRun, claim.run.id)
        assert saved is not None and saved.runtime_run_id == runtime_id
        saved_task = await session.get(RepairTask, task.id)
        assert saved_task is not None and saved_task.status == RepairStatus.PROVISIONING


async def test_expired_claim_is_reconciled_without_restarting_generation(task: TaskView) -> None:
    claim = await dispatch_store.claim_next("crashed-worker")
    assert claim is not None
    async with postgres.session() as session:
        await session.execute(
            update(DispatchIntent)
            .where(DispatchIntent.id == claim.intent.id)
            .values(lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
        )
    assert await dispatch_store.record_dispatch(claim.intent.id, claim.token, uuid4()) is False
    assert await dispatch_store.reconcile_expired_claims() == 1
    assert await dispatch_store.claim_next("replacement-worker") is None
    assert await dispatch_store.record_dispatch(claim.intent.id, claim.token, uuid4()) is False
    async with postgres.session() as session:
        intent = await session.get(DispatchIntent, claim.intent.id)
        assert intent is not None and intent.status == DispatchStatus.RECONCILING
        assert intent.attempt_count == 1


async def test_unknown_create_result_never_becomes_safe_retry(task: TaskView) -> None:
    claim = await dispatch_store.claim_next("worker")
    assert claim is not None
    assert await dispatch_store.record_dispatch_failure(
        claim.intent.id,
        claim.token,
        "connection_lost",
        definitely_not_created=False,
        retryable=True,
    )
    assert await dispatch_store.claim_next("another-worker") is None
    async with postgres.session() as session:
        intent = await session.get(DispatchIntent, claim.intent.id)
        assert intent is not None and intent.status == DispatchStatus.RECONCILING


async def test_safe_retry_waits_for_backoff_and_exhaustion_is_terminal(task: TaskView) -> None:
    for attempt in range(1, 4):
        claim = await dispatch_store.claim_next("worker")
        assert claim is not None and claim.intent.attempt_count == attempt
        assert await dispatch_store.record_dispatch_failure(
            claim.intent.id,
            claim.token,
            "preflight_connection_refused",
            definitely_not_created=True,
            retryable=True,
        )
        assert await dispatch_store.claim_next("too-soon") is None
        if attempt < 3:
            async with postgres.session() as session:
                await session.execute(
                    update(DispatchIntent)
                    .where(DispatchIntent.id == claim.intent.id)
                    .values(next_retry_at=func.clock_timestamp() - timedelta(seconds=1))
                )
    async with postgres.session() as session:
        saved = await session.get(RepairTask, task.id)
        assert saved is not None and saved.status == RepairStatus.FAILED
        assert saved.failure_reason == "dispatch_retry_exhausted"
        intent = await session.scalar(select(DispatchIntent))
        assert intent is not None and intent.status == DispatchStatus.FAILED


async def test_expired_task_is_not_dispatched(task: TaskView) -> None:
    async with postgres.session() as session:
        await session.execute(
            update(RepairTask)
            .where(RepairTask.id == task.id)
            .values(deadline_at=func.clock_timestamp() - timedelta(seconds=1))
        )
    assert await dispatch_store.claim_next("worker") is None
    async with postgres.session() as session:
        saved = await session.get(RepairTask, task.id)
        assert saved is not None and saved.status == RepairStatus.TIMEOUT
