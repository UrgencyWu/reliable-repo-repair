from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, update

from agent.database import postgres
from agent.repair import execution_store, recovery_store, validation_store
from agent.repair.models import DispatchIntent, RepairTask, ValidationRecord
from tests.repair.test_validation_store import prepare_validation

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("registry_db")]


async def test_deadline_invalidates_validation_owner_and_keeps_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPEN_SWE_LOCAL_WORKTREES_DIR", str(tmp_path / "worktrees"))
    claim, attempt = await prepare_validation(tmp_path)
    checks = [
        {
            "name": "BASELINE",
            "argv": claim.task.validation_plan["target_argv"],
            "exit_code": 1,
            "output": "original failure",
            "truncated": False,
            "timed_out": False,
            "duration_seconds": 0.1,
        }
    ]
    assert await validation_store.checkpoint_checks(claim, attempt, checks)
    async with postgres.session() as session:
        await session.execute(
            update(RepairTask)
            .where(RepairTask.id == claim.task.id)
            .values(deadline_at=func.clock_timestamp() - timedelta(seconds=1))
        )
    assert not await execution_store.renew_execution(claim)
    assert not await validation_store.checkpoint_checks(claim, attempt, checks)
    assert await recovery_store.expire_tasks() == 1
    assert await recovery_store.expire_tasks() == 0
    assert not await execution_store.fail_execution(claim, "late_failure")
    assert await execution_store.claim_execution("replacement") is None
    stops = await recovery_store.pending_stops()
    assert len(stops) == 1 and stops[0].run.id == claim.run.id
    async with postgres.session() as session:
        task = await session.get(RepairTask, claim.task.id)
        evidence = await session.get(ValidationRecord, attempt.record.id)
        assert (
            task is not None and task.status == "TIMEOUT" and task.failure_reason == "task_deadline"
        )
        assert evidence is not None and evidence.status == "ERROR" and evidence.checks == checks
        intent = await session.scalar(select(DispatchIntent))
        assert intent is not None and intent.status == "FAILED"
    await recovery_store.record_stop(claim.run.id, finished=True)
    assert not await recovery_store.pending_stops()


async def test_deadline_stops_real_active_run_without_starting_another(tmp_path: Path) -> None:
    import asyncio
    import os
    import shutil

    from langgraph_sdk import get_client

    from agent.repair import store
    from agent.repair.adapter import OpenSweAgentAdapter
    from agent.repair.dispatch import RepairDispatcher
    from agent.repair.process import git
    from tests.repair.test_adapter_integration import make_task_input

    url = os.environ.get("REPAIR_TEST_RUNTIME_URL")
    root = os.environ.get("OPEN_SWE_LOCAL_WORKTREES_DIR")
    if not url or not root:
        pytest.skip("Real repair Runtime and matching local worktree root required")
    owner, body, plan = await make_task_input(tmp_path)
    test_file = Path(plan["source_path"]) / "test_calc.py"
    test_file.write_text(
        test_file.read_text().replace(
            "import unittest", "import time\ntime.sleep(3)\nimport unittest"
        )
    )
    await git(test_file.parent, "add", "test_calc.py")
    await git(
        test_file.parent,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "slow test",
    )
    body.target_commit = (await git(test_file.parent, "rev-parse", "HEAD")).decode().strip()
    task = await store.create_task(owner, "timeout", body, 60, plan)
    async with get_client(url=url) as client:
        adapter = OpenSweAgentAdapter(client)
        dispatcher = RepairDispatcher(adapter, "timeout-worker")
        await dispatcher.tick()
        detail = await store.get_task(owner, task.id)
        assert detail is not None
        run = detail.runs[0]
        assert run.runtime_run_id is not None
        try:
            async with asyncio.timeout(10):
                while True:
                    status = (await client.runs.get(str(run.thread_id), str(run.runtime_run_id)))[
                        "status"
                    ]
                    if status == "running":
                        break
                    assert status == "pending"
                    await asyncio.sleep(0.05)
            async with postgres.session() as session:
                await session.execute(
                    update(RepairTask)
                    .where(RepairTask.id == task.id)
                    .values(deadline_at=func.clock_timestamp() - timedelta(seconds=1))
                )
            async with asyncio.timeout(15):
                while True:
                    await dispatcher.tick()
                    detail = await store.get_task(owner, task.id)
                    assert detail is not None and detail.task.status == "TIMEOUT"
                    if not detail.runs[0].runtime_stop_pending:
                        break
                    await asyncio.sleep(0.1)
            assert detail.runs[0].runtime_stop_error is None
            assert detail.candidates == []
            runs = await client.runs.list(str(run.thread_id))
            assert len(runs) == 1 and runs[0]["status"] == "interrupted"
        finally:
            await client.threads.delete(str(run.thread_id))
            await asyncio.to_thread(shutil.rmtree, Path(root) / "repair" / str(run.id), True)


