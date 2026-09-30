import asyncio
import hashlib
import logging
import platform
import shutil
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Literal

from agent.config import ENV
from agent.repair.models import CandidateArtifact, CheckPayload, RepairTask
from agent.repair.process import CommandTimeout, git, run_command

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidationOutcome:
    status: Literal["PASS", "FAIL", "ERROR"]
    error_type: str | None
    checks: list[CheckPayload]
    manifest: dict[str, str]
    duration_seconds: float


class ValidationLeaseLost(RuntimeError):
    pass


class IndependentValidator:
    async def validate(
        self,
        task: RepairTask,
        candidate: CandidateArtifact,
        workspace: Path,
        on_check: Callable[[list[CheckPayload]], Awaitable[bool]] | None = None,
    ) -> ValidationOutcome:
        start = perf_counter()
        checks: list[CheckPayload] = []
        owns_workspace = False
        manifest = {
            "provider": "trusted_local_checkout",
            "base_commit": task.target_commit,
            "candidate_sha256": candidate.sha256,
            "python_version": sys.version,
            "platform": platform.platform(),
            "environment": "explicit PATH/Git config/LANG; no inherited host secrets",
        }
        timeout = float(ENV.REPAIR_VALIDATION_TIMEOUT_SECONDS.get())
        if timeout <= 0:
            raise ValueError("Validation command timeout must be positive")

        async def check(
            name: str, argv: list[str], input_data: bytes | None = None
        ) -> CheckPayload:
            remaining = (task.deadline_at - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                raise TimeoutError("Repair task deadline exceeded")
            timed_out = False
            try:
                result = await run_command(
                    argv, workspace, timeout=min(timeout, remaining), input_data=input_data
                )
            except CommandTimeout as exc:
                result = exc.result
                timed_out = True
                logger.warning(
                    "Independent validation command timed out",
                    extra={
                        "repair_task_id": str(task.id),
                        "validation_workspace": str(workspace),
                        "check_name": name,
                    },
                )
            evidence: CheckPayload = {
                "name": name,
                "argv": argv,
                "exit_code": result.exit_code,
                "output": result.output.decode(errors="replace"),
                "truncated": result.truncated,
                "timed_out": timed_out,
                "duration_seconds": result.duration_seconds,
            }
            checks.append(evidence)
            if on_check is not None and not await on_check(list(checks)):
                raise ValidationLeaseLost("Validation owner no longer holds the execution lease")
            if timed_out:
                raise TimeoutError("Independent validation command timed out")
            return evidence

        async def outcome(
            status: Literal["PASS", "FAIL", "ERROR"], reason: str | None
        ) -> ValidationOutcome:
            return ValidationOutcome(status, reason, checks, manifest, perf_counter() - start)

        try:
            if candidate.base_commit != task.target_commit:
                return await outcome("FAIL", "candidate_base_mismatch")
            if hashlib.sha256(candidate.patch).hexdigest() != candidate.sha256:
                return await outcome("FAIL", "candidate_hash_mismatch")
            if workspace.exists():
                raise ValueError("Validator requires a fresh workspace")
            await asyncio.to_thread(workspace.parent.mkdir, parents=True, exist_ok=True)
            owns_workspace = True
            await git(
                workspace.parent,
                "clone",
                "--no-hardlinks",
                "--no-checkout",
                task.validation_plan["source_path"],
                str(workspace),
            )
            await git(workspace, "checkout", "--detach", task.target_commit)
            if (
                await git(workspace, "rev-parse", "HEAD")
            ).decode().strip() != task.target_commit or await git(
                workspace, "status", "--porcelain"
            ):
                raise RuntimeError("Validator checkout is not a clean target commit")
            baseline = await check("BASELINE", task.validation_plan["target_argv"])
            if baseline["exit_code"] == 0:
                return await outcome("FAIL", "failure_not_reproduced")
            if baseline["exit_code"] != 1:
                return await outcome("ERROR", "baseline_command_error")
            apply_check = await check(
                "PATCH_CHECK", ["git", "apply", "--check", "-"], candidate.patch
            )
            if apply_check["exit_code"] != 0:
                return await outcome("FAIL", "patch_apply_failed")
            applied = await check("PATCH_APPLY", ["git", "apply", "-"], candidate.patch)
            if applied["exit_code"] != 0:
                return await outcome("FAIL", "patch_apply_failed")
            changed = await git(workspace, "diff", "--name-only", "-z", task.target_commit)
            new_files = await git(workspace, "ls-files", "--others", "--exclude-standard", "-z")
            actual = sorted({path.decode() for path in (changed + new_files).split(b"\0") if path})
            if actual != sorted(candidate.files_changed) or any(
                path not in task.validation_plan["allowed_patch_paths"] for path in actual
            ):
                return await outcome("FAIL", "candidate_file_policy")
            target = await check("TARGET", task.validation_plan["target_argv"])
            if target["exit_code"] != 0:
                return await outcome("FAIL", "target_test_failed")
            for index, argv in enumerate(task.validation_plan["regression_argv"]):
                regression = await check(f"REGRESSION_{index + 1}", argv)
                if regression["exit_code"] != 0:
                    return await outcome("FAIL", "regression_test_failed")
            return await outcome("PASS", None)
        except ValidationLeaseLost:
            raise
        except Exception as exc:
            logger.exception(
                "Independent validation failed",
                extra={
                    "repair_task_id": str(task.id),
                    "candidate_id": str(candidate.id),
                    "validation_workspace": str(workspace),
                },
            )
            return await outcome("ERROR", type(exc).__name__)
        finally:
            # Each attempt owns this disposable checkout; no agent files are removed.
            if owns_workspace and workspace.exists():
                await asyncio.to_thread(shutil.rmtree, workspace)
