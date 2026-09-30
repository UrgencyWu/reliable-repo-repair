import json
from pathlib import Path
from uuid import uuid4

import pytest

from agent.repair.process import git
from scripts import repair_acceptance_audit as auditor
from scripts import repair_acceptance_fixtures as corpus
from scripts.repair_real_model_acceptance import save


@pytest.mark.parametrize("correct", [False, True])
async def test_audit_distinguishes_test_overfit_from_reference_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, correct: bool
) -> None:
    sample = next(sample for sample in corpus.SAMPLES if sample.name == "capped-backoff")
    monkeypatch.setattr(corpus, "SAMPLES", (sample,))
    monkeypatch.setattr(auditor, "CHECKS", {sample.name: auditor.CHECKS[sample.name]})
    prepared = await corpus.prepare(tmp_path / "fixtures", uuid4())
    samples = prepared["samples"]
    assert isinstance(samples, list)
    base = samples[0]["target_commit"]
    repo = tmp_path / "fixtures" / sample.name
    source = repo / "subject.py"
    source.write_text(
        sample.reference
        if correct
        else "def solve(base, attempt, cap):\n    return min(base ** (attempt + 1), cap)\n"
    )
    patch = await git(repo, "diff", "--binary", base)
    await git(repo, "checkout", "--", "subject.py")
    evidence = tmp_path / "evidence" / "acceptance-capped-backoff"
    evidence.mkdir(parents=True)
    save(evidence / "result.json", {"target_commit": base, "task_id": "saved-task"})
    (evidence / "candidate.patch").write_bytes(patch)
    await auditor.audit(
        tmp_path / "fixtures" / "fixtures.json", evidence.parent, tmp_path / "audit"
    )
    result = json.loads((tmp_path / "audit" / evidence.name / "result.json").read_text())
    assert result["original_checks_pass"] is True
    assert result["supplementary_pass"] is correct
    assert result["reference_exit_codes"] == [0, 0, 0]
    assert source.read_text() == sample.broken
    assert (evidence / "candidate.patch").read_bytes() == patch
