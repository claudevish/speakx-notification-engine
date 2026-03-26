"""Standalone event consumer worker — bridges Redis Streams to the event processor."""

import asyncio
import signal

import structlog

logger = structlog.get_logger()


def main() -> None:
    """Entry point for the event consumer worker process."""
    asyncio.run(_run())


async def _run() -> None:
    from app.config.settings import settings
    from app.events.consumer import EventConsumer

    consumer = EventConsumer(redis_url=settings.redis_url)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(consumer.stop()))

    logger.info("Event consumer worker starting", redis_url=settings.redis_url)
    await consumer.start()
    logger.info("Event consumer worker stopped")


if __name__ == "__main__":
    main()
