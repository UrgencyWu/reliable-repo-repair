"""Redis Streams delivery for durable PostgreSQL repair intents."""

import asyncio
import logging
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError, ResponseError

from agent.repair import dispatch_store, stream_store
from agent.repair.dispatch import RepairDispatcher

logger = logging.getLogger(__name__)

STREAM = "open-swe:repair:dispatch"
GROUP = "repair-workers"
RECLAIM_IDLE_MS = 45_000


class RepairStreamTransport:
    def __init__(self, url: str, dispatcher: RepairDispatcher) -> None:
        self.url = url
        self.dispatcher = dispatcher
        self.reclaim_cursor = "0-0"

    async def run(self) -> None:
        async with asyncio.TaskGroup() as group:
            group.create_task(self.publish_forever(), name="repair-stream-publisher")
            group.create_task(self.consume_forever(), name="repair-stream-consumer")

    async def publish_forever(self) -> None:
        while True:
            try:
                async with Redis.from_url(
                    self.url, decode_responses=True, socket_connect_timeout=1, socket_timeout=2
                ) as redis:
                    while True:
                        await self.publish_due(redis)
                        await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except RedisError, OSError, TimeoutError:
                logger.warning("Repair Stream publication unavailable; retrying", exc_info=True)
                await asyncio.sleep(1)
            except Exception:
                logger.exception("Repair Stream publisher failed; retrying")
                await asyncio.sleep(1)

    async def publish_due(self, redis: Redis) -> None:
        offset = 0
        while True:
            intents = await stream_store.due_intents(offset=offset)
            if not intents:
                return
            for intent in intents:
                if intent.redis_stream_id is not None:
                    existing = await redis.xrange(
                        STREAM, min=intent.redis_stream_id, max=intent.redis_stream_id, count=1
                    )
                    if existing and existing[0][1].get("intent_id") == str(intent.id):
                        continue
                stream_id = await redis.xadd(STREAM, {"intent_id": str(intent.id)})
                if await stream_store.record_published(intent, stream_id):
                    logger.info(
                        "Repair intent published to Redis Stream",
                        extra={"dispatch_intent_id": str(intent.id), "stream_id": stream_id},
                    )
            offset += len(intents)

    async def consume_forever(self) -> None:
        while True:
            try:
                async with Redis.from_url(
                    self.url, decode_responses=True, socket_connect_timeout=1, socket_timeout=3
                ) as redis:
                    await self.ensure_group(redis)
                    while True:
                        try:
                            await self.consume_once(redis)
                        except ResponseError as exc:
                            if "NOGROUP" not in str(exc):
                                raise
                            await self.ensure_group(redis)
            except asyncio.CancelledError:
                raise
            except RedisError, OSError, TimeoutError:
                logger.warning("Repair Stream consumption unavailable; retrying", exc_info=True)
                await asyncio.sleep(1)
            except Exception:
                logger.exception("Repair Stream consumer failed; retrying")
                await asyncio.sleep(1)

    async def ensure_group(self, redis: Redis) -> None:
        self.reclaim_cursor = "0-0"
        try:
            await redis.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def consume_once(self, redis: Redis) -> None:
        claimed = await redis.xautoclaim(
            STREAM, GROUP, self.dispatcher.worker_id, RECLAIM_IDLE_MS, self.reclaim_cursor, count=5
        )
        self.reclaim_cursor = claimed[0]
        for stream_id, fields in claimed[1]:
            await self.handle_message(redis, stream_id, fields)
        messages = await redis.xreadgroup(
            GROUP, self.dispatcher.worker_id, {STREAM: ">"}, count=5, block=1000
        )
        for _, entries in messages:
            for stream_id, fields in entries:
                await self.handle_message(redis, stream_id, fields)

    async def handle_message(self, redis: Redis, stream_id: str, fields: dict[str, str]) -> None:
        try:
            intent_id = UUID(fields["intent_id"])
        except KeyError, ValueError:
            logger.warning("Invalid repair Stream message", extra={"stream_id": stream_id})
            await self.ack_message(redis, stream_id)
            return
        claim = await dispatch_store.claim_intent(intent_id, self.dispatcher.worker_id)
        if claim is not None:
            await self.dispatcher.dispatch(claim)
        if await stream_store.message_settled(intent_id):
            await self.ack_message(redis, stream_id)

    async def ack_message(self, redis: Redis, stream_id: str) -> None:
        await redis.xack(STREAM, GROUP, stream_id)
        await redis.xdel(STREAM, stream_id)
