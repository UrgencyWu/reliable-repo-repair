"""Create private local Compose settings without printing credentials."""

import asyncio
import secrets
from pathlib import Path


async def main() -> None:
    path = Path(".env.repair")
    contents = (
        f"DASHBOARD_JWT_SECRET={secrets.token_hex(32)}\n"
        f"POSTGRES_PASSWORD={secrets.token_hex(24)}\n"
        "REPAIR_UI_PORT=3012\n"
        "REPAIR_API_PORT=2032\n"
    )

    def write() -> None:
        with path.open("x", encoding="utf-8") as file:
            path.chmod(0o600)
            file.write(contents)

    await asyncio.to_thread(write)
    print("Created private .env.repair; keep it for subsequent restarts.")


if __name__ == "__main__":
    asyncio.run(main())
