"""Daily journey progress snapshots for funnel analysis."""

from datetime import date

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics import JourneyProgressSnapshot
from app.models.user import UserJourneyState

logger = structlog.get_logger()


async def take_daily_snapshots(
    db_session: AsyncSession,
) -> dict:
    today = date.today()
    summary = {
        "snapshots_created": 0,
        "snapshots_skipped": 0,
        "view_refreshed": False,
    }

    result = await db_session.execute(
        select(UserJourneyState),
    )
    states = result.scalars().all()

    for state in states:
        existing = await db_session.execute(
            select(JourneyProgressSnapshot).where(
                JourneyProgressSnapshot.user_id == state.user_id,
                JourneyProgressSnapshot.journey_id
                == state.journey_id,
                JourneyProgressSnapshot.snapshot_date == today,
            ),
        )
        if existing.scalar_one_or_none():
            summary["snapshots_skipped"] += 1
            continue

        chapter_progress = {}
        if state.current_chapter_id:
            chapter_progress["current_chapter_id"] = str(
                state.current_chapter_id,
            )
        if state.current_quest_id:
            chapter_progress["current_quest_id"] = str(
                state.current_quest_id,
            )

        activities_completed = 0
        if state.sliding_window_scores:
            activities_completed = len(
                state.sliding_window_scores,
            )

        snapshot = JourneyProgressSnapshot(
            user_id=state.user_id,
            journey_id=state.journey_id,
            snapshot_date=today,
            state=state.current_state,
            chapter_progress=chapter_progress or None,
            total_activities_completed=activities_completed,
        )
        db_session.add(snapshot)
        summary["snapshots_created"] += 1

    await db_session.flush()

    try:
        await db_session.execute(
            text(
                "REFRESH MATERIALIZED VIEW"
                " CONCURRENTLY segment_performance"
            ),
        )
        summary["view_refreshed"] = True
    except Exception as exc:
        logger.warning(
            "Materialized view refresh failed",
            error=str(exc),
        )

    logger.info("Daily snapshots complete", **summary)
    return summary
