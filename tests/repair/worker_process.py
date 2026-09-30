"""Test-only dispatcher process against the parent's isolated PostgreSQL schema."""

import argparse
import asyncio
import re
from pathlib import Path
from uuid import UUID

from langgraph_sdk import get_client
from langgraph_sdk.client import LangGraphClient

from agent.database import postgres
from agent.repair.adapter import OpenSweAgentAdapter
from agent.repair.dispatch import RepairDispatcher
from agent.repair.models import RepairRun, RepairTask
from agent.users import User  # Register the existing users FK target in this process.


class PauseAfterCreateAdapter(OpenSweAgentAdapter):
    def __init__(self, client: LangGraphClient, marker: Path) -> None:
        super().__init__(client)
        self.marker = marker

    async def start(self, task: RepairTask, run: RepairRun, intent_id: UUID) -> UUID:
        runtime_id = await super().start(task, run, intent_id)
        await asyncio.to_thread(self.marker.write_text, str(runtime_id))
        await asyncio.sleep(60)
        return runtime_id


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("schema")
    parser.add_argument("runtime_url")
    parser.add_argument("worker_id")
    parser.add_argument("--pause-after-create", type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"open_swe_test_[0-9a-f]{32}", args.schema):
        raise ValueError("Worker process tests require an isolated test schema")
    assert User.__tablename__ == "users"
    postgres.SCHEMA = args.schema
    async with get_client(url=args.runtime_url, timeout=10) as client:
        adapter = (
            PauseAfterCreateAdapter(client, args.pause_after_create)
            if args.pause_after_create
            else OpenSweAgentAdapter(client)
        )
        await RepairDispatcher(adapter, args.worker_id, poll_seconds=0.1).run()


if __name__ == "__main__":
    asyncio.run(main())
