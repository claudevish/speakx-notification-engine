"""Load test script — simulate N users worth of events."""

import argparse
import asyncio
import json
import os
import random
import time
import uuid

import redis.asyncio as aioredis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
STREAM_KEY = "user:progress:events"

STATES = [
    "new_unstarted",
    "onboarding",
    "progressing_active",
    "progressing_slow",
]

EVENT_TYPES = [
    "activity_completed",
    "chapter_completed",
    "app_opened",
]


async def publish_events(
    num_users: int,
    batch_size: int = 500,
) -> dict:
    redis = aioredis.from_url(REDIS_URL)
    journey_id = str(uuid.uuid4())

    total_events = 0
    start = time.time()

    try:
        for batch_start in range(0, num_users, batch_size):
            batch_end = min(batch_start + batch_size, num_users)
            pipe = redis.pipeline()

            for i in range(batch_start, batch_end):
                user_id = f"load-test-user-{i:06d}"
                num_events = random.randint(3, 5)

                for _ in range(num_events):
                    event = {
                        "user_id": user_id,
                        "journey_id": journey_id,
                        "event_type": random.choice(EVENT_TYPES),
                        "data": json.dumps({
                            "score": random.randint(50, 100),
                            "time_spent_seconds": random.randint(
                                30, 300,
                            ),
                        }),
                    }
                    pipe.xadd(STREAM_KEY, event)
                    total_events += 1

            await pipe.execute()

            elapsed = time.time() - start
            rate = total_events / elapsed if elapsed > 0 else 0
            print(
                f"  Batch {batch_start}-{batch_end}: "
                f"{total_events} events, "
                f"{rate:.0f} events/sec"
            )

    finally:
        await redis.aclose()

    elapsed = time.time() - start
    return {
        "total_events": total_events,
        "total_users": num_users,
        "elapsed_seconds": round(elapsed, 2),
        "events_per_second": round(
            total_events / elapsed if elapsed > 0 else 0, 1,
        ),
        "journey_id": journey_id,
    }


async def check_results(wait_seconds: int = 60) -> dict:
    print(
        f"\nWaiting {wait_seconds}s for processing..."
    )
    await asyncio.sleep(wait_seconds)

    try:
        from sqlalchemy import func, select
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            create_async_engine,
        )

        db_url = os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://speakx:speakx_dev"
            "@localhost:5432/speakx_notifications",
        )
        engine = create_async_engine(db_url)

        async with AsyncSession(engine) as session:
            from app.models.notification import Notification
            from app.models.user import UserJourneyState

            state_result = await session.execute(
                select(
                    UserJourneyState.current_state,
                    func.count(),
                ).group_by(
                    UserJourneyState.current_state,
                ),
            )
            state_dist = {
                r[0]: r[1] for r in state_result.all()
            }

            notif_result = await session.execute(
                select(func.count()).select_from(
                    Notification,
                ),
            )
            notif_count = notif_result.scalar() or 0

        await engine.dispose()

        return {
            "state_distribution": state_dist,
            "total_user_states": sum(state_dist.values()),
            "notifications_generated": notif_count,
        }
    except Exception as exc:
        return {"error": str(exc)}


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load test the notification engine",
    )
    parser.add_argument(
        "--users",
        type=int,
        default=100,
        help="Number of users to simulate",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=60,
        help="Seconds to wait before checking results",
    )
    parser.add_argument(
        "--skip-check",
        action="store_true",
        help="Skip result checking (just publish events)",
    )
    args = parser.parse_args()

    print(f"=== Load Test: {args.users} users ===\n")
    print("Publishing events...")

    publish_result = await publish_events(args.users)
    print("\n--- Publish Summary ---")
    for k, v in publish_result.items():
        print(f"  {k}: {v}")

    if not args.skip_check:
        results = await check_results(args.wait)
        print("\n--- Processing Results ---")
        for k, v in results.items():
            print(f"  {k}: {v}")

    print("\n=== Load Test Complete ===")


if __name__ == "__main__":
    asyncio.run(main())
