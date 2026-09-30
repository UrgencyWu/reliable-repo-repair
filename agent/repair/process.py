import asyncio
import logging
import os
import signal
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from agent.config import ENV

MAX_OUTPUT_BYTES = 1024 * 1024
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandResult:
    exit_code: int
    output: bytes
    truncated: bool
    duration_seconds: float
    stderr: bytes = b""


class CommandTimeout(TimeoutError):
    def __init__(self, result: CommandResult) -> None:
        super().__init__("Repository command timed out")
        self.result = result


async def run_command(
    argv: Sequence[str],
    cwd: Path,
    *,
    timeout: float = 20,
    input_data: bytes | None = None,
    merge_stderr: bool = True,
) -> CommandResult:
    start = perf_counter()
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        start_new_session=True,
        env={
            "PATH": ENV.REPAIR_EXECUTION_PATH.get(default=os.defpath),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "PYTHONDONTWRITEBYTECODE": "1",
            "LANG": "C.UTF-8",
        },
        stdin=asyncio.subprocess.PIPE if input_data is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT if merge_stderr else asyncio.subprocess.PIPE,
    )
    output = bytearray()
    errors = bytearray()
    truncated = False

    async def feed_stdin() -> None:
        if process.stdin is not None:
            try:
                process.stdin.write(input_data or b"")
                await process.stdin.drain()
            except BrokenPipeError, ConnectionResetError:
                logger.debug("Command closed its input stream", extra={"process_id": process.pid})
            finally:
                process.stdin.close()

    async def read_pipe(pipe: asyncio.StreamReader, destination: bytearray) -> None:
        nonlocal truncated
        while data := await pipe.read(65536):
            available = MAX_OUTPUT_BYTES - len(output) - len(errors)
            destination.extend(data[:available])
            truncated |= len(data) > available

    async def communicate() -> None:
        async with asyncio.TaskGroup() as group:
            group.create_task(feed_stdin())
            assert process.stdout is not None
            group.create_task(read_pipe(process.stdout, output))
            if process.stderr is not None:
                group.create_task(read_pipe(process.stderr, errors))
        await process.wait()

    try:
        await asyncio.wait_for(communicate(), timeout=timeout)
    except BaseException as exc:
        # Kill the command's process group, including children retaining stdout.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            logger.debug("Command process group already exited", extra={"process_id": process.pid})
        await process.wait()
        if isinstance(exc, TimeoutError):
            raise CommandTimeout(
                CommandResult(
                    process.returncode or 0,
                    bytes(output),
                    truncated,
                    perf_counter() - start,
                    bytes(errors),
                )
            ) from exc
        raise
    assert process.returncode is not None
    return CommandResult(
        process.returncode, bytes(output), truncated, perf_counter() - start, bytes(errors)
    )


async def git(cwd: Path, *args: str, timeout: float = 20) -> bytes:
    result = await run_command(["git", *args], cwd, timeout=timeout, merge_stderr=False)
    if result.exit_code != 0 or result.truncated:
        raise RuntimeError(
            (result.output + result.stderr).decode(errors="replace") or "Git command failed"
        )
    if result.stderr:
        logger.debug(
            "Git diagnostic output", extra={"git_stderr": result.stderr.decode(errors="replace")}
        )
    return result.output
