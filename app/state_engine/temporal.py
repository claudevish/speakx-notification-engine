"""Periodic temporal scans for dormancy and chapter-transition detection.

Contains standalone async functions designed to run on a scheduler (e.g.
Celery beat, APScheduler).  Each function queries users whose inactivity
exceeds configurable thresholds and moves them into the appropriate
dormancy tier or chapter-transition state.
"""

from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import ConfigManager
from app.models.user import UserJourneyState
from app.state_engine.machine import ACTIVE_STATES

logger = structlog.get_logger()


async def scan_dormancy(
    db_session: AsyncSession, config_manager: ConfigManager,
) -> dict[str, int | dict[str, int]]:
    """Scan active and dormant users and escalate dormancy tiers as needed.

    Checks every user in an active or dormant state and, based on the
    number of days since their last activity, transitions them through
    ``dormant_short`` -> ``dormant_long`` -> ``churned``.

    Thresholds are read from ``config_manager``:
        - ``short_threshold_days`` (default 2)
        - ``long_threshold_days`` (default 7)
        - ``churned_threshold_days`` (default 30)

    Args:
        db_session: An async SQLAlchemy session for querying and updating
            user journey states.
        config_manager: Provides configurable dormancy thresholds.

    Returns:
        A dict with ``"users_scanned"`` (int) and ``"transitions"`` (a dict
        mapping each dormancy target state to the count of users moved
        into it).
    """
    short_days = await config_manager.get("short_threshold_days", 2)
    long_days = await config_manager.get("long_threshold_days", 7)
    churned_days = await config_manager.get("churned_threshold_days", 30)

    now = datetime.now(timezone.utc)
    transitions: dict[str, int] = {"dormant_short": 0, "dormant_long": 0, "churned": 0}
    scanned = 0

    scannable_states = list(ACTIVE_STATES) + ["dormant_short", "dormant_long"]
    result = await db_session.execute(
        select(UserJourneyState).where(
            UserJourneyState.current_state.in_(scannable_states),
            UserJourneyState.last_activity_at.is_not(None),
        )
    )
    users = result.scalars().all()
    scanned = len(users)

    for user_state in users:
        if user_state.last_activity_at is None:
            continue

        last_activity = user_state.last_activity_at
        if last_activity.tzinfo is None:
            last_activity = last_activity.replace(tzinfo=timezone.utc)
        inactive_days = (now - last_activity).days

        if user_state.current_state in ACTIVE_STATES and inactive_days >= short_days:
            user_state.current_state = "dormant_short"
            user_state.state_entered_at = now
            transitions["dormant_short"] += 1
            logger.info(
                "Dormancy transition",
                user_id=user_state.user_id,
                journey_id=str(user_state.journey_id),
                to_state="dormant_short",
                inactive_days=inactive_days,
            )

        elif user_state.current_state == "dormant_short" and inactive_days >= long_days:
            user_state.current_state = "dormant_long"
            user_state.state_entered_at = now
            transitions["dormant_long"] += 1
            logger.info(
                "Dormancy transition",
                user_id=user_state.user_id,
                journey_id=str(user_state.journey_id),
                to_state="dormant_long",
                inactive_days=inactive_days,
            )

        elif user_state.current_state == "dormant_long" and inactive_days >= churned_days:
            user_state.current_state = "churned"
            user_state.state_entered_at = now
            transitions["churned"] += 1
            logger.info(
                "Dormancy transition",
                user_id=user_state.user_id,
                journey_id=str(user_state.journey_id),
                to_state="churned",
                inactive_days=inactive_days,
            )

    await db_session.flush()

    logger.info(
        "Dormancy scan complete",
        users_scanned=scanned,
        transitions_made=sum(transitions.values()),
        by_type=transitions,
    )
    return {"users_scanned": scanned, "transitions": transitions}


async def scan_chapter_transitions(
    db_session: AsyncSession, config_manager: ConfigManager,
) -> dict[str, int]:
    """Detect users who completed a chapter but have not started the next.

    Queries users in active states and checks their ``chapter_progress``
    for any chapter marked ``chapter_completed`` whose completion timestamp
    exceeds the configured inactivity window.  Matching users are moved
    into the ``chapter_transition`` state.

    Args:
        db_session: An async SQLAlchemy session for querying and updating
            user journey states.
        config_manager: Provides the ``chapter_transition_inactivity_hours``
            threshold (default 24).

    Returns:
        A dict with ``"users_scanned"`` (int) and ``"transitions"`` (int
        count of users moved into ``chapter_transition``).
    """
    inactivity_hours = await config_manager.get("chapter_transition_inactivity_hours", 24)
    now = datetime.now(timezone.utc)
    transitioned = 0

    result = await db_session.execute(
        select(UserJourneyState).where(
            UserJourneyState.current_state.in_(list(ACTIVE_STATES)),
            UserJourneyState.last_activity_at.is_not(None),
        )
    )
    users = result.scalars().all()

    for user_state in users:
        if user_state.current_state == "chapter_transition":
            continue

        progress = user_state.chapter_progress or {}
        has_completed_chapter = False
        for _ch_key, ch_data in progress.items():
            if isinstance(ch_data, dict) and ch_data.get("chapter_completed", False):
                completed_at_str = ch_data.get("completed_at")
                if completed_at_str:
                    completed_at = datetime.fromisoformat(completed_at_str)
                    hours_since = (now - completed_at).total_seconds() / 3600
                    if hours_since >= inactivity_hours:
                        has_completed_chapter = True
                        break

        if has_completed_chapter:
            user_state.current_state = "chapter_transition"
            user_state.state_entered_at = now
            transitioned += 1
            logger.info(
                "Chapter transition",
                user_id=user_state.user_id,
                journey_id=str(user_state.journey_id),
            )

    await db_session.flush()

    logger.info(
        "Chapter transition scan complete",
        users_scanned=len(users),
        transitions_made=transitioned,
    )
    return {"users_scanned": len(users), "transitions": transitioned}
