"""Bootstrap a trusted local fixture and the existing session format for development."""

import asyncio
import json
import os
import sys
from pathlib import Path

from agent.config import ENV
from agent.dashboard.oauth import COOKIE_NAME, issue_session
from agent.database import postgres
from agent.repair.process import git
from agent.users import User


async def main() -> None:
    root = Path(os.environ.get("REPAIR_DEMO_DIR", ".tools/repair-demo")).resolve()
    await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
    source = root / "source"
    if not source.exists():
        await asyncio.to_thread(source.mkdir)
        await asyncio.to_thread(
            (source / "calc.py").write_text, "def add(a, b):\n    return a - b\n"
        )
        await asyncio.to_thread(
            (source / "test_calc.py").write_text,
            "import unittest\nfrom calc import add\nclass TestCalc(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n",
        )
        await asyncio.to_thread((source / ".gitignore").write_text, "__pycache__/\n")
        await git(source, "init", "--initial-branch=main")
        await git(source, "add", ".")
        await git(
            source,
            "-c",
            "user.name=Repair Demo",
            "-c",
            "user.email=demo@example.invalid",
            "commit",
            "-m",
            "broken arithmetic fixture",
        )
    commit = (await git(source, "rev-parse", "HEAD")).decode().strip()
    ENV.DASHBOARD_JWT_SECRET.require()
    await postgres.migrate()
    user = await User.sign_in(
        "github", "repair-demo-local", login="repair-demo", display_name="Repair Demo"
    )
    validation_python = str(Path(sys.executable).resolve())
    fixtures = [
        {
            "id": "arithmetic",
            "source_path": str(source),
            "failing_command": "python3 -m unittest test_calc.py",
            "target_argv": [
                validation_python,
                "-S",
                "-c",
                "from calc import add; assert add(2, 3) == 5",
            ],
            "regression_argv": [
                [
                    validation_python,
                    "-S",
                    "-c",
                    "from calc import add; assert add(-2, 5) == 3; assert add(0, 0) == 0",
                ]
            ],
            "allowed_patch_paths": ["calc.py"],
            "allowed_users": [str(user.id)],
        }
    ]
    await asyncio.to_thread((root / "fixtures.json").write_text, json.dumps(fixtures, indent=2))
    session = {
        "cookie_name": COOKIE_NAME,
        "cookie_value": issue_session(
            login="repair-demo", email=None, avatar_url=None, user_id=str(user.id)
        ),
        "fixture_id": "arithmetic",
        "target_commit": commit,
        "failing_command": fixtures[0]["failing_command"],
        "user_id": str(user.id),
    }
    session_file = root / "session.json"
    await asyncio.to_thread(session_file.touch, mode=0o600, exist_ok=True)
    await asyncio.to_thread(session_file.chmod, 0o600)
    await asyncio.to_thread(session_file.write_text, json.dumps(session, indent=2))
    await postgres.engine().dispose()
    print(f"Fixture and private development session written to {root}")


if __name__ == "__main__":
    asyncio.run(main())
