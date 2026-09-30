import asyncio
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from langgraph_sdk import get_client
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError

from agent.api.app import create_app
from agent.dashboard.oauth import COOKIE_NAME, issue_session
from agent.database import postgres
from agent.repair import dispatch_store, execution_store, store
from agent.repair.adapter import OpenSweAgentAdapter
from agent.repair.api_models import CreateRepairTask
from agent.repair.dispatch import RepairDispatcher
from agent.repair.models import (
    CandidateArtifact,
    DispatchIntent,
    RepairRun,
    RepairTask,
    ValidationPlan,
    ValidationRecord,
)
from agent.repair.process import git, run_command
from agent.repair.repository import prepare_agent_repository
from agent.repair.worker import repair_worker
from agent.users import User

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("registry_db")]


async def make_task_input(tmp_path: Path) -> tuple[UUID, CreateRepairTask, ValidationPlan]:
    source = tmp_path / "source"
    source.mkdir()
    (source / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (source / "test_calc.py").write_text(
        "import unittest\nfrom calc import add\nclass TestCalc(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n"
    )
    (source / ".gitignore").write_text("__pycache__/\n")
    await git(source, "init", "--initial-branch=main")
    await git(source, "add", ".")
    await git(
        source,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-m",
        "broken fixture",
    )
    base = (await git(source, "rev-parse", "HEAD")).decode().strip()
    async with postgres.session() as session:
        owner = User(display_name="Adapter Test")
        session.add(owner)
        await session.flush()
        owner_id = owner.id
    body = CreateRepairTask(
        fixture_id="arithmetic",
        target_commit=base,
        failing_command="python3 -m unittest test_calc.py",
        constraints="E2E_REPAIR_FIXTURE",
    )
    plan: ValidationPlan = {
        "source_path": str(source),
        "target_argv": [sys.executable, "-c", "from calc import add; assert add(2, 3) == 5"],
        "regression_argv": [
            [
                sys.executable,
                "-c",
                "from calc import add; assert add(-2, 5) == 3; assert add(0, 0) == 0",
            ]
        ],
        "allowed_patch_paths": ["calc.py"],
    }
    return owner_id, body, plan


async def make_task(tmp_path: Path) -> tuple[UUID, UUID]:
    owner_id, body, plan = await make_task_input(tmp_path)
    task = await store.create_task(owner_id, "adapter", body, 60, plan)
    return owner_id, task.id


async def test_two_dispatchers_persist_one_candidate_without_self_declaring_success(
    tmp_path: Path,
) -> None:
    url = os.environ.get("REPAIR_TEST_RUNTIME_URL")
    root = os.environ.get("OPEN_SWE_LOCAL_WORKTREES_DIR")
    if not url or not root:
        pytest.skip("Running repair LangGraph test server and matching worktree root required")
    owner_id, task_id = await make_task(tmp_path)
    async with get_client(url=url) as client:
        dispatcher = RepairDispatcher(OpenSweAgentAdapter(client), "worker-one", poll_seconds=0.1)
        second_dispatcher = RepairDispatcher(
            OpenSweAgentAdapter(client), "worker-two", poll_seconds=0.1
        )
        detail = await store.get_task(owner_id, task_id)
        assert detail is not None
        run_id = detail.runs[0].id
        thread_id = detail.runs[0].thread_id
        try:
            async with asyncio.timeout(20):
                while True:
                    await asyncio.gather(dispatcher.tick(), second_dispatcher.tick())
                    detail = await store.get_task(owner_id, task_id)
                    assert detail is not None
                    if detail.task.status == "COMPLETED":
                        break
                    assert detail.task.status != "FAILED", detail.task.failure_reason
                    await asyncio.sleep(0.1)
            async with postgres.session() as session:
                artifact = await session.scalar(
                    select(CandidateArtifact).where(CandidateArtifact.repair_run_id == run_id)
                )
                assert artifact is not None
                assert artifact.base_commit == detail.task.target_commit
                assert artifact.sha256 == hashlib.sha256(artifact.patch).hexdigest()
            async with postgres.session() as session:
                validation = await session.scalar(
                    select(ValidationRecord).where(ValidationRecord.repair_run_id == run_id)
                )
                assert validation is not None and validation.status == "PASS"
                assert [check["exit_code"] for check in validation.checks] == [1, 0, 0, 0, 0]
                assert validation.candidate_id == artifact.id
            assert artifact.files_changed == ["calc.py"]
            assert detail.runs[0].dispatch_attempts == 1
            assert detail.runs[0].dispatch_status == "DISPATCHED"
            runtime_events = [event for event in detail.events if event.event == "RUNTIME_STARTED"]
            assert len(runtime_events) == 1
            assert runtime_events[0].payload["runtime_run_id"] == str(detail.runs[0].runtime_run_id)
            assert runtime_events[0].payload["dispatch_attempts"] == 1
            assert detail.runs[0].runtime_run_id is not None
            candidate = artifact.patch
            with pytest.raises(DBAPIError, match="repair candidate is immutable"):
                async with postgres.session() as mutable_session:
                    await mutable_session.execute(
                        update(CandidateArtifact)
                        .where(CandidateArtifact.id == artifact.id)
                        .values(sha256="0" * 64)
                    )
            with pytest.raises(DBAPIError, match="repair candidate is immutable"):
                async with postgres.session() as deletion_session:
                    await deletion_session.execute(
                        delete(CandidateArtifact).where(CandidateArtifact.id == artifact.id)
                    )
            validator = tmp_path / "validator"
            await git(tmp_path, "clone", str(tmp_path / "source"), str(validator))
            await git(validator, "checkout", "--detach", detail.task.target_commit)
            baseline = await run_command(
                [sys.executable, "-m", "unittest", "test_calc.py"], validator
            )
            assert baseline.exit_code == 1
            applied = await run_command(["git", "apply", "-"], validator, input_data=candidate)
            assert applied.exit_code == 0
            verified = await run_command(
                [sys.executable, "-m", "unittest", "test_calc.py"], validator
            )
            assert verified.exit_code == 0
            runtime_runs = await client.runs.list(str(thread_id))
            assert len(runtime_runs) == 1
        finally:
            await client.threads.delete(str(thread_id))
            await asyncio.to_thread(shutil.rmtree, Path(root) / "repair" / str(run_id), True)


class LostCreateResponseAdapter(OpenSweAgentAdapter):
    async def start(self, task: RepairTask, run: RepairRun, intent_id: UUID) -> UUID:
        await super().start(task, run, intent_id)
        raise httpx.ReadTimeout("Injected response loss after real Runtime creation")


async def test_new_dispatcher_reconciles_real_run_after_lost_response(tmp_path: Path) -> None:
    url = os.environ.get("REPAIR_TEST_RUNTIME_URL")
    root = os.environ.get("OPEN_SWE_LOCAL_WORKTREES_DIR")
    if not url or not root:
        pytest.skip("Running repair LangGraph test server and matching worktree root required")
    owner_id, task_id = await make_task(tmp_path)
    async with get_client(url=url) as client:
        detail = await store.get_task(owner_id, task_id)
        assert detail is not None
        run_id, thread_id = detail.runs[0].id, detail.runs[0].thread_id
        try:
            lost = RepairDispatcher(LostCreateResponseAdapter(client), "old-worker")
            await lost.tick()
            async with postgres.session() as session:
                intent = await session.scalar(select(DispatchIntent))
                assert intent is not None and intent.status == "RECONCILING"
            recovered = RepairDispatcher(OpenSweAgentAdapter(client), "replacement-worker")
            async with asyncio.timeout(20):
                while True:
                    await recovered.tick()
                    detail = await store.get_task(owner_id, task_id)
                    assert detail is not None
                    if detail.task.status == "COMPLETED":
                        break
                    assert detail.task.status != "FAILED", detail.task.failure_reason
                    await asyncio.sleep(0.1)
            assert len(await client.runs.list(str(thread_id))) == 1
            assert detail.runs[0].runtime_run_id is not None
        finally:
            await client.threads.delete(str(thread_id))
            await asyncio.to_thread(shutil.rmtree, Path(root) / "repair" / str(run_id), True)


async def test_repository_reconnect_preserves_work_and_execution_token_fences_late_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPEN_SWE_LOCAL_WORKTREES_DIR", str(tmp_path / "worktrees"))
    owner_id, task_id = await make_task(tmp_path)
    claim = await dispatch_store.claim_next("worker")
    assert claim is not None
    workspace = await prepare_agent_repository(
        Path(claim.task.validation_plan["source_path"]), claim.task.target_commit, claim.run.id
    )
    (workspace / "calc.py").write_text("in progress\n")
    assert (
        await prepare_agent_repository(
            Path(claim.task.validation_plan["source_path"]), claim.task.target_commit, claim.run.id
        )
        == workspace
    )
    assert (workspace / "calc.py").read_text() == "in progress\n"
    assert await dispatch_store.record_dispatch(
        claim.intent.id, claim.token, UUID("00000000-0000-0000-0000-000000000001")
    )
    old = await execution_store.claim_execution("old")
    assert old is not None
    await execution_store.release_execution(old)
    new = await execution_store.claim_execution("new")
    assert new is not None
    assert await execution_store.fail_execution(old, "late_failure") is False
    assert await execution_store.fail_execution(new, "current_failure") is True
    detail = await store.get_task(owner_id, task_id)
    assert detail is not None and detail.task.failure_reason == "current_failure"


async def test_api_accepts_before_standalone_worker_dispatches_persisted_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = os.environ.get("REPAIR_TEST_RUNTIME_URL")
    root = os.environ.get("OPEN_SWE_LOCAL_WORKTREES_DIR")
    if not url or not root:
        pytest.skip("Running repair LangGraph test server and matching worktree root required")
    owner_id, body, plan = await make_task_input(tmp_path)
    fixture_file = tmp_path / "fixtures.json"
    fixture_file.write_text(
        json.dumps(
            [
                {
                    "id": "arithmetic",
                    "source_path": plan["source_path"],
                    "shared": True,
                    "failing_command": body.failing_command,
                    "target_argv": plan["target_argv"],
                    "regression_argv": plan["regression_argv"],
                    "allowed_patch_paths": plan["allowed_patch_paths"],
                }
            ]
        )
    )
    monkeypatch.setenv("REPAIR_FIXTURES_FILE", str(fixture_file))
    monkeypatch.setenv("REPAIR_ENABLED", "true")
    monkeypatch.setenv("REPAIR_POLL_SECONDS", "0.1")
    monkeypatch.setenv("LANGGRAPH_URL", url)
    monkeypatch.setenv("DASHBOARD_JWT_SECRET", "repair-test-only-jwt-secret-at-least-32-bytes")
    monkeypatch.setenv("DASHBOARD_ALLOWED_ORIGINS", "http://test")
    token = issue_session(login="adapter-test", email=None, avatar_url=None, user_id=str(owner_id))
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        cookies={COOKIE_NAME: token},
        headers={"Origin": "http://test"},
    ) as http:
        posted = await http.post(
            "/api/repair-tasks",
            json=body.model_dump(),
            headers={"Idempotency-Key": "before-worker"},
        )
        assert posted.status_code == 202, posted.text
        task_id = UUID(posted.json()["id"])
        detail = await store.get_task(owner_id, task_id)
        assert detail is not None and detail.task.status == "QUEUED"
        run_id, thread_id = detail.runs[0].id, detail.runs[0].thread_id
        try:
            async with repair_worker():
                async with asyncio.timeout(20):
                    while True:
                        response = await http.get(posted.headers["Location"])
                        assert response.status_code == 200
                        status = response.json()["task"]["status"]
                        if status == "COMPLETED":
                            break
                        assert status != "FAILED", response.text
                        await asyncio.sleep(0.1)
            artifacts = await http.get(f"{posted.headers['Location']}/artifacts")
            assert artifacts.status_code == 200
            assert artifacts.json()["validations"][0]["status"] == "PASS"
            assert [
                check["exit_code"] for check in artifacts.json()["validations"][0]["checks"]
            ] == [1, 0, 0, 0, 0]
            patch_response = await http.get(f"{posted.headers['Location']}/patch")
            assert patch_response.status_code == 200
            assert (
                hashlib.sha256(patch_response.content).hexdigest()
                == artifacts.json()["candidate"]["sha256"]
            )
            assert not hasattr(app.state, "repair_dispatcher")
            async with get_client(url=url) as client:
                assert len(await client.runs.list(str(thread_id))) == 1
        finally:
            async with get_client(url=url) as client:
                await client.threads.delete(str(thread_id))
            await asyncio.to_thread(shutil.rmtree, Path(root) / "repair" / str(run_id), True)
