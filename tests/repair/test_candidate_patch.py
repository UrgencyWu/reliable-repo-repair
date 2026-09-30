"""Replay the upstream exporter output in a clean, exact-base checkout."""

import asyncio
import base64
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

EXPORT_SCRIPT = Path(__file__).resolve().parents[2] / "agent/resources/recovery_patch.py"


class CandidatePatchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="repair-patch-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.repo = self.root / "agent repo"
        self.repo.mkdir()
        self.environment = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "Repair Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Repair Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        }
        await self.git(self.repo, "init", "--initial-branch=main")
        (self.repo / "base.txt").write_text("base\n")
        (self.repo / "staged.txt").write_text("before\n")
        (self.repo / "deleted.txt").write_text("delete me\n")
        await self.git(self.repo, "add", ".")
        await self.git(self.repo, "commit", "-m", "base")
        self.base = (await self.git(self.repo, "rev-parse", "HEAD")).decode().strip()

    async def git(self, repo: Path, *arguments: str, input_data: bytes | None = None) -> bytes:
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(repo),
            *arguments,
            stdin=asyncio.subprocess.PIPE if input_data is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self.environment,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(input_data), timeout=20)
        self.assertEqual(process.returncode, 0, stderr.decode(errors="replace"))
        return stdout

    async def export(self, payload: dict[str, str]) -> tuple[int, dict[str, object], bytes]:
        payload = {**payload, "thread_key": f"repair-test-{uuid4().hex}"}
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        script = EXPORT_SCRIPT.read_text().replace("__PAYLOAD__", encoded)
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-",
            cwd=self.root,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self.environment,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(script.encode()), timeout=20)
        result: dict[str, object] = json.loads(stdout)
        self.assertIsInstance(result, dict, stderr.decode(errors="replace"))
        output_path = result.get("path")
        patch = b""
        if isinstance(output_path, str):
            path = Path(output_path)
            self.addCleanup(path.unlink, missing_ok=True)
            patch = path.read_bytes()
        return process.returncode or 0, result, patch

    async def clean_checkout(self) -> Path:
        validator = self.root / f"validator-{uuid4().hex}"
        await self.git(self.root, "clone", "--no-hardlinks", str(self.repo), str(validator))
        await self.git(validator, "checkout", "--detach", self.base)
        self.assertEqual(await self.git(validator, "status", "--porcelain"), b"")
        return validator

    async def test_exact_base_replays_committed_staged_unstaged_new_and_binary_changes(
        self,
    ) -> None:
        (self.repo / "base.txt").write_text("committed change\n")
        await self.git(self.repo, "add", "base.txt")
        await self.git(self.repo, "commit", "-m", "agent commit")
        (self.repo / "staged.txt").write_text("staged\n")
        await self.git(self.repo, "add", "staged.txt")
        (self.repo / "staged.txt").write_text("staged plus unstaged\n")
        (self.repo / "deleted.txt").unlink()
        (self.repo / "new file.txt").write_text("new content\n")
        binary = b"\x00\x01\xffrepair\x00"
        (self.repo / "binary.dat").write_bytes(binary)
        code, result, patch = await self.export(
            {"repo_path": str(self.repo), "base_commit": self.base}
        )
        self.assertEqual(code, 0, result)
        self.assertEqual(result["base_commit"], self.base)
        self.assertEqual(result["sha256"], hashlib.sha256(patch).hexdigest())
        self.assertEqual(result["size"], len(patch))
        validator = await self.clean_checkout()
        await self.git(validator, "apply", "--check", "--binary", "-", input_data=patch)
        await self.git(validator, "apply", "--binary", "-", input_data=patch)
        self.assertEqual((validator / "base.txt").read_text(), "committed change\n")
        self.assertEqual((validator / "staged.txt").read_text(), "staged plus unstaged\n")
        self.assertFalse((validator / "deleted.txt").exists())
        self.assertEqual((validator / "new file.txt").read_text(), "new content\n")
        self.assertEqual((validator / "binary.dat").read_bytes(), binary)

    async def test_exact_base_does_not_fall_back_to_a_branch_when_commit_is_missing(self) -> None:
        (self.repo / "base.txt").write_text("modified\n")
        code, result, patch = await self.export(
            {"repo_path": str(self.repo), "base_commit": "a" * 40}
        )
        self.assertNotEqual(code, 0)
        self.assertFalse(result["ok"])
        self.assertEqual(patch, b"")

    async def test_explicit_repository_does_not_fall_back_to_scanning_other_repositories(
        self,
    ) -> None:
        code, result, _ = await self.export(
            {"repo_path": str(self.root / "missing"), "base_commit": self.base}
        )
        self.assertNotEqual(code, 0)
        self.assertFalse(result["ok"])

    async def test_explicit_input_requires_both_repository_and_complete_commit(self) -> None:
        for payload in (
            {"repo_path": str(self.repo)},
            {"base_commit": self.base},
            {"repo_path": str(self.repo), "base_commit": self.base[:8]},
            {"repo_path": "agent repo", "base_commit": self.base},
        ):
            with self.subTest(payload=payload):
                code, result, _ = await self.export(payload)
                self.assertNotEqual(code, 0)
                self.assertFalse(result["ok"])

    async def test_default_dashboard_mode_still_exports_uncommitted_work(self) -> None:
        (self.repo / "base.txt").write_text("dashboard edit\n")
        code, result, patch = await self.export({"repo_name": "agent repo", "base_branch": "main"})
        self.assertEqual(code, 0, result)
        validator = await self.clean_checkout()
        await self.git(validator, "apply", "-", input_data=patch)
        self.assertEqual((validator / "base.txt").read_text(), "dashboard edit\n")

    async def test_repository_root_must_match_the_explicit_path(self) -> None:
        nested = self.repo / "nested"
        nested.mkdir()
        code, result, _ = await self.export({"repo_path": str(nested), "base_commit": self.base})
        self.assertNotEqual(code, 0)
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
