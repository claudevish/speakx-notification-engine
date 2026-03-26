"""Redis Streams consumer — reads progress and profile events with consumer group semantics."""

import asyncio
import json

import structlog
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.events.processor import EventProcessor
from app.events.schemas import ProfileEvent, ProgressEvent

logger = structlog.get_logger()

PROGRESS_STREAM = "user:progress:events"
PROFILE_STREAM = "user:profile:events"


class EventConsumer:
    """Consumes user progress and profile events from Redis Streams.

    Uses consumer groups for reliable delivery with automatic
    reconnection on failure (exponential backoff, max 5 attempts).
    """

    def __init__(
        self,
        redis_url: str,
        group_name: str = "notification-engine",
        consumer_name: str = "consumer-1",
    ) -> None:
        self.redis_url = redis_url
        self.group_name = group_name
        self.consumer_name = consumer_name
        self._running = False
        self._redis: Redis | None = None

    async def start(self) -> None:
        """Start the consumer loop with automatic reconnection."""
        self._running = True
        reconnect_attempts = 0
        max_reconnects = 5

        while self._running:
            try:
                self._redis = Redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_timeout=10,
                )
                await self._ensure_consumer_groups()
                reconnect_attempts = 0
                logger.info(
                    "Event consumer started",
                    group=self.group_name,
                    consumer=self.consumer_name,
                )
                await self._consume_loop()
            except asyncio.CancelledError:
                logger.info("Event consumer cancelled")
                break
            except Exception:
                reconnect_attempts += 1
                if reconnect_attempts > max_reconnects:
                    logger.critical(
                        "Max reconnection attempts exceeded",
                        attempts=reconnect_attempts,
                    )
                    break
                backoff = min(2**reconnect_attempts, 60)
                logger.exception(
                    "Consumer error, reconnecting",
                    attempt=reconnect_attempts,
                    backoff=backoff,
                )
                await asyncio.sleep(backoff)
            finally:
                await self._cleanup()

    async def _consume_loop(self) -> None:
        while self._running:
            if self._redis is None:
                break

            messages = await self._redis.xreadgroup(
                groupname=self.group_name,
                consumername=self.consumer_name,
                streams={
                    PROGRESS_STREAM: ">",
                    PROFILE_STREAM: ">",
                },
                count=10,
                block=5000,
            )

            if not messages:
                continue

            for stream_name, stream_messages in messages:
                for message_id, data in stream_messages:
                    await self._process_message(
                        stream_name, message_id, data,
                    )

    async def stop(self) -> None:
        """Signal the consumer loop to stop."""
        self._running = False

    async def _ensure_consumer_groups(self) -> None:
        if self._redis is None:
            return
        for stream in (PROGRESS_STREAM, PROFILE_STREAM):
            try:
                await self._redis.xgroup_create(
                    stream, self.group_name, id="0", mkstream=True,
                )
            except ResponseError as exc:
                if "BUSYGROUP" not in str(exc):
                    raise

    async def _process_message(
        self, stream: str, message_id: str, data: dict,
    ) -> None:
        if self._redis is None:
            return

        try:
            payload_str = data.get("payload", "{}")
            payload = json.loads(payload_str) if isinstance(payload_str, str) else payload_str

            from app.models.base import AsyncSessionLocal

            async with AsyncSessionLocal() as db_session:
                from app.config.manager import ConfigManager

                config = ConfigManager(db_session)
                processor = EventProcessor(db_session, config)

                if stream == PROGRESS_STREAM:
                    event = ProgressEvent(**payload)
                    await processor.process(event)
                elif stream == PROFILE_STREAM:
                    event = ProfileEvent(**payload)
                    await processor.process(event)

                await db_session.commit()

            await self._redis.xack(stream, self.group_name, message_id)

        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.warning(
                "Malformed message, acknowledging",
                stream=stream,
                message_id=message_id,
                error=str(exc),
            )
            await self._redis.xack(
                stream, self.group_name, message_id,
            )
        except Exception:
            logger.exception(
                "Failed to process message",
                stream=stream,
                message_id=message_id,
            )
            await self._redis.xack(
                stream, self.group_name, message_id,
            )

    async def _cleanup(self) -> None:
        if self._redis:
            await self._redis.aclose()
        logger.info("Event consumer stopped")
