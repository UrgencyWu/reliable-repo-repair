from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid7

from sqlalchemy import func, select

from agent.config import ENV
from agent.database import postgres
from agent.repair.execution_store import ExecutionClaim, owned_run
from agent.repair.models import CandidateArtifact, CheckPayload, RepairTask, ValidationRecord
from agent.repair.service import transition_task
from agent.repair.state import RepairStatus
from agent.repair.validation import ValidationOutcome


@dataclass(frozen=True)
class ValidationAttempt:
    record: ValidationRecord
    candidate: CandidateArtifact


async def start_validation(claim: ExecutionClaim) -> ValidationAttempt | None:
    async with postgres.session() as session:
        run = await owned_run(session, claim)
        if run is None:
            return None
        task = await session.scalar(
            select(RepairTask).where(RepairTask.id == run.task_id).with_for_update()
        )
        assert task is not None
        now = await session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        if task.status != RepairStatus.VALIDATING or task.deadline_at <= now:
            return None
        candidate = await session.scalar(
            select(CandidateArtifact).where(CandidateArtifact.repair_run_id == run.id)
        )
        if candidate is None:
            raise ValueError("VALIDATING repair run has no persisted candidate")
        previous = list(
            await session.scalars(
                select(ValidationRecord)
                .where(ValidationRecord.repair_run_id == run.id)
                .order_by(ValidationRecord.attempt_no)
            )
        )
        for abandoned in previous:
            if abandoned.status == "RUNNING":
                abandoned.status = "ERROR"
                abandoned.error_type = "validation_owner_lost"
                abandoned.ended_at = now
        if len(previous) >= 3:
            task.failure_reason = "validation_recovery_exhausted"
            task.updated_at = now
            run.ended_at = now
            await transition_task(session, task, run, RepairStatus.FAILED)
            return None
        validation_id = uuid7()
        workspace = (
            Path(ENV.OPEN_SWE_LOCAL_WORKTREES_DIR.require()).resolve()
            / "repair-validation"
            / str(validation_id)
        )
        record = ValidationRecord(
            id=validation_id,
            repair_run_id=run.id,
            candidate_id=candidate.id,
            attempt_no=len(previous) + 1,
            execution_token=claim.token,
            workspace=str(workspace),
        )
        session.add(record)
        await session.flush()
        return ValidationAttempt(record, candidate)


async def checkpoint_checks(
    claim: ExecutionClaim, attempt: ValidationAttempt, checks: list[CheckPayload]
) -> bool:
    async with postgres.session() as session:
        if await owned_run(session, claim) is None:
            return False
        record = await session.get(ValidationRecord, attempt.record.id)
        if record is None or record.status != "RUNNING" or record.execution_token != claim.token:
            return False
        record.checks = checks
        return True


async def finish_validation(
    claim: ExecutionClaim, attempt: ValidationAttempt, outcome: ValidationOutcome
) -> bool:
    async with postgres.session() as session:
        run = await owned_run(session, claim)
        if run is None:
            return False
        task = await session.scalar(
            select(RepairTask).where(RepairTask.id == run.task_id).with_for_update()
        )
        assert task is not None
        now = await session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        if task.status != RepairStatus.VALIDATING or task.deadline_at <= now:
            return False
        record = await session.get(ValidationRecord, attempt.record.id)
        if record is None or record.status != "RUNNING" or record.execution_token != claim.token:
            return False
        if outcome.status == "PASS":
            checks = outcome.checks
            expected = ["BASELINE", "PATCH_CHECK", "PATCH_APPLY", "TARGET"] + [
                f"REGRESSION_{index + 1}"
                for index in range(len(task.validation_plan["regression_argv"]))
            ]
            expected_argv = [
                task.validation_plan["target_argv"],
                ["git", "apply", "--check", "-"],
                ["git", "apply", "-"],
                task.validation_plan["target_argv"],
                *task.validation_plan["regression_argv"],
            ]
            if (
                [check["argv"] for check in checks] != expected_argv
                or outcome.manifest.get("base_commit") != attempt.candidate.base_commit
                or outcome.manifest.get("candidate_sha256") != attempt.candidate.sha256
                or [check["name"] for check in checks] != expected
                or checks[0]["exit_code"] != 1
                or any(check["exit_code"] != 0 for check in checks[1:])
                or any(check["timed_out"] for check in checks)
            ):
                raise ValueError("PASS requires complete baseline/apply/target/regression evidence")
        record.status = outcome.status
        record.error_type = outcome.error_type
        record.checks = outcome.checks
        record.manifest = outcome.manifest
        record.duration_seconds = outcome.duration_seconds
        record.ended_at = now
        task.failure_reason = outcome.error_type
        task.updated_at = now
        run.ended_at = now
        await transition_task(
            session,
            task,
            run,
            RepairStatus.COMPLETED if outcome.status == "PASS" else RepairStatus.FAILED,
            {
                "validation_id": str(record.id),
                "validation_status": outcome.status,
                "latency_seconds": outcome.duration_seconds,
            },
        )
        return True
