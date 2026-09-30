import asyncio
import os
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import cast
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError
from sqlalchemy import func, select, update

from agent.database import postgres
from agent.repair import dispatch_store, store, stream, stream_store
from agent.repair.adapter import RepairAdapter
from agent.repair.api_models import CreateRepairTask
from agent.repair.dispatch import RepairDispatcher
from agent.repair.dispatch_store import Claim
from agent.repair.models import DispatchIntent, RepairRun, RepairTask, ValidationPlan
from agent.repair.state import DispatchStatus, RepairStatus
from agent.repair.stream import RepairStreamTransport
from agent.users import User

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("registry_db")]


@pytest.fixture
async def redis_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Redis]:
    url = os.environ.get("REPAIR_TEST_REDIS_URL")
    if url is None:
        pytest.skip("REPAIR_TEST_REDIS_URL is required for Redis Stream regressions")
    key = f"test:repair:dispatch:{uuid4()}"
    monkeypatch.setattr(stream, "STREAM", key)
    async with Redis.from_url(url, decode_responses=True) as client:
        await client.ping()
        try:
            yield client
        finally:
            await client.delete(key)


async def create_intent(key: str) -> UUID:
    async with postgres.session() as session:
        owner = User(display_name="Redis Stream Test")
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
    task = await store.create_task(owner_id, key, body, 300, plan)
    async with postgres.session() as session:
        intent = await session.scalar(
            select(DispatchIntent)
            .join(RepairRun, RepairRun.id == DispatchIntent.repair_run_id)
            .where(RepairRun.task_id == task.id)
        )
        assert intent is not None
        return intent.id


class RecordingDispatcher(RepairDispatcher):
    def __init__(self, worker_id: str) -> None:
        super().__init__(cast(RepairAdapter, object()), worker_id, database_dispatch=False)
        self.dispatches = 0

    async def dispatch(self, claim: Claim) -> None:
        self.dispatches += 1
        assert await dispatch_store.record_dispatch(claim.intent.id, claim.token, uuid4())


async def consume_message(client: Redis, worker: str) -> tuple[str, dict[str, str]]:
    result = await client.xreadgroup(stream.GROUP, worker, {stream.STREAM: ">"}, count=1)
    assert len(result) == 1 and len(result[0][1]) == 1
    return result[0][1][0]


