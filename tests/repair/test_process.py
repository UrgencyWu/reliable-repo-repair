import asyncio
import shlex
import shutil
import sys
from pathlib import Path

import pytest

from agent.repair.process import MAX_OUTPUT_BYTES, git, run_command

pytestmark = pytest.mark.asyncio


async def test_bounded_output_is_drained_concurrently_with_stdin(tmp_path: Path) -> None:
    result = await run_command(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('x' * 2000000); sys.stdout.flush(); assert len(sys.stdin.buffer.read()) == 2000000",
        ],
        tmp_path,
        input_data=b"a" * 2000000,
    )
    assert result.exit_code == 0
    assert result.truncated is True and len(result.output) == MAX_OUTPUT_BYTES


async def test_command_environment_does_not_inherit_host_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REPAIR_TEST_SECRET", "host-only-test-value")
    result = await run_command(
        [
            sys.executable,
            "-c",
            "import os; assert 'REPAIR_TEST_SECRET' not in os.environ; raise SystemExit(3)",
        ],
        tmp_path,
    )
    assert result.exit_code == 3


async def test_timeout_cleans_up_child_process(tmp_path: Path) -> None:
    script = "import subprocess,sys,time; subprocess.Popen([sys.executable, '-c', \"import time; from pathlib import Path; time.sleep(0.5); Path('leaked-child').touch()\"]); time.sleep(10)"
    with pytest.raises(TimeoutError):
        await run_command([sys.executable, "-c", script], tmp_path, timeout=0.1)
    await asyncio.sleep(0.7)
    assert not (tmp_path / "leaked-child").exists()


async def test_git_machine_output_is_not_corrupted_by_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    actual_git = shutil.which("git")
    assert actual_git is not None
    binaries = tmp_path / "bin"
    binaries.mkdir()
    wrapper = binaries / "git"
    wrapper.write_text(
        f"#!/bin/sh\nprintf 'diagnostic warning\\n' >&2\nexec {shlex.quote(actual_git)} \"$@\"\n"
    )
    wrapper.chmod(0o700)
    monkeypatch.setenv("REPAIR_EXECUTION_PATH", str(binaries))
    await git(tmp_path, "init")
    assert (await git(tmp_path, "rev-parse", "--git-dir")).strip() == b".git"
    with pytest.raises(RuntimeError, match="diagnostic warning"):
        await git(tmp_path, "rev-parse", "missing-revision")
