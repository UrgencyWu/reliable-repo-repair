"""Prepare a reproducible Requests issue from verified upstream package blobs."""

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import shutil
import sys
from pathlib import Path
from uuid import UUID

from agent.repair.config import FixtureConfig
from agent.repair.process import git, run_command


async def prepare(source: Path, output: Path, owner: UUID) -> dict[str, object]:
    source = source.resolve()
    output = output.resolve()
    origin: dict[str, object] = json.loads((source / "origin-manifest.json").read_text())
    blobs = origin["blobs"]
    if not isinstance(blobs, dict):
        raise ValueError("Upstream blob manifest is missing")
    for name, expected in blobs.items():
        if not isinstance(name, str) or not isinstance(expected, str):
            raise ValueError("Upstream blob manifest is invalid")
        content = source / name
        if not content.is_file():
            raise ValueError(f"Upstream file is missing: {name}")
        result = await run_command(["git", "hash-object", str(content)], source)
        if result.exit_code != 0 or result.output.decode().strip() != expected:
            raise ValueError(f"Upstream blob differs from release: {name}")
    issue = origin.get("issue")
    release_commit = origin.get("tag_commit")
    if issue == "https://github.com/psf/requests/issues/7432":
        if release_commit != "0b401c76b6e80a4eecf3c690085b2553f6e261ca":
            raise ValueError("Unexpected Requests release commit")
        issue_number = 7432
        allowed_patch_path = "src/requests/models.py"
    elif issue == "https://github.com/psf/requests/issues/6295":
        if release_commit != "111d2b77790bf49943c0dfa09b365371c24aec7e":
            raise ValueError("Unexpected Requests release commit")
        issue_number = 6295
        allowed_patch_path = "src/requests/sessions.py"
    else:
        raise ValueError("Unsupported verified upstream issue")
    await asyncio.to_thread(output.mkdir, parents=True, exist_ok=False)
    repo = output / f"requests-{issue_number}"
    await asyncio.to_thread(
        shutil.copytree,
        source,
        repo,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    await asyncio.to_thread((repo / ".gitignore").write_text, "__pycache__/\n*.pyc\n")
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
        f"Extract Requests package and issue {issue_number} reproducer",
    )
    commit = (await git(repo, "rev-parse", "HEAD")).decode().strip()
    python = sys.executable
    target = [python, "-m", "unittest", "test_target.py"]
    regression = [python, "-m", "unittest", "test_regression.py"]
    baseline = await run_command(target, repo)
    if (
        baseline.exit_code != 1
        or baseline.truncated
        or b"FAILED (failures=1)" not in baseline.output
        or f"Issue #{issue_number}".encode() not in baseline.output
    ):
        raise RuntimeError("Real issue baseline is not the documented assertion failure")
    repair_file = repo / allowed_patch_path
    original_content = await asyncio.to_thread(repair_file.read_bytes)
    if issue_number == 7432:
        fixed_distribution = importlib.metadata.distribution("requests")
        if fixed_distribution.version != "2.34.2":
            raise ValueError("Known-good Requests oracle version is unavailable")
        fixed_models = Path(str(fixed_distribution.locate_file("requests/models.py")))
        fixed_content = await asyncio.to_thread(fixed_models.read_bytes)
        oracle_version = fixed_distribution.version
    else:
        old = b"hist.append(resp)\n            resp.history = hist[1:]"
        new = b"resp.history = hist[:]\n            hist.append(resp)"
        if original_content.count(old) != 1:
            raise ValueError("Known-good redirect-history oracle does not match the release")
        fixed_content = original_content.replace(old, new)
        oracle_version = "v2.34.0 history-order correction"
    await asyncio.to_thread(repair_file.write_bytes, fixed_content)
    try:
        oracle = [await run_command(argv, repo) for argv in (target, regression)]
    finally:
        await asyncio.to_thread(repair_file.write_bytes, original_content)
    if any(check.exit_code != 0 or check.truncated for check in oracle):
        raise RuntimeError("Known-good Requests module fails the frozen issue checks")
    if await git(repo, "status", "--porcelain"):
        raise RuntimeError("Real issue base is not clean after oracle check")
    fixture = FixtureConfig(
        id=f"acceptance-real-requests-{issue_number}",
        source_path=repo,
        failing_command=f"{python} -m unittest test_target.py",
        target_argv=target,
        regression_argv=[regression],
        allowed_patch_paths=[allowed_patch_path],
        allowed_users=[owner],
    )
    fixture_json = json.dumps([fixture.model_dump(mode="json")], indent=2)
    await asyncio.to_thread((output / "fixtures.json").write_text, fixture_json)
    sample: dict[str, object] = {
        "sample_id": fixture.id,
        "target_commit": commit,
        "failing_command": fixture.failing_command,
        "constraints": (repo / "ISSUE.md").read_text(),
        "upstream_issue": origin["issue"],
        "upstream_tag": origin["tag"],
        "upstream_tag_commit": origin["tag_commit"],
        "source_file_count": len(blobs),
        "source_kind": "verified upstream package extraction with local reproducer; not full checkout",
        "baseline_exit_code": baseline.exit_code,
        "oracle_version": oracle_version,
        "oracle_file_sha256": hashlib.sha256(fixed_content).hexdigest(),
        "oracle_check_exit_codes": [check.exit_code for check in oracle],
    }
    evidence: dict[str, object] = {
        "kind": "real-upstream-issue-preparation-not-model-acceptance",
        "sample_count": 1,
        "model_calls": 0,
        "fixtures_sha256": hashlib.sha256(fixture_json.encode()).hexdigest(),
        "samples": [sample],
    }
    await asyncio.to_thread((output / "manifest.json").write_text, json.dumps(evidence, indent=2))
    return evidence


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--owner-id", type=UUID, required=True)
    args = parser.parse_args()
    evidence = await prepare(args.source, args.output, args.owner_id)
    print(json.dumps({"sample_count": evidence["sample_count"], "model_calls": 0}))


if __name__ == "__main__":
    asyncio.run(main())
