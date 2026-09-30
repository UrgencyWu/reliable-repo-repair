"""Prepare three trusted multi-file repair cases with verified reference patches."""

import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from agent.repair.config import FixtureConfig
from agent.repair.process import git, run_command


@dataclass(frozen=True)
class RepositorySample:
    name: str
    files: dict[str, str]
    references: dict[str, str]
    imports: str
    target: str
    regression: str


SAMPLES = (
    RepositorySample(
        "pagination-contract",
        {
            "pagination.py": "def paginate(items, page, size):\n    if page < 1 or size < 1:\n        raise ValueError('positive page and size required')\n    start = page * size\n    return items[start:start + size]\n",
            "service.py": "from pagination import paginate\ndef response(items, page, size):\n    return {'items': paginate(items, page, size), 'has_next': (page + 1) * size < len(items)}\n",
        },
        {
            "pagination.py": "def paginate(items, page, size):\n    if page < 1 or size < 1:\n        raise ValueError('positive page and size required')\n    start = (page - 1) * size\n    return items[start:start + size]\n",
            "service.py": "from pagination import paginate\ndef response(items, page, size):\n    return {'items': paginate(items, page, size), 'has_next': page * size < len(items)}\n",
        },
        "from service import response\nfrom pagination import paginate\n",
        "self.assertEqual(response([1, 2, 3, 4, 5], 2, 2), {'items': [3, 4], 'has_next': True})",
        "self.assertEqual(response([1, 2, 3], 1, 2), {'items': [1, 2], 'has_next': True}); self.assertEqual(response([1, 2, 3], 2, 2), {'items': [3], 'has_next': False}); self.assertEqual(response([], 1, 2), {'items': [], 'has_next': False}); self.assertRaises(ValueError, paginate, [], 0, 2)",
    ),
    RepositorySample(
        "retry-contract",
        {
            "policy.py": "def retryable(status):\n    return status >= 400\n",
            "scheduler.py": "from policy import retryable\ndef next_delay(status, attempt, base=2, cap=20):\n    if not retryable(status):\n        return None\n    return min(base * attempt, cap)\n",
        },
        {
            "policy.py": "def retryable(status):\n    return status == 429 or 500 <= status < 600\n",
            "scheduler.py": "from policy import retryable\ndef next_delay(status, attempt, base=2, cap=20):\n    if not retryable(status):\n        return None\n    return min(base * 2 ** attempt, cap)\n",
        },
        "from scheduler import next_delay\nfrom policy import retryable\n",
        "self.assertEqual((next_delay(429, 1), next_delay(400, 1)), (4, None))",
        "self.assertEqual(next_delay(503, 0), 2); self.assertEqual(next_delay(503, 9), 20); self.assertIsNone(next_delay(200, 1)); self.assertFalse(retryable(404)); self.assertFalse(retryable(600))",
    ),
    RepositorySample(
        "export-contract",
        {
            "normalization.py": "def normalize(value, default):\n    return value or default\n",
            "exporter.py": "from normalization import normalize\ndef export(record, default='N/A'):\n    return [(key, normalize(record[key], default)) for key in sorted(record)]\n",
        },
        {
            "normalization.py": "def normalize(value, default):\n    return default if value is None else value\n",
            "exporter.py": "from normalization import normalize\ndef export(record, default='N/A'):\n    return [(key, normalize(value, default)) for key, value in record.items()]\n",
        },
        "from exporter import export\nfrom normalization import normalize\n",
        "self.assertEqual(export({'b': 0, 'a': None}), [('b', 0), ('a', 'N/A')])",
        "self.assertEqual(export({}), []); self.assertEqual(export({'z': '', 'y': False}), [('z', ''), ('y', False)]); self.assertEqual(normalize(None, 'missing'), 'missing'); self.assertEqual(export({'x': 2}), [('x', 2)])",
    ),
)


