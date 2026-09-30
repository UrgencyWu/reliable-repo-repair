"""Audit saved candidates against supplementary synthetic contracts without model calls."""

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from agent.repair.config import FixtureConfig
from agent.repair.process import git, run_command
from scripts.repair_acceptance_fixtures import SAMPLES as SINGLE_SAMPLES
from scripts.repair_acceptance_multifile_fixtures import SAMPLES as MULTI_SAMPLES
from scripts.repair_real_model_acceptance import read, required_string, save

CHECKS = {
    "addition": "for a in range(-4, 5):\n    for b in range(-4, 5):\n        self.assertEqual(solve(a, b), a + b)",
    "clamp": "for value in range(-10, 11):\n    self.assertEqual(solve(value, -2, 4), min(max(value, -2), 4))",
    "mean": "for values in ([1, 2, 4], [-3, 1, 7], [0], [1.5, 2.5]):\n    self.assertAlmostEqual(solve(values), sum(values) / len(values))",
    "median": "for values, expected in (([8, 1, 4, 2], 3), ([1, 1, 9, 9], 5), ([5, 2, 1, 4, 3], 3)):\n    self.assertEqual(solve(values), expected)",
    "stable-unique": "self.assertEqual(solve([3, 1, 3, 2, 1]), [3, 1, 2]); self.assertEqual(solve([False, False, True]), [False, True])",
    "slug": "self.assertEqual(solve(' A\\tB\\nC '), 'a-b-c'); self.assertEqual(solve('  '), '')",
    "chunks": "for size in range(1, 10):\n    values = list(range(7))\n    self.assertEqual(solve(values, size), [values[i:i + size] for i in range(0, 7, size)])",
    "inclusive-range": "for start in range(-3, 4):\n    for stop in range(-3, 4):\n        self.assertEqual(solve(start, stop), list(range(start, stop + 1)))",
    "none-default": "for value in (False, [], {}, 0, '', None):\n    self.assertEqual(solve(value, 'default'), 'default' if value is None else value)",
    "capped-backoff": "for base in (1, 3, 5):\n    for attempt in range(5):\n        for cap in (4, 100):\n            with self.subTest(base=base, attempt=attempt, cap=cap):\n                self.assertEqual(solve(base, attempt, cap), min(base * 2 ** attempt, cap))",
    "pagination-contract": "for length in range(10):\n    for page in range(1, 6):\n        for size in range(1, 5):\n            values = list(range(length))\n            self.assertEqual(response(values, page, size), {'items': values[(page - 1) * size:page * size], 'has_next': page * size < length})\nself.assertRaises(ValueError, paginate, [], 1, 0)",
    "retry-contract": "for status in (200, 400, 404, 429, 500, 501, 502, 503, 504, 599, 600):\n    with self.subTest(status=status):\n        self.assertEqual(retryable(status), status == 429 or 500 <= status < 600)\nfor base in (2, 3, 5):\n    for attempt in range(5):\n        with self.subTest(base=base, attempt=attempt):\n            self.assertEqual(next_delay(503, attempt, base, 100), min(base * 2 ** attempt, 100))",
    "export-contract": "for record in ({'z': [], 'b': None, 'a': 0}, {'second': False, 'first': ''}, {}):\n    self.assertEqual(export(record, 'missing'), [(key, 'missing' if value is None else value) for key, value in record.items()])",
}


async def run_checks(
    phase: str, fixture: FixtureConfig, supplemental: list[str], repo: Path, folder: Path
) -> list[int]:
    codes: list[int] = []
    for index, argv in enumerate([fixture.target_argv, *fixture.regression_argv, supplemental]):
        command = await run_command(argv, repo)
        if command.truncated:
            raise RuntimeError("Audit command output was truncated")
        await asyncio.to_thread((folder / f"{phase}-{index}.log").write_bytes, command.output)
        codes.append(command.exit_code)
    return codes


