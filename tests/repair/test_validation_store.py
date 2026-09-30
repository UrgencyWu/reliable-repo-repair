import hashlib
from pathlib import Path
from uuid import uuid7

import pytest
from sqlalchemy import select

from agent.database import postgres
from agent.repair import dispatch_store, execution_store, store, validation_store
from agent.repair.adapter import Candidate
from agent.repair.execution_store import ExecutionClaim
from agent.repair.models import CandidateArtifact, RepairTask, ValidationRecord
from agent.repair.process import git
from agent.repair.validation import IndependentValidator, ValidationOutcome
from agent.repair.validation_store import ValidationAttempt
from tests.repair.test_adapter_integration import make_task_input

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("registry_db")]


async def prepare_validation(tmp_path: Path) -> tuple[ExecutionClaim, ValidationAttempt]:
    owner, body, plan = await make_task_input(tmp_path)
    task = await store.create_task(owner, "validator", body, 60, plan)
    dispatched = await dispatch_store.claim_next("producer")
    assert dispatched is not None and dispatched.task.id == task.id
    assert await dispatch_store.record_dispatch(dispatched.intent.id, dispatched.token, uuid7())
    claim = await execution_store.claim_execution("validator")
    assert claim is not None
    source = Path(plan["source_path"])
    (source / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    patch = await git(source, "diff", "--binary", body.target_commit)
    candidate = Candidate(body.target_commit, hashlib.sha256(patch).hexdigest(), patch, ["calc.py"])
    assert await execution_store.store_candidate(claim, candidate)
    await execution_store.release_execution(claim)
    validating = await execution_store.claim_execution("validator")
    assert validating is not None
    attempt = await validation_store.start_validation(validating)
    assert attempt is not None
    return validating, attempt


@pytest.mark.parametrize(
    "fault", ["missing_checks", "different_command", "different_base", "different_hash"]
)
async def test_completion_requires_full_fixed_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    monkeypatch.setenv("OPEN_SWE_LOCAL_WORKTREES_DIR", str(tmp_path / "worktrees"))
    claim, attempt = await prepare_validation(tmp_path)
    outcome = await IndependentValidator().validate(
        claim.task, attempt.candidate, Path(attempt.record.workspace)
    )
    assert outcome.status == "PASS"
    checks = list(outcome.checks)
    manifest = dict(outcome.manifest)
    if fault == "missing_checks":
        checks.pop()
    elif fault == "different_command":
        checks[-1] = {**checks[-1], "argv": ["echo", "pass"]}
    elif fault == "different_base":
        manifest["base_commit"] = "0" * 40
    else:
        manifest["candidate_sha256"] = "0" * 64
    forged = ValidationOutcome("PASS", None, checks, manifest, outcome.duration_seconds)
    with pytest.raises(ValueError, match="PASS requires complete"):
        await validation_store.finish_validation(claim, attempt, forged)
    async with postgres.session() as session:
        task = await session.get(RepairTask, claim.task.id)
        record = await session.get(ValidationRecord, attempt.record.id)
        assert task is not None and task.status == "VALIDATING"
        assert record is not None and record.status == "RUNNING"
    assert await validation_store.finish_validation(claim, attempt, outcome)
    assert await validation_store.finish_validation(claim, attempt, outcome) is False


async def test_validator_restart_reuses_candidate_and_fences_old_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPEN_SWE_LOCAL_WORKTREES_DIR", str(tmp_path / "worktrees"))
    old, first = await prepare_validation(tmp_path)
    result = await IndependentValidator().validate(
        old.task, first.candidate, Path(first.record.workspace)
    )
    assert await validation_store.checkpoint_checks(old, first, result.checks[:1])
    await execution_store.release_execution(old)
    new = await execution_store.claim_execution("replacement-validator")
    assert new is not None
    second = await validation_store.start_validation(new)
    assert second is not None and second.record.attempt_no == 2
    assert second.candidate.id == first.candidate.id
    assert not await validation_store.checkpoint_checks(old, first, result.checks)
    assert not await validation_store.finish_validation(old, first, result)
    verified = await IndependentValidator().validate(
        new.task, second.candidate, Path(second.record.workspace)
    )
    assert await validation_store.finish_validation(new, second, verified)
    async with postgres.session() as session:
        records = list(
            await session.scalars(select(ValidationRecord).order_by(ValidationRecord.attempt_no))
        )
        assert [record.status for record in records] == ["ERROR", "PASS"]
        assert records[0].error_type == "validation_owner_lost"
        assert len(records[0].checks) == 1
        assert len(list(await session.scalars(select(CandidateArtifact)))) == 1
        task = await session.get(RepairTask, old.task.id)
        assert task is not None and task.status == "COMPLETED"


async def test_repeated_validation_owner_loss_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPEN_SWE_LOCAL_WORKTREES_DIR", str(tmp_path / "worktrees"))
    claim, attempt = await prepare_validation(tmp_path)
    for index in range(2, 4):
        await execution_store.release_execution(claim)
        next_claim = await execution_store.claim_execution(f"replacement-{index}")
        assert next_claim is not None
        claim = next_claim
        next_attempt = await validation_store.start_validation(claim)
        assert next_attempt is not None and next_attempt.record.attempt_no == index
        assert next_attempt.candidate.id == attempt.candidate.id
    await execution_store.release_execution(claim)
    final = await execution_store.claim_execution("fourth-owner")
    assert final is not None
    assert await validation_store.start_validation(final) is None
    async with postgres.session() as session:
        task = await session.get(RepairTask, final.task.id)
        assert task is not None and task.status == "FAILED"
        assert task.failure_reason == "validation_recovery_exhausted"
        records = list(await session.scalars(select(ValidationRecord)))
        assert len(records) == 3 and all(record.status == "ERROR" for record in records)
