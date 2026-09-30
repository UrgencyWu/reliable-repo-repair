import asyncio
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from agent.api.app import create_app
from agent.dashboard.oauth import COOKIE_NAME, issue_session
from agent.database import postgres
from agent.repair import store
from agent.repair.api_models import CreateRepairTask
from agent.repair.models import DispatchIntent, RepairEvent, RepairRun, RepairTask, ValidationPlan
from agent.users import User

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("registry_db")]


@pytest.fixture
async def owner() -> UUID:
    async with postgres.session() as session:
        user = User(display_name="Repair Test")
        session.add(user)
        await session.flush()
        return user.id


@pytest.fixture
async def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CreateRepairTask:
    repo = tmp_path / "fixture"
    repo.mkdir()
    (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    environment = {
        "PATH": os.environ["PATH"],
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    for args in (
        ("init",),
        ("add", "."),
        (
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-m",
            "base",
        ),
    ):
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(repo),
            *args,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        output, error = await process.communicate()
        assert process.returncode == 0, (output, error)
    process = await asyncio.create_subprocess_exec(
        "git", "-C", str(repo), "rev-parse", "HEAD", stdout=asyncio.subprocess.PIPE
    )
    output, _ = await process.communicate()
    assert process.returncode == 0
    configuration = tmp_path / "fixtures.json"
    configuration.write_text(
        json.dumps(
            [
                {
                    "id": "arithmetic",
                    "source_path": str(repo),
                    "failing_command": "python3 -m unittest",
                    "target_argv": ["python3", "-m", "unittest"],
                    "allowed_patch_paths": ["calc.py"],
                    "shared": True,
                }
            ]
        )
    )
    monkeypatch.setenv("REPAIR_FIXTURES_FILE", str(configuration))
    return CreateRepairTask(
        fixture_id="arithmetic",
        target_commit=output.decode().strip(),
        failing_command="python3 -m unittest",
    )


@pytest.fixture
async def client(owner: UUID, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("DASHBOARD_JWT_SECRET", "repair-test-only-jwt-secret-at-least-32-bytes")
    monkeypatch.setenv("DASHBOARD_ALLOWED_ORIGINS", "http://test")
    token = issue_session(login="repair-test", email=None, avatar_url=None, user_id=str(owner))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()),
        base_url="http://test",
        cookies={COOKIE_NAME: token},
        headers={"Origin": "http://test"},
    ) as http:
        yield http


async def test_create_is_async_persisted_and_queryable(
    client: httpx.AsyncClient, repository: CreateRepairTask, owner: UUID
) -> None:
    response = await client.post(
        "/api/repair-tasks", json=repository.model_dump(), headers={"Idempotency-Key": "initial"}
    )
    assert response.status_code == 202, response.text
    task_id = response.json()["id"]
    assert response.headers["Location"] == f"/api/repair-tasks/{task_id}"
    assert response.json()["status"] == "QUEUED"
    detail = await client.get(response.headers["Location"])
    assert detail.status_code == 200
    assert detail.json()["runs"][0]["runtime_run_id"] is None
    assert [event["event"] for event in detail.json()["events"]] == ["RECEIVED", "QUEUED"]
    assert (await client.get("/api/repair-tasks")).json()["items"][0]["id"] == task_id
    async with postgres.session() as session:
        task = await session.get(RepairTask, UUID(task_id))
        assert task is not None and task.owner_id == owner
        assert task.validation_plan["allowed_patch_paths"] == ["calc.py"]
        assert await session.scalar(select(func.count()).select_from(DispatchIntent)) == 1


async def test_concurrent_duplicate_requests_create_one_task_run_intent(
    client: httpx.AsyncClient, repository: CreateRepairTask
) -> None:
    responses = await asyncio.gather(
        *(
            client.post(
                "/api/repair-tasks",
                json=repository.model_dump(),
                headers={"Idempotency-Key": "same"},
            )
            for _ in range(8)
        )
    )
    assert all(response.status_code == 202 for response in responses), [
        response.text for response in responses
    ]
    assert len({response.json()["id"] for response in responses}) == 1
    async with postgres.session() as session:
        for model in (RepairTask, RepairRun, DispatchIntent):
            assert await session.scalar(select(func.count()).select_from(model)) == 1
        assert await session.scalar(select(func.count()).select_from(RepairEvent)) == 2
    changed = repository.model_copy(update={"constraints": "different"})
    response = await client.post(
        "/api/repair-tasks", json=changed.model_dump(), headers={"Idempotency-Key": "same"}
    )
    assert response.status_code == 409


async def test_auth_ownership_pagination_and_input_validation(
    client: httpx.AsyncClient, repository: CreateRepairTask
) -> None:
    response = await client.post(
        "/api/repair-tasks", json=repository.model_dump(), headers={"Idempotency-Key": "ownership"}
    )
    assert response.status_code == 202
    task_id = UUID(response.json()["id"])
    assert await store.get_task(uuid4(), task_id) is None
    assert (await store.list_tasks(uuid4(), 20, 0)).items == []
    assert (await client.get("/api/repair-tasks?limit=101")).status_code == 422
    assert (await client.get(f"/api/repair-tasks/{uuid4()}")).status_code == 404
    unsafe = repository.model_dump() | {"failing_command": "arbitrary shell command"}
    assert (
        await client.post("/api/repair-tasks", json=unsafe, headers={"Idempotency-Key": "unsafe"})
    ).status_code == 422
    client.cookies.clear()
    assert (await client.get(f"/api/repair-tasks/{task_id}")).status_code == 401


async def test_recent_task_pages_are_stable_and_do_not_include_other_owners(
    client: httpx.AsyncClient, repository: CreateRepairTask, owner: UUID
) -> None:
    owned_ids: list[str] = []
    for index in range(3):
        response = await client.post(
            "/api/repair-tasks",
            json=repository.model_dump(),
            headers={"Idempotency-Key": f"page-{index}"},
        )
        assert response.status_code == 202
        owned_ids.append(response.json()["id"])
    async with postgres.session() as session:
        other_owner = User(display_name="Another Owner")
        session.add(other_owner)
        await session.flush()
        other_id = other_owner.id
        await session.execute(
            update(RepairTask).where(RepairTask.owner_id == owner).values(created_at=func.now())
        )
    foreign_task = await store.create_task(
        other_id,
        "foreign-task",
        repository,
        300,
        {
            "source_path": "/configured",
            "target_argv": ["python3"],
            "regression_argv": [],
            "allowed_patch_paths": ["calc.py"],
        },
    )
    first = (await client.get("/api/repair-tasks?limit=2&offset=0")).json()
    second = (await client.get("/api/repair-tasks?limit=2&offset=2")).json()
    ids = [item["id"] for page in (first, second) for item in page["items"]]
    assert ids == sorted(owned_ids, reverse=True)
    assert str(foreign_task.id) not in ids
    assert first["has_more"] is True and second["has_more"] is False
    assert [len(first["items"]), len(second["items"])] == [2, 1]
    assert (await client.get("/api/repair-tasks?limit=2&offset=0")).json() == first


async def test_failed_intent_insert_rolls_back_task_and_run(
    owner: UUID, repository: CreateRepairTask
) -> None:
    async with postgres.transaction() as connection:
        await connection.execute(
            text(
                "CREATE FUNCTION reject_repair_intent() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected intent failure'; END $$"
            )
        )
        await connection.execute(
            text(
                "CREATE TRIGGER reject_repair_intent BEFORE INSERT ON repair_dispatch_intent FOR EACH ROW EXECUTE FUNCTION reject_repair_intent()"
            )
        )
    plan: ValidationPlan = {
        "source_path": "/configured",
        "target_argv": ["python3"],
        "regression_argv": [],
        "allowed_patch_paths": ["calc.py"],
    }
    with pytest.raises(DBAPIError, match="injected intent failure"):
        await store.create_task(owner, "rollback", repository, 300, plan)
    async with postgres.session() as session:
        for model in (RepairTask, RepairRun, DispatchIntent, RepairEvent):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_artifact_queries_are_owned_bounded_and_preserve_exact_patch(
    client: httpx.AsyncClient, repository: CreateRepairTask, owner: UUID
) -> None:
    import hashlib

    from agent.repair.models import CandidateArtifact, ValidationRecord
    from agent.repair.store import LOG_LIMIT_BYTES

    posted = await client.post(
        "/api/repair-tasks", json=repository.model_dump(), headers={"Idempotency-Key": "artifacts"}
    )
    assert posted.status_code == 202
    location = posted.headers["Location"]
    unavailable = await client.get(f"{location}/patch")
    assert unavailable.status_code == 409
    assert unavailable.json()["detail"]["code"] == "patch_not_ready"
    empty = await client.get(f"{location}/artifacts")
    assert empty.status_code == 200 and empty.json()["candidate"] is None
    patch = b"diff --git a/calc.py b/calc.py\n\xff\n"
    digest = hashlib.sha256(patch).hexdigest()
    async with postgres.session() as session:
        run = await session.scalar(
            select(RepairRun).where(RepairRun.task_id == UUID(posted.json()["id"]))
        )
        assert run is not None
        candidate = CandidateArtifact(
            repair_run_id=run.id,
            base_commit=repository.target_commit,
            sha256=digest,
            patch=patch,
            files_changed=["calc.py"],
        )
        session.add(candidate)
        await session.flush()
        evidence = {
            "name": "BASELINE",
            "argv": ["python3", "-m", "unittest"],
            "exit_code": 1,
            "output": "测" * LOG_LIMIT_BYTES,
            "truncated": False,
            "timed_out": False,
            "duration_seconds": 0.1,
        }
        session.add(
            ValidationRecord(
                repair_run_id=run.id,
                candidate_id=candidate.id,
                attempt_no=1,
                execution_token=uuid4(),
                workspace="/private/internal/validator",
                checks=[evidence, evidence],
            )
        )
    detail = await client.get(location)
    assert detail.status_code == 200
    assert detail.json()["candidates"][0]["size_bytes"] == len(patch)
    assert "checks" not in detail.json()["validations"][0]
    assert "agent_workspace" not in detail.json()["runs"][0]
    downloaded = await client.get(f"{location}/patch")
    assert downloaded.status_code == 200 and downloaded.content == patch
    assert downloaded.headers["ETag"] == f'"{digest}"'
    assert downloaded.headers["X-Base-Commit"] == repository.target_commit
    artifact = await client.get(f"{location}/artifacts")
    assert artifact.status_code == 200
    body = artifact.json()
    checks = body["validations"][0]["checks"]
    assert sum(len(check["output"].encode()) for check in checks) <= LOG_LIMIT_BYTES
    assert all(check["truncated"] for check in checks)
    assert checks[0]["stored_output_bytes"] == LOG_LIMIT_BYTES * 3
    assert "/private/internal/validator" not in artifact.text
    async with postgres.session() as session:
        other = User(display_name="Other Reader")
        session.add(other)
        await session.flush()
        other_id = other.id
    token = issue_session(login="other", email=None, avatar_url=None, user_id=str(other_id))
    client.cookies.set(COOKIE_NAME, token)
    for suffix in ("", "/patch", "/artifacts"):
        denied = await client.get(f"{location}{suffix}")
        assert denied.status_code == 404
    client.cookies.clear()
    for suffix in ("", "/patch", "/artifacts"):
        anonymous = await client.get(f"{location}{suffix}")
        assert anonymous.status_code == 401
