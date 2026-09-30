import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from agent.config import ENV
from agent.repair import store
from agent.repair.api_models import CreateRepairTask, TaskView
from agent.repair.config import require_fixture
from agent.repair.models import EventPayload, RepairEvent, RepairRun, RepairTask, ValidationPlan
from agent.repair.state import RepairStatus, require_transition


class InvalidTask(ValueError):
    pass


async def transition_task(
    session: AsyncSession,
    task: RepairTask,
    run: RepairRun,
    target: RepairStatus,
    payload: EventPayload | None = None,
) -> None:
    await require_transition(task.status, target)
    task.status = target
    await append_event(session, task, run, target, payload)


async def append_event(
    session: AsyncSession,
    task: RepairTask,
    run: RepairRun,
    event: str,
    payload: EventPayload | None = None,
) -> None:
    task.version += 1
    session.add(
        RepairEvent(
            task_id=task.id,
            repair_run_id=run.id,
            sequence=task.version,
            event=event,
            payload=payload or {},
        )
    )


async def create_task(owner_id: UUID, key: str, body: CreateRepairTask) -> TaskView:
    fixture = await require_fixture(body.fixture_id, owner_id)
    if body.failing_command != fixture.failing_command:
        raise InvalidTask("Failing command must match the configured validation plan")
    process = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(fixture.source_path),
        "cat-file",
        "-e",
        f"{body.target_commit}^{{commit}}",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(process.communicate(), timeout=5)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise InvalidTask("Fixture commit lookup timed out") from None
    if process.returncode != 0:
        raise InvalidTask("Target commit does not exist in the configured fixture")
    timeout = ENV.REPAIR_TASK_TIMEOUT_SECONDS.get_int(300)
    if timeout <= 0:
        raise ValueError("REPAIR_TASK_TIMEOUT_SECONDS must be positive")
    plan: ValidationPlan = {
        "source_path": str(fixture.source_path),
        "target_argv": fixture.target_argv,
        "regression_argv": fixture.regression_argv,
        "allowed_patch_paths": fixture.allowed_patch_paths,
    }
    return await store.create_task(owner_id, key, body, timeout, plan)
