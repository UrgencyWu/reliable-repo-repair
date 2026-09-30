import asyncio
import os
import shutil
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import UUID

import pytest
from langgraph_sdk import get_client
from sqlalchemy import select

from agent.database import postgres
from agent.repair import store
from agent.repair.api_models import TaskDetail
from agent.repair.models import ValidationRecord
from agent.repair.process import git
from tests.repair.test_adapter_integration import make_task_input

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("registry_db")]


async def spawn_worker(
    url: str, label: str, log: Path, pause_after_create: Path | None = None
) -> asyncio.subprocess.Process:
    extra_args = ["--pause-after-create", str(pause_after_create)] if pause_after_create else []
    with log.open("wb") as output:
        return await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "tests.repair.worker_process",
            postgres.SCHEMA,
            url,
            label,
            *extra_args,
            env=dict(os.environ),
            stdout=output,
            stderr=asyncio.subprocess.STDOUT,
        )


async def wait_detail(
    owner: UUID,
    task_id: UUID,
    worker: asyncio.subprocess.Process,
    predicate: Callable[[TaskDetail], Awaitable[bool]],
    log: Path,
) -> TaskDetail:
    async with asyncio.timeout(45):
        while True:
            assert worker.returncode is None, log.read_text()
            detail = await store.get_task(owner, task_id)
            assert detail is not None
            assert detail.task.status not in {"FAILED", "TIMEOUT"}, (detail, log.read_text())
            if await predicate(detail):
                return detail
            await asyncio.sleep(0.025)


async def kill_worker(worker: asyncio.subprocess.Process) -> None:
    if worker.returncode is None:
        worker.kill()
    await worker.wait()


async def test_sigkill_after_runtime_start_restarts_observer_without_new_generation(
    tmp_path: Path,
) -> None:
    url = os.environ.get("REPAIR_TEST_RUNTIME_URL")
    root = os.environ.get("OPEN_SWE_LOCAL_WORKTREES_DIR")
    if not url or not root:
        pytest.skip("Real repair Runtime and worktree root required")
    owner, body, plan = await make_task_input(tmp_path)
    source = Path(plan["source_path"])
    test_file = source / "test_calc.py"
    test_file.write_text("import time\ntime.sleep(2)\n" + test_file.read_text())
    await git(source, "add", "test_calc.py")
    await git(
        source,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "hold active run",
    )
    body.target_commit = (await git(source, "rev-parse", "HEAD")).decode().strip()
    task = await store.create_task(owner, "process-crash", body, 90, plan)
    log = tmp_path / "first-worker.log"
    worker = await spawn_worker(url, "first-worker", log)
    replacement: asyncio.subprocess.Process | None = None
    detail = await store.get_task(owner, task.id)
    assert detail is not None
    run_id, thread_id = detail.runs[0].id, detail.runs[0].thread_id

    async def started(detail: TaskDetail) -> bool:
        return detail.runs[0].runtime_run_id is not None

    async def completed(detail: TaskDetail) -> bool:
        return detail.task.status == "COMPLETED"

    try:
        started_detail = await wait_detail(owner, task.id, worker, started, log)
        assert started_detail.task.status == "PROVISIONING"
        runtime_id = started_detail.runs[0].runtime_run_id
        async with get_client(url=url) as client:
            active = await client.runs.get(str(thread_id), str(runtime_id))
            assert active["status"] in {"pending", "running"}
        await kill_worker(worker)
        assert worker.returncode == -9
        replacement_log = tmp_path / "replacement.log"
        replacement = await spawn_worker(url, "replacement-worker", replacement_log)
        result = await wait_detail(owner, task.id, replacement, completed, replacement_log)
        assert result.runs[0].runtime_run_id == runtime_id
        assert len(result.candidates) == 1 and len(result.validations) == 1
        async with get_client(url=url) as client:
            assert len(await client.runs.list(str(thread_id))) == 1
        async with postgres.session() as session:
            validation = await session.scalar(select(ValidationRecord))
            assert validation is not None and validation.status == "PASS"
    finally:
        await kill_worker(worker)
        if replacement is not None:
            await kill_worker(replacement)
        async with get_client(url=url) as client:
            await client.threads.delete(str(thread_id))
        await asyncio.to_thread(shutil.rmtree, Path(root) / "repair" / str(run_id), True)


