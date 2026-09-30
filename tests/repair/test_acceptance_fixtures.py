from pathlib import Path
from uuid import uuid4

import pytest

from scripts import repair_acceptance_fixtures as corpus


async def test_preparation_preserves_existing_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "manifest.json"
    evidence.write_text("existing evidence")
    with pytest.raises(FileExistsError):
        await corpus.prepare(tmp_path, uuid4())
    assert evidence.read_text() == "existing evidence"


@pytest.mark.parametrize("fault", ["baseline_error", "invalid_reference"])
async def test_preparation_rejects_invalid_experimental_samples(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    sample = corpus.Sample(
        "invalid",
        "raise RuntimeError('import failure')\n"
        if fault == "baseline_error"
        else "def solve(): return 0\n",
        "def solve(): return 1\n" if fault == "baseline_error" else "def solve(): return -1\n",
        "self.assertEqual(solve(), 1)",
        "self.assertEqual(solve(), 1)",
    )
    monkeypatch.setattr(corpus, "SAMPLES", (sample,))
    with pytest.raises(RuntimeError, match="assertion failure|reference fails"):
        await corpus.prepare(tmp_path / "invalid", uuid4())
    assert not (tmp_path / "invalid" / "manifest.json").exists()
