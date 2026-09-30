"""Exercise per-intent error isolation without calling a Runtime or a model."""
import asyncio
import json
from uuid import UUID, uuid4

import pytest
from langgraph_sdk import get_client

from agent.database import postgres
from agent.repair import dispatch_store, store
from agent.repair.adapter import OpenSweAgentAdapter
from agent.repair.api_models import CreateRepairTask
from agent.repair.dispatch import RepairDispatcher
from agent.repair.models import RepairRun
from agent.users import User
from tests.conftest import isolated_schema


class DuplicateMetadataAdapter(OpenSweAgentAdapter):
    async def find_run(self, run: RepairRun, intent_id: UUID) -> UUID | None:
        raise ValueError("Multiple Runtime runs found for one dispatch intent")


async def main() -> None:
    with pytest.MonkeyPatch.context() as patch:
        async with isolated_schema("postgresql://postgres:postgres@127.0.0.1:5433/postgres", patch):
            async with postgres.session() as session:
                owner = User(display_name="Review reconciliation probe")
                session.add(owner)
                await session.flush()
                user_id = owner.id
            body = CreateRepairTask(fixture_id="review", target_commit="a" * 40, failing_command="test")
            plan = {"source_path": "/unused", "target_argv": ["false"], "regression_argv": [], "allowed_patch_paths": ["calc.py"]}
            await store.create_task(user_id, "poison", body, 300, plan)
            first = await dispatch_store.claim_next("review")
            assert first is not None
            await dispatch_store.record_dispatch_failure(first.intent.id, first.token, "unknown", definitely_not_created=False, retryable=True)
            healthy = await store.create_task(user_id, "healthy", body, 300, plan)
            async with get_client(url="http://127.0.0.1:9", timeout=1) as client:
                worker = RepairDispatcher(DuplicateMetadataAdapter(client), "review")
                failures = 0
                for _ in range(2):
                    try:
                        await worker.tick()
                    except ValueError as exc:
                        assert "Multiple Runtime runs" in str(exc)
                        failures += 1
            result = await store.get_task(user_id, healthy.id)
            assert result is not None
            print(json.dumps({"tick_failures": failures, "healthy_task_status": result.task.status,
                              "healthy_dispatch_attempts": result.runs[0].dispatch_attempts}))


if __name__ == "__main__":
    asyncio.run(main())
