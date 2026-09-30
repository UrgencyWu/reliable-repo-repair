"""Opt-in smoke against the real server configured by tests/repair/langgraph.json."""

import asyncio
import base64
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
from langgraph_sdk import get_client


@pytest.mark.asyncio
async def test_real_agent_patch_replays_in_clean_checkout() -> None:
    url = os.environ.get("REPAIR_TEST_RUNTIME_URL")
    worktrees = os.environ.get("OPEN_SWE_LOCAL_WORKTREES_DIR")
    if not url or not worktrees:
        pytest.skip("REPAIR_TEST_RUNTIME_URL and server's OPEN_SWE_LOCAL_WORKTREES_DIR required")
    root = Path(worktrees).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="repair-runtime-", dir=root) as temporary:
        agent_repo = Path(temporary) / "agent"
        validator_repo = Path(temporary) / "validator"
        agent_repo.mkdir()
        environment = {
            "PATH": os.environ["PATH"],
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "Repair Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Repair Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            "PYTHONDONTWRITEBYTECODE": "1",
        }

        async def command(
            cwd: Path, *args: str, input_data: bytes | None = None
        ) -> tuple[int, bytes]:
            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=cwd,
                env=environment,
                stdin=asyncio.subprocess.PIPE if input_data is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            output, _ = await asyncio.wait_for(process.communicate(input_data), 20)
            assert process.returncode is not None
            return process.returncode, output

        async def git(cwd: Path, *args: str) -> bytes:
            code, output = await command(cwd, "git", *args)
            assert code == 0, output.decode(errors="replace")
            return output

        await git(agent_repo, "init", "--initial-branch=main")
        (agent_repo / "calc.py").write_text("def add(a, b):\n    return a - b\n")
        (agent_repo / "test_calc.py").write_text(
            "import unittest\nfrom calc import add\n"
            "class ArithmeticTest(unittest.TestCase):\n"
            "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n"
        )
        (agent_repo / ".gitignore").write_text("__pycache__/\n")
        await git(agent_repo, "add", ".")
        await git(agent_repo, "commit", "-m", "broken fixture")
        base = (await git(agent_repo, "rev-parse", "HEAD")).decode().strip()
        await git(Path(temporary), "clone", "--no-hardlinks", str(agent_repo), str(validator_repo))
        await git(validator_repo, "checkout", "--detach", base)
        code, output = await command(
            validator_repo, sys.executable, "-m", "unittest", "test_calc.py"
        )
        assert code == 1 and b"AssertionError: -1 != 5" in output

        client = get_client(url=url)
        thread_id = str(uuid4())
        run_key = str(uuid4())
        await client.threads.create(thread_id=thread_id, metadata={"repair_run_id": run_key})
        try:
            run = await client.runs.create(
                thread_id,
                "agent",
                input={
                    "messages": [{"role": "user", "content": "E2E_REPAIR_FIXTURE: fix calc.py"}]
                },
                config={
                    "configurable": {"source": "desktop", "local_project_path": str(agent_repo)}
                },
                metadata={"repair_run_id": run_key},
                multitask_strategy="reject",
            )
            await asyncio.wait_for(client.runs.join(thread_id, run["run_id"]), 60)
            finished = await client.runs.get(thread_id, run["run_id"])
            assert finished["status"] == "success", finished
            runs = await client.runs.list(thread_id, limit=10)
            matched = [item for item in runs if item["metadata"].get("repair_run_id") == run_key]
            assert len(matched) == 1 and matched[0]["run_id"] == run["run_id"]
            state = await client.threads.get_state(thread_id)
            messages = state["values"]["messages"]
            tool_messages = [item for item in messages if item.get("type") == "tool"]
            assert len(tool_messages) == 3, messages
            assert b"return a + b" in (agent_repo / "calc.py").read_bytes()

            payload = {"repo_path": str(agent_repo), "base_commit": base, "thread_key": thread_id}
            encoded = base64.b64encode(json.dumps(payload).encode()).decode()
            script = (
                Path("agent/resources/recovery_patch.py")
                .read_text()
                .replace("__PAYLOAD__", encoded)
            )
            code, output = await command(
                agent_repo, sys.executable, "-", input_data=script.encode()
            )
            assert code == 0, output.decode(errors="replace")
            result = json.loads(output)
            patch_path = Path(result["path"])
            try:
                patch = patch_path.read_bytes()
                assert result["base_commit"] == base
                assert result["sha256"] == hashlib.sha256(patch).hexdigest()
                code, output = await command(
                    validator_repo, "git", "apply", "--check", "-", input_data=patch
                )
                assert code == 0, output.decode(errors="replace")
                code, output = await command(validator_repo, "git", "apply", "-", input_data=patch)
                assert code == 0, output.decode(errors="replace")
                code, output = await command(
                    validator_repo, sys.executable, "-m", "unittest", "test_calc.py"
                )
                assert code == 0 and b"OK" in output, output.decode(errors="replace")
                assert (
                    await git(validator_repo, "diff", "--name-only")
                ).decode().strip() == "calc.py"
            finally:
                patch_path.unlink(missing_ok=True)
        finally:
            await client.threads.delete(thread_id)
