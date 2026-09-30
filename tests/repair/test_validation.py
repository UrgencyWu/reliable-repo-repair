import hashlib
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid7

import pytest

from agent.repair.models import CandidateArtifact, CheckPayload, RepairTask, ValidationPlan
from agent.repair.process import git, run_command
from agent.repair.validation import IndependentValidator, ValidationLeaseLost

pytestmark = pytest.mark.asyncio


async def fixture_candidate(tmp_path: Path) -> tuple[RepairTask, CandidateArtifact]:
    source = tmp_path / "source"
    source.mkdir()
    (source / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (source / ".gitignore").write_text("__pycache__/\n")
    await git(source, "init", "--initial-branch=main")
    await git(source, "add", ".")
    await git(
        source,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "broken",
    )
    base = (await git(source, "rev-parse", "HEAD")).decode().strip()
    (source / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    patch = await git(source, "diff", "--binary", base)
    plan: ValidationPlan = {
        "source_path": str(source),
        "target_argv": [sys.executable, "-c", "from calc import add; assert add(2, 3) == 5"],
        "regression_argv": [
            [
                sys.executable,
                "-c",
                "from calc import add; assert add(-2, 5) == 3; assert add(0, 0) == 0",
            ]
        ],
        "allowed_patch_paths": ["calc.py"],
    }
    task = RepairTask(
        owner_id=uuid7(),
        fixture_id="arithmetic",
        target_commit=base,
        failing_command="fixed assertion",
        constraints="",
        idempotency_key="test",
        input_sha256="0" * 64,
        validation_plan=plan,
        deadline_at=datetime.now(UTC) + timedelta(seconds=60),
    )
    candidate = CandidateArtifact(
        repair_run_id=uuid7(),
        base_commit=base,
        sha256=hashlib.sha256(patch).hexdigest(),
        patch=patch,
        files_changed=["calc.py"],
    )
    return task, candidate


async def test_clean_validation_ignores_dirty_source_and_keeps_agent_files(tmp_path: Path) -> None:
    task, candidate = await fixture_candidate(tmp_path)
    agent_file = Path(task.validation_plan["source_path"]) / "calc.py"
    agent_file.write_text("not even valid Python\n")
    workspace = tmp_path / "validation"
    result = await IndependentValidator().validate(task, candidate, workspace)
    assert result.status == "PASS"
    assert [check["name"] for check in result.checks] == [
        "BASELINE",
        "PATCH_CHECK",
        "PATCH_APPLY",
        "TARGET",
        "REGRESSION_1",
    ]
    assert [check["exit_code"] for check in result.checks] == [1, 0, 0, 0, 0]
    assert result.manifest["base_commit"] == task.target_commit
    assert not workspace.exists()
    assert agent_file.read_text() == "not even valid Python\n"


async def test_stdlib_validation_does_not_load_agent_installed_packages(tmp_path: Path) -> None:
    task, candidate = await fixture_candidate(tmp_path)
    environment = tmp_path / "agent_environment"
    created = await run_command(
        [sys.executable, "-m", "venv", "--without-pip", str(environment)], tmp_path
    )
    assert created.exit_code == 0
    agent_python = str(environment / "bin/python")
    site_result = await run_command(
        [agent_python, "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        tmp_path,
    )
    assert site_result.exit_code == 0
    packages = Path(site_result.output.decode().strip())
    (packages / "agent_only_dependency.py").write_text("VALUE = 'agent environment'\n")
    agent_check = await run_command(
        [agent_python, "-c", "import agent_only_dependency; print(agent_only_dependency.VALUE)"],
        tmp_path,
    )
    assert agent_check.exit_code == 0 and b"agent environment" in agent_check.output
    task.validation_plan["target_argv"] = [
        str(Path(sys.executable).resolve()),
        "-S",
        "-c",
        "import importlib.util; from calc import add; "
        "assert importlib.util.find_spec('agent_only_dependency') is None; assert add(2, 3) == 5",
    ]
    task.validation_plan["regression_argv"] = []
    result = await IndependentValidator().validate(task, candidate, tmp_path / "validation")
    assert result.status == "PASS"
    assert [check["exit_code"] for check in result.checks] == [1, 0, 0, 0]


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("base", "candidate_base_mismatch"),
        ("hash", "candidate_hash_mismatch"),
        ("apply", "patch_apply_failed"),
        ("files", "candidate_file_policy"),
        ("baseline", "failure_not_reproduced"),
        ("target", "target_test_failed"),
        ("regression", "regression_test_failed"),
    ],
)
async def test_invalid_candidates_never_pass(tmp_path: Path, fault: str, reason: str) -> None:
    task, candidate = await fixture_candidate(tmp_path)
    if fault == "base":
        candidate.base_commit = "0" * 40
    elif fault == "hash":
        candidate.sha256 = "0" * 64
    elif fault == "apply":
        candidate.patch = b"invalid diff\n"
        candidate.sha256 = hashlib.sha256(candidate.patch).hexdigest()
    elif fault == "files":
        candidate.files_changed = ["different.py"]
    elif fault == "baseline":
        task.validation_plan["target_argv"] = [sys.executable, "-c", "pass"]
    elif fault == "target":
        task.validation_plan["target_argv"] = [
            sys.executable,
            "-c",
            "raise AssertionError('still broken')",
        ]
    else:
        task.validation_plan["regression_argv"] = [
            [sys.executable, "-c", "raise AssertionError('regression')"]
        ]
    result = await IndependentValidator().validate(task, candidate, tmp_path / "validation")
    assert result.status == "FAIL"
    assert result.error_type == reason


async def test_timeout_preserves_partial_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task, candidate = await fixture_candidate(tmp_path)
    monkeypatch.setenv("REPAIR_VALIDATION_TIMEOUT_SECONDS", "0.1")
    task.validation_plan["target_argv"] = [
        sys.executable,
        "-u",
        "-c",
        "import time; print('before timeout'); time.sleep(10)",
    ]
    result = await IndependentValidator().validate(task, candidate, tmp_path / "validation")
    assert result.status == "ERROR" and result.error_type == "TimeoutError"
    assert result.checks[0]["timed_out"]
    assert "before timeout" in result.checks[0]["output"]
    assert not (tmp_path / "validation").exists()


async def test_existing_directory_is_never_removed(tmp_path: Path) -> None:
    task, candidate = await fixture_candidate(tmp_path)
    workspace = tmp_path / "validation"
    workspace.mkdir()
    marker = workspace / "keep"
    marker.write_text("owned elsewhere")
    result = await IndependentValidator().validate(task, candidate, workspace)
    assert result.status == "ERROR" and result.error_type == "ValueError"
    assert marker.read_text() == "owned elsewhere"


async def test_lost_lease_stops_validation_before_applying_patch(tmp_path: Path) -> None:
    task, candidate = await fixture_candidate(tmp_path)

    async def reject_checkpoint(checks: list[CheckPayload]) -> bool:
        assert len(checks) == 1
        return False

    with pytest.raises(ValidationLeaseLost):
        await IndependentValidator().validate(
            task, candidate, tmp_path / "validation", reject_checkpoint
        )
    assert not (tmp_path / "validation").exists()


async def test_missing_executable_is_infrastructure_error(tmp_path: Path) -> None:
    task, candidate = await fixture_candidate(tmp_path)
    task.validation_plan["target_argv"] = ["/missing-repair-test-command"]
    result = await IndependentValidator().validate(task, candidate, tmp_path / "validation")
    assert result.status == "ERROR" and result.error_type == "FileNotFoundError"
    assert not (tmp_path / "validation").exists()