async def test_unknown_creation_deadline_has_explicit_bounded_unresolved_result(
    tmp_path: Path,
) -> None:
    import os

    from langgraph_sdk import get_client

    from agent.repair import dispatch_store, store
    from agent.repair.adapter import OpenSweAgentAdapter
    from agent.repair.dispatch import RepairDispatcher
    from tests.repair.test_adapter_integration import make_task_input

    url = os.environ.get("REPAIR_TEST_RUNTIME_URL")
    if not url:
        pytest.skip("Real repair Runtime required")
    owner, body, plan = await make_task_input(tmp_path)
    task = await store.create_task(owner, "unknown-deadline", body, 60, plan)
    claim = await dispatch_store.claim_next("lost-worker")
    assert claim is not None
    async with postgres.session() as session:
        await session.execute(
            update(RepairTask)
            .where(RepairTask.id == task.id)
            .values(deadline_at=func.clock_timestamp() - timedelta(seconds=61))
        )
    async with get_client(url=url) as client:
        dispatcher = RepairDispatcher(OpenSweAgentAdapter(client), "replacement")
        await dispatcher.tick()
        await dispatcher.tick()
    detail = await store.get_task(owner, task.id)
    assert detail is not None and detail.task.status == "TIMEOUT"
    assert detail.task.failure_reason == "task_deadline_create_outcome_unknown"
    assert detail.runs[0].runtime_run_id is None
    assert detail.runs[0].runtime_stop_pending is False
    assert detail.runs[0].runtime_stop_error == "runtime_creation_unresolved_after_deadline"
    async with postgres.session() as session:
        intent = await session.get(DispatchIntent, claim.intent.id)
        assert intent is not None and intent.attempt_count == 1 and intent.status == "FAILED"


async def test_missing_runtime_is_explicit_failure_without_restarting(tmp_path: Path) -> None:
    import os
    from uuid import uuid4

    from langgraph_sdk import get_client

    from agent.repair import dispatch_store, store
    from agent.repair.adapter import OpenSweAgentAdapter
    from agent.repair.dispatch import RepairDispatcher
    from tests.repair.test_adapter_integration import make_task_input

    url = os.environ.get("REPAIR_TEST_RUNTIME_URL")
    if not url:
        pytest.skip("Real repair Runtime required")
    owner, body, plan = await make_task_input(tmp_path)
    task = await store.create_task(owner, "missing-runtime", body, 60, plan)
    claim = await dispatch_store.claim_next("original-worker")
    assert claim is not None
    assert await dispatch_store.record_dispatch(claim.intent.id, claim.token, uuid4())
    async with get_client(url=url) as client:
        replacement = RepairDispatcher(OpenSweAgentAdapter(client), "replacement")
        await replacement.tick()
        await replacement.tick()
    detail = await store.get_task(owner, task.id)
    assert detail is not None and detail.task.status == "FAILED"
    assert detail.task.failure_reason == "runtime_missing"
    async with postgres.session() as session:
        intent = await session.get(DispatchIntent, claim.intent.id)
        assert intent is not None and intent.attempt_count == 1


@pytest.mark.parametrize("candidate_saved", [False, True])
async def test_lost_agent_workspace_recovers_only_with_persisted_candidate(
    tmp_path: Path, candidate_saved: bool
) -> None:
    import asyncio
    import os
    import shutil

    from langgraph_sdk import get_client

    from agent.repair import store
    from agent.repair.adapter import OpenSweAgentAdapter
    from agent.repair.dispatch import RepairDispatcher
    from tests.repair.test_adapter_integration import make_task_input

    url = os.environ.get("REPAIR_TEST_RUNTIME_URL")
    root = os.environ.get("OPEN_SWE_LOCAL_WORKTREES_DIR")
    if not url or not root:
        pytest.skip("Real repair Runtime and worktree root required")
    owner, body, plan = await make_task_input(tmp_path)
    task = await store.create_task(owner, "workspace-loss", body, 60, plan)
    async with get_client(url=url) as client:
        original = RepairDispatcher(OpenSweAgentAdapter(client), "original")
        await original.tick()
        detail = await store.get_task(owner, task.id)
        assert detail is not None
        run = detail.runs[0]
        workspace = Path(root) / "repair" / str(run.id) / "agent"
        try:
            async with asyncio.timeout(15):
                while True:
                    status = (await client.runs.get(str(run.thread_id), str(run.runtime_run_id)))[
                        "status"
                    ]
                    if status == "success":
                        break
                    assert status in {"pending", "running"}
                    await asyncio.sleep(0.05)
            if candidate_saved:
                await original.tick()
                saved = await store.get_task(owner, task.id)
                assert (
                    saved is not None
                    and saved.task.status == "VALIDATING"
                    and len(saved.candidates) == 1
                )
            await asyncio.to_thread(shutil.rmtree, workspace)
            replacement = RepairDispatcher(OpenSweAgentAdapter(client), "replacement")
            await replacement.tick()
            result = await store.get_task(owner, task.id)
            assert result is not None
            assert result.task.status == ("COMPLETED" if candidate_saved else "FAILED")
            assert result.task.failure_reason == (
                None if candidate_saved else "agent_workspace_lost"
            )
            assert not workspace.exists()
            assert len(await client.runs.list(str(run.thread_id))) == 1
        finally:
            await client.threads.delete(str(run.thread_id))
            await asyncio.to_thread(shutil.rmtree, Path(root) / "repair" / str(run.id), True)
