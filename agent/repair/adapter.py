import asyncio
import base64
import hashlib
import json
import logging
import sys
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

import httpx
from langgraph_sdk.client import LangGraphClient
from langgraph_sdk.schema import RunStatus
from pydantic import BaseModel, Field

from agent.prompts import prompt
from agent.repair.models import RepairRun, RepairTask
from agent.repair.process import git, run_command

MAX_PATCH_BYTES = 5 * 1024 * 1024
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Candidate:
    base_commit: str
    sha256: str
    patch: bytes
    files_changed: list[str]


class ExportResult(BaseModel):
    ok: bool
    path: Path
    size: int = Field(gt=0, le=MAX_PATCH_BYTES)
    base_commit: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RepairAdapter(Protocol):
    async def ensure_thread(self, task: RepairTask, run: RepairRun) -> None: ...
    async def start(self, task: RepairTask, run: RepairRun, intent_id: UUID) -> UUID: ...
    async def find_run(self, run: RepairRun, intent_id: UUID) -> UUID | None: ...
    async def observe(self, run: RepairRun) -> RunStatus: ...
    async def collect(self, task: RepairTask, run: RepairRun) -> Candidate: ...

    async def stop(self, run: RepairRun) -> None: ...


class OpenSweAgentAdapter:
    def __init__(self, client: LangGraphClient) -> None:
        self.client = client

    async def ensure_thread(self, task: RepairTask, run: RepairRun) -> None:
        thread = await self.client.threads.create(
            thread_id=str(run.thread_id),
            if_exists="do_nothing",
            metadata={
                "repair_task_id": str(task.id),
                "repair_run_id": str(run.id),
                "trace_id": str(task.trace_id),
            },
        )
        if (thread["metadata"] or {}).get("repair_run_id") != str(run.id):
            raise ValueError("Runtime thread belongs to a different repair run")

    async def start(self, task: RepairTask, run: RepairRun, intent_id: UUID) -> UUID:
        if run.agent_workspace is None:
            raise ValueError("Repair run has no assigned workspace")
        content = await asyncio.to_thread(
            prompt,
            "repair/task",
            {
                "repair_task_id": str(task.id),
                "repair_run_id": str(run.id),
                "fixture_id": task.fixture_id,
                "target_commit": task.target_commit,
                "failing_command": task.failing_command,
                "constraints": task.constraints,
                "allowed_paths": ", ".join(task.validation_plan["allowed_patch_paths"]),
            },
        )
        created = await self.client.runs.create(
            str(run.thread_id),
            "agent",
            input={"messages": [{"role": "user", "content": content}]},
            config={
                "configurable": {"source": "desktop", "local_project_path": run.agent_workspace}
            },
            metadata={
                "repair_task_id": str(task.id),
                "repair_run_id": str(run.id),
                "dispatch_intent_id": str(intent_id),
                "trace_id": str(task.trace_id),
            },
            multitask_strategy="reject",
        )
        return UUID(created["run_id"])

    async def find_run(self, run: RepairRun, intent_id: UUID) -> UUID | None:
        found: list[UUID] = []
        offset = 0
        while True:
            try:
                page = await self.client.runs.list(str(run.thread_id), limit=100, offset=offset)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise
                # A missing thread does not prove an older create request cannot still finish.
                logger.debug(
                    "Runtime thread absent during reconciliation",
                    extra={"repair_run_id": str(run.id), "thread_id": str(run.thread_id)},
                )
                return None
            for item in page:
                metadata = item["metadata"] or {}
                if metadata.get("repair_run_id") == str(run.id) and metadata.get(
                    "dispatch_intent_id"
                ) == str(intent_id):
                    found.append(UUID(item["run_id"]))
            if len(page) < 100:
                break
            offset += len(page)
        if len(found) > 1:
            raise ValueError("Multiple Runtime runs found for one dispatch intent")
        return found[0] if found else None

    async def observe(self, run: RepairRun) -> RunStatus:
        if run.runtime_run_id is None:
            raise ValueError("Repair run has no Runtime run reference")
        result = await self.client.runs.get(str(run.thread_id), str(run.runtime_run_id))
        return result["status"]

    async def stop(self, run: RepairRun) -> None:
        if run.runtime_run_id is None:
            raise ValueError("Repair run has no Runtime run reference")
        await self.client.runs.cancel(
            str(run.thread_id), str(run.runtime_run_id), wait=False, action="interrupt"
        )

    async def collect(self, task: RepairTask, run: RepairRun) -> Candidate:
        if run.agent_workspace is None:
            raise ValueError("Repair run has no workspace")
        repo = Path(run.agent_workspace)
        key = f"repair-export-{uuid4().hex}"
        patch_path = Path("/tmp") / f"{key}.patch"
        payload = {"repo_path": str(repo), "base_commit": task.target_commit, "thread_key": key}
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        script = await asyncio.to_thread(
            resources.files("agent.resources").joinpath("recovery_patch.py").read_text
        )
        try:
            result = await run_command(
                [sys.executable, "-"],
                repo,
                input_data=script.replace("__PAYLOAD__", encoded).encode(),
            )
            if result.exit_code != 0 or result.truncated:
                raise RuntimeError(result.output.decode(errors="replace") or "Patch export failed")
            exported = ExportResult.model_validate_json(result.output)
            if (
                not exported.ok
                or exported.path != patch_path
                or exported.base_commit != task.target_commit
            ):
                raise ValueError("Patch exporter returned a different path or base")
            patch = await asyncio.to_thread(patch_path.read_bytes)
            if len(patch) != exported.size or hashlib.sha256(patch).hexdigest() != exported.sha256:
                raise ValueError("Patch content does not match exporter hash or size")
            changed = await git(repo, "diff", "--name-only", "-z", task.target_commit)
            untracked = await git(repo, "ls-files", "--others", "--exclude-standard", "-z")
            files = sorted({item.decode() for item in (changed + untracked).split(b"\0") if item})
            if not files or any(
                path not in task.validation_plan["allowed_patch_paths"] for path in files
            ):
                raise ValueError("Candidate modified files outside the configured patch policy")
            indexed = await git(repo, "ls-files", "--stage", "--", *files)
            base_tree = await git(repo, "ls-tree", task.target_commit, "--", *files)
            if any(
                line.startswith((b"120000 ", b"160000 "))
                for line in (indexed + base_tree).splitlines()
            ) or any((repo / path).is_symlink() for path in files):
                raise ValueError("Repair MVP does not support symlink or submodule patches")
            return Candidate(exported.base_commit, exported.sha256, patch, files)
        finally:
            await asyncio.to_thread(patch_path.unlink, missing_ok=True)
