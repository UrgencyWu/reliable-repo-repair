import asyncio
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from agent.config import ENV


class FixtureConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    source_path: Path
    failing_command: str = Field(min_length=1, max_length=512)
    target_argv: list[str] = Field(min_length=1)
    regression_argv: list[list[str]] = Field(default_factory=list, max_length=10)
    allowed_patch_paths: list[str] = Field(min_length=1)
    shared: bool = False
    allowed_users: list[UUID] = Field(default_factory=list)


async def load_fixtures() -> list[FixtureConfig]:
    filename = ENV.REPAIR_FIXTURES_FILE.optional()
    if not filename:
        return []
    content = await asyncio.to_thread(Path(filename).read_text)
    fixtures = TypeAdapter(list[FixtureConfig]).validate_json(content)
    if len({fixture.id for fixture in fixtures}) != len(fixtures):
        raise ValueError("Repair fixture ids must be unique")
    for fixture in fixtures:
        if not fixture.source_path.is_absolute() or not fixture.source_path.is_dir():
            raise ValueError("Repair fixture source must be an existing absolute directory")
        if any(not argv for argv in fixture.regression_argv):
            raise ValueError("Regression commands must not be empty")
        if any(
            Path(path).is_absolute() or ".." in Path(path).parts
            for path in fixture.allowed_patch_paths
        ):
            raise ValueError("Allowed patch paths must be relative to the fixture")
    return fixtures


async def require_fixture(fixture_id: str, owner_id: UUID) -> FixtureConfig:
    for fixture in await load_fixtures():
        if fixture.id == fixture_id and (fixture.shared or owner_id in fixture.allowed_users):
            return fixture
    raise LookupError("Repair fixture is unavailable to this user")
