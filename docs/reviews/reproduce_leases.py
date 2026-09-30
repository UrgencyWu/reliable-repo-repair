"""Read-only-to-business review probe; creates/drops an isolated test schema."""
import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from agent.database import postgres
from agent.repair import dispatch_store, execution_store, store
from agent.repair.api_models import CreateRepairTask
from agent.repair.models import DispatchIntent, RepairRun
from agent.users import User
from tests.conftest import isolated_schema


async def probe(operation: str) -> dict[str, object]:
    async with postgres.session() as session:
        user = User(display_name="Review lease probe")
        session.add(user)
        await session.flush()
        owner = user.id
    await store.create_task(owner, str(uuid4()), CreateRepairTask(
        fixture_id="review", target_commit="a" * 40, failing_command="test"
    ), 300, {"source_path": "/unused", "target_argv": ["false"],
             "regression_argv": [], "allowed_patch_paths": ["calc.py"]})
    claim = await dispatch_store.claim_next("review", lease_seconds=2)
    assert claim is not None
    if operation == "execution_renew":
        assert await dispatch_store.record_dispatch(claim.intent.id, claim.token, uuid4())
        execution = await execution_store.claim_execution("review", lease_seconds=2)
        assert execution is not None
        expires = execution.run.execution_lease_at
        query = select(RepairRun).where(RepairRun.id == execution.run.id).with_for_update()
        callback = execution_store.renew_execution(execution)
    else:
        expires = claim.intent.lease_expires_at
        query = select(DispatchIntent).where(DispatchIntent.id == claim.intent.id).with_for_update()
        callback = (dispatch_store.renew_claim(claim.intent.id, claim.token)
                    if operation == "dispatch_renew" else
                    dispatch_store.record_dispatch(claim.intent.id, claim.token, uuid4()))
    assert expires is not None
    async with postgres.session() as holder:
        await holder.scalar(query)
        pid = await holder.scalar(text("select pg_backend_pid()"))
        job = asyncio.create_task(callback)
        async with asyncio.timeout(3):
            while True:
                async with postgres.session() as observer:
                    blocked = await observer.scalar(text(
                        "select count(*) from pg_stat_activity where :pid = any(pg_blocking_pids(pid))"
                    ), {"pid": pid})
                if blocked:
                    break
                await asyncio.sleep(0.01)
        await asyncio.sleep(max(0, (expires - datetime.now(UTC)).total_seconds()) + 0.25)
        assert not job.done()
    accepted = await asyncio.wait_for(job, timeout=5)
    return {"operation": operation, "accepted_after_expiry": accepted,
            "waited_past_expiry": datetime.now(UTC) > expires}


async def main() -> None:
    with pytest.MonkeyPatch.context() as patch:
        async with isolated_schema("postgresql://postgres:postgres@127.0.0.1:5433/postgres", patch):
            for operation in ("dispatch_record", "dispatch_renew", "execution_renew"):
                print(json.dumps(await probe(operation)))


if __name__ == "__main__":
    asyncio.run(main())
