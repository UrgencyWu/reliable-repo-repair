"""Prepare verified synthetic repair samples without model calls or task dispatch."""

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
class Sample:
    name: str
    broken: str
    reference: str
    target: str
    regression: str


SAMPLES = (
    Sample(
        "addition",
        "def solve(a, b):\n    return a - b\n",
        "def solve(a, b):\n    return a + b\n",
        "self.assertEqual(solve(2, 3), 5)",
        "self.assertEqual(solve(-2, 5), 3); self.assertEqual(solve(0, 0), 0)",
    ),
    Sample(
        "clamp",
        "def solve(value, low, high):\n    return min(value, low)\n",
        "def solve(value, low, high):\n    return min(max(value, low), high)\n",
        "self.assertEqual(solve(5, 0, 3), 3)",
        "self.assertEqual(solve(-1, 0, 3), 0); self.assertEqual(solve(2, 0, 3), 2)",
    ),
    Sample(
        "mean",
        "def solve(values):\n    return sum(values) // len(values)\n",
        "def solve(values):\n    return sum(values) / len(values)\n",
        "self.assertEqual(solve([1, 2]), 1.5)",
        "self.assertEqual(solve([2, 4]), 3); self.assertEqual(solve([-1, 0]), -0.5)",
    ),
    Sample(
        "median",
        "def solve(values):\n    values = sorted(values)\n    return values[len(values) // 2]\n",
        "def solve(values):\n    values = sorted(values)\n    middle = len(values) // 2\n    return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2\n",
        "self.assertEqual(solve([1, 3]), 2)",
        "self.assertEqual(solve([3, 1, 2]), 2); self.assertEqual(solve([8]), 8)",
    ),
    Sample(
        "stable-unique",
        "def solve(values):\n    return sorted(set(values))\n",
        "def solve(values):\n    return list(dict.fromkeys(values))\n",
        "self.assertEqual(solve(['b', 'a', 'b']), ['b', 'a'])",
        "self.assertEqual(solve([]), []); self.assertEqual(solve(['x', 'x']), ['x'])",
    ),
    Sample(
        "slug",
        "def solve(value):\n    return value.lower().replace(' ', '-')\n",
        "def solve(value):\n    return '-'.join(value.lower().split())\n",
        "self.assertEqual(solve(' Hello  World '), 'hello-world')",
        "self.assertEqual(solve(''), ''); self.assertEqual(solve('Already'), 'already')",
    ),
    Sample(
        "chunks",
        "def solve(values, size):\n    return [values[i:i + size] for i in range(1, len(values), size)]\n",
        "def solve(values, size):\n    return [values[i:i + size] for i in range(0, len(values), size)]\n",
        "self.assertEqual(solve([1, 2, 3], 2), [[1, 2], [3]])",
        "self.assertEqual(solve([], 2), []); self.assertEqual(solve([1], 3), [[1]])",
    ),
    Sample(
        "inclusive-range",
        "def solve(start, stop):\n    return list(range(start, stop))\n",
        "def solve(start, stop):\n    return list(range(start, stop + 1))\n",
        "self.assertEqual(solve(2, 4), [2, 3, 4])",
        "self.assertEqual(solve(-1, 0), [-1, 0]); self.assertEqual(solve(2, 2), [2])",
    ),
    Sample(
        "none-default",
        "def solve(value, default):\n    return value or default\n",
        "def solve(value, default):\n    return default if value is None else value\n",
        "self.assertEqual(solve(0, 7), 0)",
        "self.assertEqual(solve(None, 7), 7); self.assertEqual(solve('', 'x'), '')",
    ),
    Sample(
        "capped-backoff",
        "def solve(base, attempt, cap):\n    return min(base * attempt, cap)\n",
        "def solve(base, attempt, cap):\n    return min(base * 2 ** attempt, cap)\n",
        "self.assertEqual(solve(2, 3, 100), 16)",
        "self.assertEqual(solve(2, 10, 20), 20); self.assertEqual(solve(2, 0, 20), 2)",
    ),
)


async def prepare(root: Path, owner: UUID) -> dict[str, object]:
    root = root.resolve()
    # Exclusive creation prevents an acceptance preparation from replacing existing evidence.
    await asyncio.to_thread(root.mkdir, parents=True, exist_ok=False)
    python = str(Path(sys.executable).resolve())
    fixtures: list[FixtureConfig] = []
    manifest: list[dict[str, object]] = []
    for sample in SAMPLES:
        repo = root / sample.name
        await asyncio.to_thread(repo.mkdir)
        source = repo / "subject.py"
        await asyncio.to_thread(source.write_text, sample.broken)
        for name, assertion in (("target", sample.target), ("regression", sample.regression)):
            code = (
                "import unittest\nfrom subject import solve\n"
                f"class RepairTest(unittest.TestCase):\n    def test_contract(self):\n        {assertion}\n"
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
            raise RuntimeError(f"Sample does not reproduce an assertion failure: {sample.name}")
        await asyncio.to_thread(source.write_text, sample.reference)
        patch = await git(repo, "diff", "--binary", commit)
        await git(repo, "checkout", "--", "subject.py")
        for argv in (["git", "apply", "--check", "-"], ["git", "apply", "-"]):
            applied = await run_command(argv, repo, input_data=patch)
            if applied.exit_code != 0 or applied.truncated:
                raise RuntimeError(f"Sample reference patch cannot be applied: {sample.name}")
        results = [await run_command(argv, repo) for argv in (target, regression)]
        if any(result.exit_code != 0 or result.truncated for result in results):
            raise RuntimeError(f"Sample reference fails validation: {sample.name}")
        await git(repo, "checkout", "--", "subject.py")
        if await git(repo, "status", "--porcelain"):
            raise RuntimeError(f"Sample is not left at its clean failing base: {sample.name}")
        fixture = FixtureConfig(
            id=f"acceptance-{sample.name}",
            source_path=repo,
            failing_command="python3 -m unittest test_target.py",
            target_argv=target,
            regression_argv=[regression],
            allowed_patch_paths=["subject.py"],
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
            }
        )
    fixture_json = json.dumps([fixture.model_dump(mode="json") for fixture in fixtures], indent=2)
    await asyncio.to_thread((root / "fixtures.json").write_text, fixture_json)
    evidence: dict[str, object] = {
        "kind": "synthetic-fixture-preparation-not-model-acceptance",
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
