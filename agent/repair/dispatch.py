import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import httpx

from agent.repair import dispatch_store, execution_store, recovery_store, validation_store
from agent.repair.adapter import RepairAdapter
from agent.repair.dispatch_store import Claim
from agent.repair.repository import prepare_agent_repository
from agent.repair.state import RepairStatus
from agent.repair.validation import IndependentValidator, ValidationLeaseLost

logger = logging.getLogger(__name__)


@asynccontextmanager
async def maintaining_lease(
    renew: Callable[[], Awaitable[bool]], context: Mapping[str, str | int]
) -> AsyncIterator[asyncio.Event]:
    lost = asyncio.Event()

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(5)
            try:
                if not await renew():
                    lost.set()
                    logger.warning("Repair execution lease lost", extra=context)
                    return
            except Exception:
                lost.set()
                logger.exception("Repair lease renewal failed", extra=context)
                return

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        yield lost
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            logger.debug("Repair lease heartbeat stopped", extra=context)


class RepairDispatcher:
    def __init__(
        self,
        adapter: RepairAdapter,
        worker_id: str,
        poll_seconds: float = 1,
        database_dispatch: bool = True,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("Repair poll interval must be positive")
        self.adapter = adapter
        self.worker_id = worker_id
        self.poll_seconds = poll_seconds
        self.database_dispatch = database_dispatch
        self.validator = IndependentValidator()

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                logger.exception(
                    "Repair dispatcher tick failed", extra={"worker_id": self.worker_id}
                )
            await asyncio.sleep(self.poll_seconds)

    async def tick(self) -> None:
        await recovery_store.expire_tasks()
        await self.stop_expired_runs()
        await dispatch_store.reconcile_expired_claims()
        for intent, run, task in await dispatch_store.unresolved_dispatches():
            try:
                found = await asyncio.wait_for(self.adapter.find_run(run, intent.id), timeout=10)
                if found is not None:
                    await dispatch_store.record_reconciled(intent.id, found)
            except httpx.HTTPError, TimeoutError:
                logger.warning(
                    "Repair dispatch reconciliation unavailable",
                    extra={
                        "repair_task_id": str(task.id),
                        "repair_run_id": str(run.id),
                        "thread_id": str(run.thread_id),
                    },
                    exc_info=True,
                )
            except ValueError as exc:
                await dispatch_store.defer_reconciliation_conflict(intent.id, str(exc))
                logger.exception(
                    "Repair dispatch reconciliation conflict",
                    extra={
                        "repair_task_id": str(task.id),
                        "repair_run_id": str(run.id),
                        "thread_id": str(run.thread_id),
                        "dispatch_intent_id": str(intent.id),
                    },
                )
        if self.database_dispatch:
            claim = await dispatch_store.claim_next(self.worker_id)
            if claim is not None:
                await self.dispatch(claim)
        execution = await execution_store.claim_execution(self.worker_id)
        if execution is None:
            return
        context = {
            "trace_id": str(execution.task.trace_id),
            "repair_task_id": str(execution.task.id),
            "repair_run_id": str(execution.run.id),
            "thread_id": str(execution.run.thread_id),
            "runtime_run_id": str(execution.run.runtime_run_id),
        }
        try:
            remaining = (execution.task.deadline_at - datetime.now(UTC)).total_seconds()
            async with (
                asyncio.timeout(max(0, remaining)),
                maintaining_lease(lambda: execution_store.renew_execution(execution), context),
            ):
                if execution.task.status == RepairStatus.VALIDATING:
                    attempt = await validation_store.start_validation(execution)
                    if attempt is None:
                        return
                    outcome = await self.validator.validate(
                        execution.task,
                        attempt.candidate,
                        Path(attempt.record.workspace),
                        lambda checks: validation_store.checkpoint_checks(
                            execution, attempt, checks
                        ),
                    )
                    accepted = await validation_store.finish_validation(execution, attempt, outcome)
                    logger.info(
                        "Independent validation finished",
                        extra={
                            **context,
                            "validation_status": outcome.status,
                            "validation_id": str(attempt.record.id),
                            "result_persisted": accepted,
                            "latency_seconds": outcome.duration_seconds,
                        },
                    )
                    return
                try:
                    status = await asyncio.wait_for(self.adapter.observe(execution.run), timeout=10)
                except httpx.HTTPStatusError as exc:
                    logger.warning(
                        "Repair Runtime observation failed", extra=context, exc_info=True
                    )
                    if exc.response.status_code == 404:
                        await execution_store.fail_execution(execution, "runtime_missing")
                    elif exc.response.status_code in {401, 403}:
                        await execution_store.fail_execution(execution, "runtime_access_denied")
                    return
                except httpx.HTTPError, TimeoutError:
                    logger.warning(
                        "Repair Runtime observation unavailable", extra=context, exc_info=True
                    )
                    return
                if status in {"pending", "running"}:
                    return
                if status != "success":
                    await execution_store.fail_execution(execution, f"runtime_{status}")
                    return
                workspace = execution.run.agent_workspace
                if workspace is None or not await asyncio.to_thread(
                    (Path(workspace) / ".git").is_dir
                ):
                    await execution_store.fail_execution(execution, "agent_workspace_lost")
                    return
                candidate = await self.adapter.collect(execution.task, execution.run)
                if await execution_store.store_candidate(execution, candidate):
                    logger.info(
                        "Repair candidate persisted for validation",
                        extra={**context, "patch_sha256": candidate.sha256, "phase": "VALIDATING"},
                    )
        except TimeoutError:
            logger.warning("Repair task execution deadline reached", extra=context)
            await recovery_store.expire_tasks()
        except ValidationLeaseLost:
            logger.warning("Independent validation lost its execution lease", extra=context)
        except Exception as exc:
            logger.exception("Repair execution observation failed", extra=context)
            await execution_store.fail_execution(execution, f"candidate_{type(exc).__name__}")
        finally:
            await execution_store.release_execution(execution)

    async def stop_expired_runs(self) -> None:
        for stop in await recovery_store.pending_stops():
            context = {
                "trace_id": str(stop.task.trace_id),
                "repair_task_id": str(stop.task.id),
                "repair_run_id": str(stop.run.id),
                "thread_id": str(stop.run.thread_id),
            }
            try:
                async with asyncio.timeout(10):
                    if stop.run.runtime_run_id is None:
                        found = await self.adapter.find_run(stop.run, stop.dispatch_id)
                        if found is None:
                            if (datetime.now(UTC) - stop.task.deadline_at).total_seconds() > 60:
                                await recovery_store.record_stop(
                                    stop.run.id,
                                    finished=True,
                                    error="runtime_creation_unresolved_after_deadline",
                                )
                            continue
                        await recovery_store.record_stop(
                            stop.run.id, finished=False, runtime_id=found
                        )
                        stop.run.runtime_run_id = found
                    status = await self.adapter.observe(stop.run)
                    if status in {"pending", "running"}:
                        await self.adapter.stop(stop.run)
                        status = await self.adapter.observe(stop.run)
                    if (
                        status in {"pending", "running"}
                        and (datetime.now(UTC) - stop.task.deadline_at).total_seconds() > 60
                    ):
                        await recovery_store.record_stop(
                            stop.run.id, finished=True, error="runtime_stop_unconfirmed"
                        )
                    elif status not in {"pending", "running"}:
                        await recovery_store.record_stop(stop.run.id, finished=True)
                        logger.info(
                            "Timed out repair Runtime is terminal",
                            extra={**context, "runtime_status": status},
                        )
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "Timed out repair Runtime lookup failed", extra=context, exc_info=True
                )
                missing = exc.response.status_code == 404 and stop.run.runtime_run_id is not None
                exhausted = (datetime.now(UTC) - stop.task.deadline_at).total_seconds() > 60
                await recovery_store.record_stop(
                    stop.run.id,
                    finished=missing or exhausted,
                    error="runtime_missing"
                    if missing
                    else "runtime_stop_unconfirmed"
                    if exhausted
                    else "runtime_stop_unavailable",
                )
            except Exception as exc:
                logger.warning(
                    "Timed out repair Runtime stop unconfirmed", extra=context, exc_info=True
                )
                exhausted = (datetime.now(UTC) - stop.task.deadline_at).total_seconds() > 60
                await recovery_store.record_stop(
                    stop.run.id,
                    finished=exhausted,
                    error="runtime_stop_unconfirmed" if exhausted else type(exc).__name__,
                )

    async def dispatch(self, claim: Claim) -> None:
        start = perf_counter()
        context = {
            "trace_id": str(claim.task.trace_id),
            "repair_task_id": str(claim.task.id),
            "repair_run_id": str(claim.run.id),
            "thread_id": str(claim.run.thread_id),
            "dispatch_intent_id": str(claim.intent.id),
            "dispatch_attempts": claim.intent.attempt_count,
        }
        creating_run = False
        try:
            remaining = (claim.task.deadline_at - datetime.now(UTC)).total_seconds()
            async with (
                asyncio.timeout(max(0, remaining)),
                maintaining_lease(
                    lambda: dispatch_store.renew_claim(claim.intent.id, claim.token), context
                ) as lost,
            ):
                workspace = await prepare_agent_repository(
                    Path(claim.task.validation_plan["source_path"]),
                    claim.task.target_commit,
                    claim.run.id,
                )
                if not await dispatch_store.record_workspace(
                    claim.intent.id, claim.token, workspace
                ):
                    return
                claim.run.agent_workspace = str(workspace)
                await asyncio.wait_for(
                    self.adapter.ensure_thread(claim.task, claim.run), timeout=10
                )
                if lost.is_set() or not await dispatch_store.renew_claim(
                    claim.intent.id, claim.token
                ):
                    return
                creating_run = True
                runtime_id = await asyncio.wait_for(
                    self.adapter.start(claim.task, claim.run, claim.intent.id), timeout=15
                )
                accepted = await dispatch_store.record_dispatch(
                    claim.intent.id, claim.token, runtime_id
                )
                logger.info(
                    "Repair Runtime dispatch returned",
                    extra={
                        **context,
                        "runtime_run_id": str(runtime_id),
                        "reference_persisted": accepted,
                        "latency_seconds": perf_counter() - start,
                    },
                )
        except Exception as exc:
            logger.exception(
                "Repair Runtime dispatch failed",
                extra={**context, "create_outcome_unknown": creating_run},
            )
            await dispatch_store.record_dispatch_failure(
                claim.intent.id,
                claim.token,
                type(exc).__name__,
                definitely_not_created=not creating_run,
                retryable=isinstance(exc, (httpx.HTTPError, TimeoutError)),
            )
