"""Recheck saved Requests candidates against exploratory offline edge cases."""

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import shutil
import sys
from pathlib import Path

from agent.repair.process import git, run_command
from scripts.repair_real_model_acceptance import read, save

EXTRA_TESTS = {
    7432: """import unittest
from io import BytesIO
from test_target import DelegatingStream, RedirectAdapter
import requests

class Audit(unittest.TestCase):
    def test_delegating_stream_offset_and_308(self):
        class PermanentAdapter(RedirectAdapter):
            def send(self, request, **kwargs):
                response = super().send(request, **kwargs)
                if len(self.bodies) == 1:
                    response.status_code = 308
                return response
        payload = b"prefix-and-payload"
        source = BytesIO(payload)
        source.seek(7)
        session = requests.Session()
        adapter = PermanentAdapter()
        session.mount("https://", adapter)
        response = session.put("https://example.invalid/upload", data=DelegatingStream(source), timeout=2)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(adapter.bodies, [payload[7:], payload[7:]])
""",
    6295: """import unittest
from test_target import RedirectAdapter
import requests

class Audit(unittest.TestCase):
    def test_four_redirect_history_is_ordered_and_acyclic(self):
        session = requests.Session()
        adapter = RedirectAdapter(redirects=4)
        session.mount("https://", adapter)
        response = session.get("https://example.invalid/start", timeout=2)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(adapter.calls, 5)
        self.assertEqual(len(response.history), 4)
        for index, earlier in enumerate(response.history):
            self.assertEqual(earlier.history, response.history[:index])
            self.assertTrue(all(child is not earlier for child in earlier.history))
""",
}


async def run_checks(repo: Path, output: Path, phase: str) -> list[int]:
    codes: list[int] = []
    for index, test in enumerate(("test_target.py", "test_regression.py", "test_supplementary.py")):
        command = await run_command([sys.executable, "-m", "unittest", test], repo, timeout=30)
        if command.truncated:
            raise RuntimeError("Audit test output was truncated")
        await asyncio.to_thread((output / f"{phase}-{index}.log").write_bytes, command.output)
        codes.append(command.exit_code)
    return codes


async def audit(source: Path, evidence: Path, output: Path) -> None:
    await asyncio.to_thread(output.mkdir, parents=True, exist_ok=False)
    plan = {
        "kind": "post-hoc-exploratory-real-issue-audit-not-blind-heldout",
        "checks": EXTRA_TESTS,
    }
    save(output / "plan.json", plan)
    rows: list[dict[str, object]] = []
    fixed_distribution = importlib.metadata.distribution("requests")
    if fixed_distribution.version != "2.34.2":
        raise ValueError("Known-good Requests oracle version is unavailable")
    for issue_number in (7432, 6295):
        sample_id = f"acceptance-real-requests-{issue_number}"
        source_repo = source / f"requests-{issue_number}"
        candidate_dir = evidence / sample_id
        result = read(candidate_dir / "result.json")
        patch = await asyncio.to_thread((candidate_dir / "candidate.patch").read_bytes)
        task = output / sample_id
        await asyncio.to_thread(task.mkdir)
        repo = task / "repo"
        await asyncio.to_thread(
            shutil.copytree,
            source_repo,
            repo,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        await git(repo, "init", "--quiet")
        await asyncio.to_thread(
            (repo / "test_supplementary.py").write_text, EXTRA_TESTS[issue_number]
        )
        path = repo / f"src/requests/{'models' if issue_number == 7432 else 'sessions'}.py"
        original = await asyncio.to_thread(path.read_bytes)
        baseline = await run_checks(repo, task, "baseline")
        if baseline[0] != 1:
            raise RuntimeError(f"Upstream issue baseline not reproduced: {sample_id}")
        if issue_number == 7432:
            reference = await asyncio.to_thread(
                Path(str(fixed_distribution.locate_file("requests/models.py"))).read_bytes
            )
        else:
            old = b"hist.append(resp)\n            resp.history = hist[1:]"
            new = b"resp.history = hist[:]\n            hist.append(resp)"
            if original.count(old) != 1:
                raise ValueError("History oracle does not match the release")
            reference = original.replace(old, new)
        await asyncio.to_thread(path.write_bytes, reference)
        oracle = await run_checks(repo, task, "oracle")
        if any(oracle):
            raise RuntimeError(f"Supplementary oracle is invalid: {sample_id}")
        await asyncio.to_thread(path.write_bytes, original)
        checked = await run_command(["git", "apply", "--check", "-"], repo, input_data=patch)
        if checked.exit_code != 0 or checked.truncated:
            raise RuntimeError(f"Candidate patch cannot be applied: {sample_id}")
        applied = await run_command(["git", "apply", "-"], repo, input_data=patch)
        if applied.exit_code != 0 or applied.truncated:
            raise RuntimeError(f"Candidate patch application failed: {sample_id}")
        if await asyncio.to_thread(path.read_bytes) == original:
            raise RuntimeError(f"Candidate patch did not change the expected file: {sample_id}")
        candidate = await run_checks(repo, task, "candidate")
        row: dict[str, object] = {
            "sample_id": sample_id,
            "task_id": result["task_id"],
            "target_commit": result["target_commit"],
            "patch_sha256": hashlib.sha256(patch).hexdigest(),
            "baseline_exit_codes": baseline,
            "oracle_exit_codes": oracle,
            "candidate_exit_codes": candidate,
            "supplementary_pass": not any(candidate),
        }
        save(task / "result.json", row)
        rows.append(row)
        print(json.dumps(row), flush=True)
    save(output / "summary.json", {"kind": plan["kind"], "samples": rows})


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    await audit(args.source, args.evidence, args.output)


if __name__ == "__main__":
    asyncio.run(main())
