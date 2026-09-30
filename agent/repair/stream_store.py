"""PostgreSQL side of Redis Stream publication and consumption."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update

from agent.database import postgres
from agent.repair.models import DispatchIntent
from agent.repair.state import DispatchStatus


@dataclass(frozen=True)
class DueIntent:
    id: UUID
    attempt_count: int
    redis_stream_id: str | None


async def due_intents(limit: int = 20, offset: int = 0) -> list[DueIntent]:
    async with postgres.session() as session:
        intents = await session.scalars(
            select(DispatchIntent)
            .where(
                DispatchIntent.status == DispatchStatus.PENDING,
                DispatchIntent.next_retry_at <= func.clock_timestamp(),
            )
            .order_by(DispatchIntent.next_retry_at, DispatchIntent.id)
            .limit(limit)
            .offset(offset)
        )
        return [DueIntent(i.id, i.attempt_count, i.redis_stream_id) for i in intents]


async def record_published(intent: DueIntent, stream_id: str) -> bool:
    async with postgres.session() as session:
        recorded = await session.scalar(
            update(DispatchIntent)
            .where(
                DispatchIntent.id == intent.id,
                DispatchIntent.status == DispatchStatus.PENDING,
                DispatchIntent.attempt_count == intent.attempt_count,
                DispatchIntent.redis_stream_id.is_not_distinct_from(intent.redis_stream_id),
            )
            .values(redis_stream_id=stream_id, redis_published_at=func.clock_timestamp())
            .returning(DispatchIntent.id)
        )
        return recorded is not None


async def message_settled(intent_id: UUID) -> bool:
    async with postgres.session() as session:
        row = await session.execute(
            select(
                DispatchIntent.status, DispatchIntent.next_retry_at, func.clock_timestamp()
            ).where(DispatchIntent.id == intent_id)
        )
        result = row.one_or_none()
        if result is None:
            return True
        status, next_retry_at, now = result
        assert isinstance(status, DispatchStatus)
        assert isinstance(next_retry_at, datetime)
        assert isinstance(now, datetime)
        return status not in {DispatchStatus.CLAIMED, DispatchStatus.PENDING} or (
            status == DispatchStatus.PENDING and next_retry_at > now
        )
