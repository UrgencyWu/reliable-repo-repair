from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response

from agent.dashboard.oauth import require_same_origin_for_mutations, require_session
from agent.repair import service, store
from agent.repair.api_models import (
    ArtifactResult,
    CreateRepairTask,
    RepairError,
    TaskDetail,
    TaskPage,
    TaskView,
)
from agent.repair.store import IdempotencyConflict
from agent.users import User

router = APIRouter(
    prefix="/api/repair-tasks",
    tags=["repair"],
    dependencies=[Depends(require_same_origin_for_mutations)],
)


async def principal(session: Annotated[dict[str, object], Depends(require_session)]) -> UUID:
    raw = session.get("user_id")
    if not isinstance(raw, str):
        raise HTTPException(
            401,
            detail=RepairError(
                code="invalid_session", message="Session has no user identity"
            ).model_dump(),
        )
    try:
        owner_id = UUID(raw)
    except ValueError as exc:
        raise HTTPException(
            401,
            detail=RepairError(
                code="invalid_session", message="Invalid user identity"
            ).model_dump(),
        ) from exc
    if await User.get(owner_id) is None:
        raise HTTPException(
            401,
            detail=RepairError(
                code="invalid_session", message="User no longer exists"
            ).model_dump(),
        )
    return owner_id


Owner = Annotated[UUID, Depends(principal)]


@router.post("", status_code=202, response_model=TaskView)
async def create_task(
    body: CreateRepairTask,
    owner: Owner,
    response: Response,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=128)],
) -> TaskView:
    if not idempotency_key.strip():
        raise HTTPException(
            422,
            detail=RepairError(
                code="invalid_idempotency_key", message="Idempotency-Key must not be blank"
            ).model_dump(),
        )
    try:
        task = await service.create_task(owner, idempotency_key, body)
    except IdempotencyConflict as exc:
        raise HTTPException(
            409, detail=RepairError(code="idempotency_conflict", message=str(exc)).model_dump()
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            404, detail=RepairError(code="fixture_unavailable", message=str(exc)).model_dump()
        ) from exc
    except service.InvalidTask as exc:
        raise HTTPException(
            422, detail=RepairError(code="invalid_task", message=str(exc)).model_dump()
        ) from exc
    response.headers["Location"] = f"/api/repair-tasks/{task.id}"
    return task


@router.get("", response_model=TaskPage)
async def list_tasks(
    owner: Owner,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
) -> TaskPage:
    return await store.list_tasks(owner, limit, offset)


@router.get("/{task_id}", response_model=TaskDetail)
async def get_task(task_id: UUID, owner: Owner) -> TaskDetail:
    detail = await store.get_task(owner, task_id)
    if detail is None:
        raise HTTPException(
            404,
            detail=RepairError(code="task_not_found", message="Repair task not found").model_dump(),
        )
    return detail


@router.get("/{task_id}/patch")
async def get_patch(task_id: UUID, owner: Owner) -> Response:
    result = await store.get_patch(owner, task_id)
    if result is None:
        raise HTTPException(
            404,
            detail=RepairError(code="task_not_found", message="Repair task not found").model_dump(),
        )
    task, candidate = result
    if candidate is None:
        raise HTTPException(
            409,
            detail=RepairError(
                code="patch_not_ready",
                message=f"No candidate patch available; task is {task.status}",
            ).model_dump(),
        )
    return Response(
        content=candidate.patch,
        media_type="text/plain",
        headers={
            "ETag": f'"{candidate.sha256}"',
            "X-Base-Commit": candidate.base_commit,
            "Content-Disposition": f'attachment; filename="repair-{task_id}.patch"',
        },
    )


@router.get("/{task_id}/artifacts", response_model=ArtifactResult)
async def get_artifacts(task_id: UUID, owner: Owner) -> ArtifactResult:
    result = await store.get_artifacts(owner, task_id)
    if result is None:
        raise HTTPException(
            404,
            detail=RepairError(code="task_not_found", message="Repair task not found").model_dump(),
        )
    return result