async def audit(fixtures_path: Path, evidence: Path, output: Path) -> None:
    fixtures = {
        fixture.id: fixture
        for fixture in (
            FixtureConfig.model_validate(item) for item in json.loads(fixtures_path.read_text())
        )
    }
    await asyncio.to_thread(output.mkdir, parents=True, exist_ok=False)
    references = {sample.name: {"subject.py": sample.reference} for sample in SINGLE_SAMPLES}
    imports = {sample.name: "from subject import solve\n" for sample in SINGLE_SAMPLES}
    references.update({sample.name: sample.references for sample in MULTI_SAMPLES})
    imports.update({sample.name: sample.imports for sample in MULTI_SAMPLES})
    plan = {
        "kind": "post-hoc-exploratory-contract-audit-not-blind-heldout-evaluation",
        "created_at": datetime.now(UTC).isoformat(),
        "fixtures_sha256": hashlib.sha256(fixtures_path.read_bytes()).hexdigest(),
        "checks": CHECKS,
        "reference_source_sha256": {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                Path(__file__).with_name("repair_acceptance_fixtures.py"),
                Path(__file__).with_name("repair_acceptance_multifile_fixtures.py"),
            )
        },
    }
    save(output / "plan.json", plan)
    rows: list[dict[str, object]] = []
    for name, assertions in CHECKS.items():
        sample_id = f"acceptance-{name}"
        result = read(evidence / sample_id / "result.json")
        patch = (evidence / sample_id / "candidate.patch").read_bytes()
        fixture = fixtures[sample_id]
        folder = output / sample_id
        await asyncio.to_thread(folder.mkdir)
        repo = folder / "checkout"
        await git(folder, "clone", "--no-local", str(fixture.source_path), str(repo))
        await git(repo, "checkout", "--detach", required_string(result["target_commit"]))
        code = (
            "import unittest\n"
            + imports[name]
            + "class ContractAudit(unittest.TestCase):\n    def test_contract(self):\n"
        )
        code += "\n".join("        " + line for line in assertions.splitlines()) + "\n"
        await asyncio.to_thread((repo / "test_supplementary.py").write_text, code)
        supplemental = [sys.executable, "-S", "-m", "unittest", "test_supplementary.py"]

        baseline = await run_checks("baseline", fixture, supplemental, repo, folder)
        if baseline[0] != 1:
            raise RuntimeError(f"Original failure not reproduced: {sample_id}")
        for path, contents in references[name].items():
            await asyncio.to_thread((repo / path).write_text, contents)
        reference = await run_checks("reference", fixture, supplemental, repo, folder)
        if any(reference):
            raise RuntimeError(f"Supplementary oracle disagrees with reference: {sample_id}")
        await git(repo, "checkout", "--", *references[name])
        applied = await run_command(["git", "apply", "-"], repo, input_data=patch)
        if applied.exit_code != 0 or applied.truncated:
            raise RuntimeError(f"Saved candidate cannot be applied: {sample_id}")
        candidate = await run_checks("candidate", fixture, supplemental, repo, folder)
        row: dict[str, object] = {
            "sample_id": sample_id,
            "target_commit": result["target_commit"],
            "task_id": result["task_id"],
            "patch_sha256": hashlib.sha256(patch).hexdigest(),
            "baseline_exit_codes": baseline,
            "reference_exit_codes": reference,
            "candidate_exit_codes": candidate,
            "original_checks_pass": not any(candidate[:-1]),
            "supplementary_pass": candidate[-1] == 0,
        }
        save(folder / "result.json", row)
        rows.append(row)
        print(json.dumps(row), flush=True)
    save(
        output / "summary.json",
        {
            "kind": plan["kind"],
            "samples": rows,
            "sample_count": len(rows),
            "supplementary_pass_count": sum(row["supplementary_pass"] is True for row in rows),
        },
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    await audit(args.fixtures, args.evidence, args.output)


if __name__ == "__main__":
    asyncio.run(main())
