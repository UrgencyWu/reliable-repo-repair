import asyncio
import json
import shutil
import tempfile
from pathlib import Path
from uuid import UUID

from agent.config import ENV
from agent.repair.process import git


async def prepare_agent_repository(source: Path, base_commit: str, run_id: UUID) -> Path:
    configured = ENV.OPEN_SWE_LOCAL_WORKTREES_DIR.require()
    root = Path(configured).resolve() / "repair"
    await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
    destination = root / str(run_id)
    expected = {"repair_run_id": str(run_id), "base_commit": base_commit}
    if destination.exists():
        manifest = await asyncio.to_thread((destination / "origin.json").read_text)
        if json.loads(manifest) != expected or not (destination / "agent" / ".git").is_dir():
            raise RuntimeError("Existing repair workspace is unavailable or has a different base")
        # A reconnect retains the working tree; never reset it to the base.
        return destination / "agent"
    temporary_name = await asyncio.to_thread(
        tempfile.mkdtemp, prefix="repair-prepare-", dir=str(root)
    )
    assert isinstance(temporary_name, str)
    temporary = Path(temporary_name)
    try:
        await git(temporary, "clone", "--no-hardlinks", "--no-checkout", str(source), "agent")
        await git(temporary / "agent", "checkout", "--detach", base_commit)
        if (await git(temporary / "agent", "rev-parse", "HEAD")).decode().strip() != base_commit:
            raise RuntimeError("Repair checkout does not match the requested commit")
        await asyncio.to_thread((temporary / "origin.json").write_text, json.dumps(expected))
        await asyncio.to_thread(temporary.rename, destination)
    finally:
        if temporary.exists():
            await asyncio.to_thread(shutil.rmtree, temporary)
    return destination / "agent"