async def test_sigkill_during_validation_reuses_candidate_after_real_lease_expiry(
    tmp_path: Path,
) -> None:
    url = os.environ.get("REPAIR_TEST_RUNTIME_URL")
    root = os.environ.get("OPEN_SWE_LOCAL_WORKTREES_DIR")
    if not url or not root:
        pytest.skip("Real repair Runtime and worktree root required")
    owner, body, plan = await make_task_input(tmp_path)
    marker = tmp_path / "validation-command-started"
    plan["target_argv"] = [
        sys.executable,
        "-c",
        f"from pathlib import Path; import time; Path({str(marker)!r}).write_text('started'); time.sleep(3); from calc import add; assert add(2, 3) == 5",
    ]
    task = await store.create_task(owner, "validator-crash", body, 90, plan)
    log = tmp_path / "validator-worker.log"
    worker = await spawn_worker(url, "validator-worker", log)
    replacement: asyncio.subprocess.Process | None = None
    detail = await store.get_task(owner, task.id)
    assert detail is not None
    run_id, thread_id = detail.runs[0].id, detail.runs[0].thread_id
    abandoned_workspace: Path | None = None

    async def validating(detail: TaskDetail) -> bool:
        return detail.task.status == "VALIDATING" and marker.exists()

    async def completed(detail: TaskDetail) -> bool:
        return detail.task.status == "COMPLETED"

    try:
        initial = await wait_detail(owner, task.id, worker, validating, log)
        candidate_id = initial.candidates[0].id
        candidate_hash = initial.candidates[0].sha256
        async with postgres.session() as session:
            record = await session.scalar(select(ValidationRecord))
            assert record is not None and record.status == "RUNNING"
            abandoned_workspace = Path(record.workspace)
        await kill_worker(worker)
        assert worker.returncode == -9
        replacement_log = tmp_path / "validator-replacement.log"
        replacement = await spawn_worker(url, "validator-replacement", replacement_log)
        result = await wait_detail(owner, task.id, replacement, completed, replacement_log)
        assert len(result.candidates) == 1
        assert (
            result.candidates[0].id == candidate_id
            and result.candidates[0].sha256 == candidate_hash
        )
        async with postgres.session() as session:
            records = list(
                await session.scalars(
                    select(ValidationRecord).order_by(ValidationRecord.attempt_no)
                )
            )
            assert [record.status for record in records] == ["ERROR", "PASS"]
            assert records[0].error_type == "validation_owner_lost"
            assert records[0].candidate_id == records[1].candidate_id == candidate_id
            assert records[0].workspace != records[1].workspace
        async with get_client(url=url) as client:
            assert len(await client.runs.list(str(thread_id))) == 1
    finally:
        await kill_worker(worker)
        if replacement is not None:
            await kill_worker(replacement)
        async with get_client(url=url) as client:
            await client.threads.delete(str(thread_id))
        await asyncio.to_thread(shutil.rmtree, Path(root) / "repair" / str(run_id), True)
        if abandoned_workspace is not None:
            await asyncio.to_thread(shutil.rmtree, abandoned_workspace, True)


async def test_sigkill_between_remote_create_and_db_save_reconciles_same_run(
    tmp_path: Path,
) -> None:
    url = os.environ.get("REPAIR_TEST_RUNTIME_URL")
    root = os.environ.get("OPEN_SWE_LOCAL_WORKTREES_DIR")
    if not url or not root:
        pytest.skip("Real repair Runtime and worktree root required")
    owner, body, plan = await make_task_input(tmp_path)
    task = await store.create_task(owner, "create-window-crash", body, 90, plan)
    marker = tmp_path / "remote-created"
    log = tmp_path / "create-worker.log"
    worker = await spawn_worker(url, "create-worker", log, marker)
    replacement: asyncio.subprocess.Process | None = None
    detail = await store.get_task(owner, task.id)
    assert detail is not None
    run_id, thread_id = detail.runs[0].id, detail.runs[0].thread_id

    async def remotely_created(detail: TaskDetail) -> bool:
        return marker.exists()

    async def completed(detail: TaskDetail) -> bool:
        return detail.task.status == "COMPLETED"

    try:
        initial = await wait_detail(owner, task.id, worker, remotely_created, log)
        assert initial.runs[0].runtime_run_id is None
        runtime_id = UUID(marker.read_text())
        await kill_worker(worker)
        assert worker.returncode == -9
        replacement_log = tmp_path / "create-replacement.log"
        replacement = await spawn_worker(url, "create-replacement", replacement_log)
        result = await wait_detail(owner, task.id, replacement, completed, replacement_log)
        assert result.runs[0].runtime_run_id == runtime_id
        assert result.runs[0].dispatch_attempts == 1
        assert any(event.event == "RUNTIME_RECONCILED" for event in result.events)
        async with get_client(url=url) as client:
            assert len(await client.runs.list(str(thread_id))) == 1
    finally:
        await kill_worker(worker)
        if replacement is not None:
            await kill_worker(replacement)
        async with get_client(url=url) as client:
            await client.threads.delete(str(thread_id))
        await asyncio.to_thread(shutil.rmtree, Path(root) / "repair" / str(run_id), True)
