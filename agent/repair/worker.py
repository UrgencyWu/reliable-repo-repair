"""Standalone PostgreSQL-backed repair dispatcher, observer and validator."""

import asyncio
import json
import logging
import signal
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from langgraph_sdk import get_client
from sqlalchemy import text

from agent.config import ENV
from agent.database import postgres
from agent.repair.adapter import OpenSweAgentAdapter
from agent.repair.config import load_fixtures
from agent.repair.dispatch import RepairDispatcher
from agent.repair.stream import RepairStreamTransport
from agent.users import User

logger = logging.getLogger(__name__)


class WorkerLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "service": "repair-worker",
            "event": record.getMessage(),
        }
        for key in (
            "worker_id",
            "trace_id",
            "repair_task_id",
            "repair_run_id",
            "thread_id",
            "runtime_run_id",
            "dispatch_intent_id",
            "dispatch_attempts",
            "phase",
            "patch_sha256",
            "validation_id",
            "validation_status",
            "latency_seconds",
            "result_persisted",
            "reference_persisted",
            "create_outcome_unknown",
        ):
            if key in record.__dict__:
                payload[key] = record.__dict__[key]
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


@asynccontextmanager
async def repair_worker() -> AsyncIterator[None]:
    if not ENV.REPAIR_ENABLED.get_bool():
        raise ValueError("Standalone repair worker requires REPAIR_ENABLED=true")
    postgres.require_configured()
    if not await load_fixtures():
        raise ValueError("Repair worker requires configured fixtures")
    ENV.OPEN_SWE_LOCAL_WORKTREES_DIR.require()
    runtime_url = ENV.LANGGRAPH_URL.require()
    # Register the existing User mapper used by repair ownership/FK relationships.
    assert User.__tablename__ == "users"
    async with postgres.connection() as connection:
        await connection.execute(text("SELECT 1 FROM repair_dispatch_intent LIMIT 1"))
    async with get_client(url=runtime_url, timeout=10) as client:
        worker_id = f"repair-{uuid4()}"
        redis_url = ENV.REPAIR_REDIS_URL.optional()
        dispatcher = RepairDispatcher(
            OpenSweAgentAdapter(client),
            worker_id,
            float(ENV.REPAIR_POLL_SECONDS.get()),
            database_dispatch=redis_url is None,
        )
        transport = (
            asyncio.create_task(
                RepairStreamTransport(redis_url, dispatcher).run(), name=f"{worker_id}-stream"
            )
            if redis_url is not None
            else None
        )
        task = asyncio.create_task(dispatcher.run(), name=worker_id)
        logger.info("Repair worker started", extra={"worker_id": worker_id})
        try:
            yield
        finally:
            task.cancel()
            if transport is not None:
                transport.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.info("Repair worker stopped", extra={"worker_id": worker_id})
            if transport is not None:
                try:
                    await transport
                except asyncio.CancelledError:
                    logger.info("Repair Stream transport stopped", extra={"worker_id": worker_id})


async def main() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(WorkerLogFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    try:
        async with repair_worker():
            await stop.wait()
    finally:
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(signum)
        await postgres.close()


if __name__ == "__main__":
    asyncio.run(main())