async def test_stream_transport_publishes_and_dispatches(
    redis_client: Redis,
) -> None:
    intent_id = await create_intent("transport")
    dispatcher = RecordingDispatcher("transport-worker")
    url = os.environ["REPAIR_TEST_REDIS_URL"]
    transport = RepairStreamTransport(url, dispatcher)
    task = asyncio.create_task(transport.run())
    try:

        async def dispatched() -> None:
            while True:
                async with postgres.session() as session:
                    intent = await session.get(DispatchIntent, intent_id)
                    if intent is not None and intent.status == DispatchStatus.DISPATCHED:
                        return
                await asyncio.sleep(0.01)

        try:
            await asyncio.wait_for(dispatched(), timeout=10)
        except TimeoutError:
            async with postgres.session() as session:
                intent = await session.get(DispatchIntent, intent_id)
            raise AssertionError(
                f"intent={intent.status if intent else None}, "
                f"entries={await redis_client.xrange(stream.STREAM)}, "
                f"groups={await redis_client.xinfo_groups(stream.STREAM)}, "
                f"pending={await redis_client.xpending(stream.STREAM, stream.GROUP)}, "
                f"dispatches={dispatcher.dispatches}, task_done={task.done()}"
            ) from None
        assert dispatcher.dispatches == 1
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_publish_failure_after_commit_is_retried(
    redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent_id = await create_intent("publish-failure")
    transport = RepairStreamTransport("redis://unused", RecordingDispatcher("worker"))
    with patch.object(redis_client, "xadd", new=AsyncMock(side_effect=ConnectionError("offline"))):
        with pytest.raises(ConnectionError):
            await transport.publish_due(redis_client)
    async with postgres.session() as session:
        intent = await session.get(DispatchIntent, intent_id)
        assert intent is not None and intent.status == DispatchStatus.PENDING
        assert intent.redis_stream_id is None
    await transport.publish_due(redis_client)
    async with postgres.session() as session:
        intent = await session.get(DispatchIntent, intent_id)
        assert intent is not None and intent.redis_stream_id is not None
        assert intent.redis_published_at is not None


async def test_publish_marker_failure_can_duplicate_delivery(redis_client: Redis) -> None:
    intent_id = await create_intent("marker-failure")
    dispatcher = RecordingDispatcher("worker")
    transport = RepairStreamTransport("redis://unused", dispatcher)
    with patch.object(stream_store, "record_published", new=AsyncMock(side_effect=RuntimeError)):
        with pytest.raises(RuntimeError):
            await transport.publish_due(redis_client)
    async with postgres.session() as session:
        intent = await session.get(DispatchIntent, intent_id)
        assert intent is not None and intent.redis_stream_id is None
    await transport.publish_due(redis_client)
    assert await redis_client.xlen(stream.STREAM) == 2
    await transport.ensure_group(redis_client)
    messages = await redis_client.xreadgroup(stream.GROUP, "worker", {stream.STREAM: ">"}, count=2)
    for message in messages[0][1]:
        await transport.handle_message(redis_client, *message)
    assert dispatcher.dispatches == 1
    async with postgres.session() as session:
        intent = await session.get(DispatchIntent, intent_id)
        assert intent is not None and intent.status == DispatchStatus.DISPATCHED


async def test_consumer_waits_for_publish_marker_lock(redis_client: Redis) -> None:
    intent_id = await create_intent("publish-lock")
    dispatcher = RecordingDispatcher("worker")
    transport = RepairStreamTransport("redis://unused", dispatcher)
    await transport.ensure_group(redis_client)
    await transport.publish_due(redis_client)
    message = await consume_message(redis_client, "worker")
    async with postgres.session() as session:
        await session.scalar(
            select(DispatchIntent).where(DispatchIntent.id == intent_id).with_for_update()
        )
        handling = asyncio.create_task(transport.handle_message(redis_client, *message))
        await asyncio.sleep(0.05)
        assert not handling.done()
    await asyncio.wait_for(handling, timeout=3)
    assert dispatcher.dispatches == 1
    assert (await redis_client.xpending(stream.STREAM, stream.GROUP))["pending"] == 0


async def test_duplicate_stream_delivery_creates_one_runtime_reference(redis_client: Redis) -> None:
    intent_id = await create_intent("duplicate")
    first_dispatcher = RecordingDispatcher("worker-one")
    second_dispatcher = RecordingDispatcher("worker-two")
    first = RepairStreamTransport("redis://unused", first_dispatcher)
    second = RepairStreamTransport("redis://unused", second_dispatcher)
    await first.ensure_group(redis_client)
    await first.publish_due(redis_client)
    await redis_client.xadd(stream.STREAM, {"intent_id": str(intent_id)})
    result = await redis_client.xreadgroup(
        stream.GROUP, "worker-one", {stream.STREAM: ">"}, count=2
    )
    messages = result[0][1]
    assert len(messages) == 2
    await asyncio.gather(
        first.handle_message(redis_client, *messages[0]),
        second.handle_message(redis_client, *messages[1]),
    )
    assert first_dispatcher.dispatches + second_dispatcher.dispatches == 1
    async with postgres.session() as session:
        intent = await session.get(DispatchIntent, intent_id)
        assert intent is not None and intent.status == DispatchStatus.DISPATCHED
        assert intent.attempt_count == 1
        run = await session.get(RepairRun, intent.repair_run_id)
        assert run is not None and run.runtime_run_id is not None
    pending = await redis_client.xautoclaim(
        stream.STREAM, stream.GROUP, "worker-two", 0, "0-0", count=2
    )
    for message in pending[1]:
        await second.handle_message(redis_client, *message)
    assert (await redis_client.xpending(stream.STREAM, stream.GROUP))["pending"] == 0


async def test_consumed_message_is_reclaimed_after_worker_crash(redis_client: Redis) -> None:
    intent_id = await create_intent("consumer-crash")
    replacement = RepairStreamTransport("redis://unused", RecordingDispatcher("replacement"))
    await replacement.ensure_group(redis_client)
    await replacement.publish_due(redis_client)
    await consume_message(redis_client, "crashed-worker")
    assert (await redis_client.xpending(stream.STREAM, stream.GROUP))["pending"] == 1
    reclaimed = await redis_client.xautoclaim(
        stream.STREAM, stream.GROUP, "replacement", 0, "0-0", count=1
    )
    assert len(reclaimed[1]) == 1
    await replacement.handle_message(redis_client, *reclaimed[1][0])
    async with postgres.session() as session:
        intent = await session.get(DispatchIntent, intent_id)
        assert intent is not None and intent.status == DispatchStatus.DISPATCHED
    assert (await redis_client.xpending(stream.STREAM, stream.GROUP))["pending"] == 0


async def test_claimed_worker_crash_reconciles_before_ack(redis_client: Redis) -> None:
    intent_id = await create_intent("claimed-crash")
    replacement_dispatcher = RecordingDispatcher("replacement")
    replacement = RepairStreamTransport("redis://unused", replacement_dispatcher)
    await replacement.ensure_group(redis_client)
    await replacement.publish_due(redis_client)
    await consume_message(redis_client, "crashed-worker")
    claim = await dispatch_store.claim_intent(intent_id, "crashed-worker")
    assert claim is not None
    async with postgres.session() as session:
        await session.execute(
            update(DispatchIntent)
            .where(DispatchIntent.id == intent_id)
            .values(lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
        )
    assert await dispatch_store.reconcile_expired_claims() == 1
    reclaimed = await redis_client.xautoclaim(
        stream.STREAM, stream.GROUP, "replacement", 0, "0-0", count=1
    )
    await replacement.handle_message(redis_client, *reclaimed[1][0])
    assert replacement_dispatcher.dispatches == 0
    async with postgres.session() as session:
        intent = await session.get(DispatchIntent, intent_id)
        assert intent is not None and intent.status == DispatchStatus.RECONCILING
        assert intent.attempt_count == 1
    assert (await redis_client.xpending(stream.STREAM, stream.GROUP))["pending"] == 0


async def test_lost_stream_is_rebuilt_from_pending_intent(redis_client: Redis) -> None:
    intent_id = await create_intent("stream-loss")
    replacement_dispatcher = RecordingDispatcher("replacement")
    replacement = RepairStreamTransport("redis://unused", replacement_dispatcher)
    await replacement.ensure_group(redis_client)
    await replacement.publish_due(redis_client)
    async with postgres.session() as session:
        before = await session.get(DispatchIntent, intent_id)
        assert before is not None and before.redis_stream_id is not None
    await redis_client.delete(stream.STREAM)
    await replacement.ensure_group(redis_client)
    await replacement.publish_due(redis_client)
    assert await redis_client.xlen(stream.STREAM) == 1
    async with postgres.session() as session:
        after = await session.get(DispatchIntent, intent_id)
        assert after is not None and after.redis_stream_id is not None
        assert await redis_client.xrange(
            stream.STREAM, min=after.redis_stream_id, max=after.redis_stream_id
        )
        run = await session.get(RepairRun, after.repair_run_id)
        assert run is not None
        task = await session.get(RepairTask, run.task_id)
        assert task is not None and task.status == RepairStatus.QUEUED
    await replacement.handle_message(
        redis_client, *(await consume_message(redis_client, "replacement"))
    )
    assert replacement_dispatcher.dispatches == 1