async def prepare(root: Path, owner: UUID) -> dict[str, object]:
    root = root.resolve()
    await asyncio.to_thread(root.mkdir, parents=True, exist_ok=False)
    python = str(Path(sys.executable).resolve())
    fixtures: list[FixtureConfig] = []
    manifest: list[dict[str, object]] = []
    for sample in SAMPLES:
        repo = root / sample.name
        await asyncio.to_thread(repo.mkdir)
        for path, contents in sample.files.items():
            await asyncio.to_thread((repo / path).write_text, contents)
        for name, assertion in (("target", sample.target), ("regression", sample.regression)):
            code = (
                "import unittest\n"
                + sample.imports
                + f"class RepairTest(unittest.TestCase):\n    def test_contract(self):\n        {assertion}\n"
            )
            await asyncio.to_thread((repo / f"test_{name}.py").write_text, code)
        await asyncio.to_thread((repo / ".gitignore").write_text, "__pycache__/\n")
        await git(repo, "init", "--initial-branch=main")
        await git(repo, "add", ".")
        await git(
            repo,
            "-c",
            "user.name=Acceptance Fixture",
            "-c",
            "user.email=acceptance@example.invalid",
            "commit",
            "-m",
            sample.name,
        )
        commit = (await git(repo, "rev-parse", "HEAD")).decode().strip()
        target = [python, "-S", "-m", "unittest", "test_target.py"]
        regression = [python, "-S", "-m", "unittest", "test_regression.py"]
        baseline = await run_command(target, repo)
        if (
            baseline.exit_code != 1
            or baseline.truncated
            or b"FAILED (failures=1)" not in baseline.output
        ):
            raise RuntimeError(f"Multi-file baseline is not an assertion failure: {sample.name}")
        for path, contents in sample.references.items():
            await asyncio.to_thread((repo / path).write_text, contents)
        patch = await git(repo, "diff", "--binary", commit)
        await git(repo, "checkout", "--", *sample.files)
        for argv in (["git", "apply", "--check", "-"], ["git", "apply", "-"]):
            applied = await run_command(argv, repo, input_data=patch)
            if applied.exit_code != 0 or applied.truncated:
                raise RuntimeError(f"Multi-file reference cannot be applied: {sample.name}")
        results = [await run_command(argv, repo) for argv in (target, regression)]
        if any(result.exit_code != 0 or result.truncated for result in results):
            raise RuntimeError(f"Multi-file reference does not pass: {sample.name}")
        await git(repo, "checkout", "--", *sample.files)
        if await git(repo, "status", "--porcelain"):
            raise RuntimeError(f"Multi-file sample has a dirty baseline: {sample.name}")
        fixture = FixtureConfig(
            id=f"acceptance-{sample.name}",
            source_path=repo,
            failing_command="python3 -m unittest test_target.py",
            target_argv=target,
            regression_argv=[regression],
            allowed_patch_paths=list(sample.files),
            allowed_users=[owner],
        )
        fixtures.append(fixture)
        manifest.append(
            {
                "sample_id": fixture.id,
                "target_commit": commit,
                "failing_command": fixture.failing_command,
                "baseline_exit_code": baseline.exit_code,
                "reference_check_exit_codes": [result.exit_code for result in results],
                "reference_patch_sha256": hashlib.sha256(patch).hexdigest(),
                "source_file_count": len(sample.files),
            }
        )
    fixture_json = json.dumps([f.model_dump(mode="json") for f in fixtures], indent=2)
    await asyncio.to_thread((root / "fixtures.json").write_text, fixture_json)
    evidence: dict[str, object] = {
        "kind": "synthetic-multi-file-preparation-not-model-acceptance",
        "sample_count": len(manifest),
        "model_calls": 0,
        "fixtures_sha256": hashlib.sha256(fixture_json.encode()).hexdigest(),
        "samples": manifest,
    }
    await asyncio.to_thread((root / "manifest.json").write_text, json.dumps(evidence, indent=2))
    return evidence


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--owner-id", type=UUID, required=True)
    args = parser.parse_args()
    evidence = await prepare(args.output, args.owner_id)
    print(json.dumps({"sample_count": evidence["sample_count"], "model_calls": 0}))


if __name__ == "__main__":
    asyncio.run(main())
