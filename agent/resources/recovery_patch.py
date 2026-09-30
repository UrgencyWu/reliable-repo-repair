"""Runs inside a thread's sandbox to emit a patch of its uncommitted work.

Delivered as a heredoc by ``agent.threads.diffs``; ``__PAYLOAD__`` is
substituted with a base64 JSON blob before execution. Prints a single JSON line.
"""

import base64
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

PAYLOAD = json.loads(base64.b64decode("__PAYLOAD__").decode())
WORKSPACE_FALLBACK = Path("/workspace")


def git(repo, args, check=True):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if check and result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(detail or "git " + " ".join(args) + " failed")
    return result


def search_roots():
    roots = [Path.cwd().resolve(), WORKSPACE_FALLBACK]
    seen = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        if root.exists():
            yield root


def repo_paths():
    repo_name = PAYLOAD.get("repo_name")
    for root in search_roots():
        if isinstance(repo_name, str) and repo_name:
            yield root / Path(repo_name).name
        yield root
        for child in sorted(root.iterdir()):
            if child.is_dir():
                yield child


def find_repo() -> Path:
    if "repo_path" in PAYLOAD or "base_commit" in PAYLOAD:
        requested = PAYLOAD.get("repo_path")
        if not isinstance(requested, str) or not Path(requested).is_absolute():
            raise ValueError("repair patch requires an absolute repo_path")
        repo = Path(requested).resolve()
        result = git(repo, ["rev-parse", "--show-toplevel"])
        root = Path(result.stdout.decode().strip()).resolve()
        if root != repo:
            raise ValueError("repo_path must name the repository root")
        return root
    seen = set()
    for path in repo_paths():
        if path in seen:
            continue
        seen.add(path)
        if not (path / ".git").exists():
            continue
        result = git(path, ["rev-parse", "--show-toplevel"], check=False)
        if result.returncode == 0:
            root = Path(result.stdout.decode(errors="replace").strip())
            if root.exists():
                return root
    raise RuntimeError("no git repository found in sandbox workspace")


def patch_base(repo: Path) -> str:
    if "repo_path" not in PAYLOAD and "base_commit" not in PAYLOAD:
        return merge_base(repo)
    requested = PAYLOAD.get("base_commit")
    if not isinstance(requested, str) or not re.fullmatch(r"[0-9a-f]{40}", requested):
        raise ValueError("repair patch requires a complete base_commit SHA")
    resolved = commit_for(repo, requested)
    if resolved != requested:
        raise ValueError("base_commit is not an available commit in the repository")
    return resolved


def safe_ref(value):
    if not isinstance(value, str) or not value or len(value) > 200:
        return None
    if value.startswith("-") or "\x00" in value or "\n" in value or "\r" in value:
        return None
    return value


def commit_for(repo, ref):
    result = git(repo, ["rev-parse", "--verify", ref + "^{commit}"], check=False)
    if result.returncode == 0:
        return result.stdout.decode(errors="replace").strip()
    return None


def merge_base(repo):
    base_branch = safe_ref(PAYLOAD.get("base_branch")) or "main"
    refs = [
        "origin/" + base_branch,
        base_branch,
        "origin/main",
        "main",
        "origin/master",
        "master",
        "HEAD~1",
    ]
    for ref in refs:
        commit = commit_for(repo, ref)
        if not commit:
            continue
        result = git(repo, ["merge-base", "HEAD", commit], check=False)
        if result.returncode == 0:
            return result.stdout.decode(errors="replace").strip()
        return commit
    return (
        git(repo, ["hash-object", "-t", "tree", "/dev/null"])
        .stdout.decode(errors="replace")
        .strip()
    )


def write_patch(repo, base):
    patch_path = Path("/tmp") / ((PAYLOAD.get("thread_key") or "open-swe-recovery") + ".patch")
    with patch_path.open("wb") as patch_file:
        tracked = git(repo, ["diff", "--binary", "--full-index", base, "--", "."]).stdout
        patch_file.write(tracked)
        untracked = git(repo, ["ls-files", "--others", "--exclude-standard", "-z"]).stdout
        for raw_path in [p for p in untracked.split(b"\0") if p]:
            rel_path = raw_path.decode("utf-8", errors="surrogateescape")
            full_path = repo / rel_path
            if not full_path.is_file():
                continue
            result = git(
                repo,
                ["diff", "--no-index", "--binary", "--full-index", "--", "/dev/null", rel_path],
                check=False,
            )
            if result.returncode not in {0, 1}:
                detail = result.stderr.decode(errors="replace").strip()
                raise RuntimeError(detail or "failed to diff untracked file " + rel_path)
            if result.stdout:
                if patch_file.tell() and not result.stdout.startswith(b"\n"):
                    patch_file.write(b"\n")
                patch_file.write(result.stdout)
    return patch_path


try:
    repo = find_repo()
    base = patch_base(repo)
    patch_path = write_patch(repo, base)
    result = {"ok": True, "path": str(patch_path), "size": patch_path.stat().st_size}
    if "base_commit" in PAYLOAD:
        result.update(
            base_commit=base,
            sha256=hashlib.sha256(patch_path.read_bytes()).hexdigest(),
        )
    print(json.dumps(result))
except Exception as exc:
    print(json.dumps({"ok": False, "error": str(exc)}))
    sys.exit(1)
