"""Day 0 notification schedule calculator.

Ported from NotifyGen's automation-engine.js calculateDay0Schedule().
Given a payment timestamp, calculates up to 6 time-staggered notification
slots respecting DND hours, drop priorities, and minimum gap rules.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog

from app.notifications.dnd import (
    MIN_GAP_MINUTES,
    get_dnd_start_for_date,
    has_minimum_gap,
)
from app.notifications.schemas import NotificationTheme

logger = structlog.get_logger()


@dataclass
class Day0Template:
    """Definition of a Day 0 notification slot."""

    slot: int
    name: str
    delay_minutes: int  # 0=immediate, -1=30min before DND
    drop_priority: int  # 1=never drop, 6=first to drop
    theme: NotificationTheme
    segment: str


@dataclass
class ScheduledSlot:
    """A resolved notification slot with a concrete send time."""

    slot: int
    name: str
    send_at: datetime
    drop_priority: int
    theme: NotificationTheme
    segment: str


DAY0_TEMPLATES: list[Day0Template] = [
    Day0Template(
        slot=1,
        name="Trial Payment",
        delay_minutes=0,
        drop_priority=1,
        theme=NotificationTheme.motivational,
        segment="Trial Payment",
    ),
    Day0Template(
        slot=2,
        name="Onboarding Nudge",
        delay_minutes=30,
        drop_priority=2,
        theme=NotificationTheme.story_teaser,
        segment="New Users",
    ),
    Day0Template(
        slot=3,
        name="Word of the Day",
        delay_minutes=150,
        drop_priority=4,
        theme=NotificationTheme.wotd,
        segment="New Users",
    ),
    Day0Template(
        slot=4,
        name="Cliffhanger",
        delay_minutes=300,
        drop_priority=5,
        theme=NotificationTheme.click_bait,
        segment="In Progress",
    ),
    Day0Template(
        slot=5,
        name="Social Proof",
        delay_minutes=480,
        drop_priority=6,
        theme=NotificationTheme.social_proof,
        segment="3-Day Inactive",
    ),
    Day0Template(
        slot=6,
        name="Progress Report",
        delay_minutes=-1,
        drop_priority=3,
        theme=NotificationTheme.recap,
        segment="In Progress",
    ),
]

SLOT_THEME_MAP: dict[int, NotificationTheme] = {
    t.slot: t.theme for t in DAY0_TEMPLATES
}


def calculate_day0_schedule(
    payment_time: datetime,
) -> list[ScheduledSlot]:
    """Calculate the Day 0 notification schedule for a given payment time.

    Implements the NotifyGen scheduling algorithm:
    1. Calculate DND start (23:00 IST on payment day)
    2. Sort templates by drop_priority (most important first)
    3. For each template, calculate send_at
    4. Skip if send_at >= DND start
    5. Skip if send_at conflicts with already-accepted slot (20-min gap)
    6. Return the schedule sorted by send_at ascending

    Args:
        payment_time: UTC datetime of the payment event.

    Returns:
        List of ScheduledSlot objects sorted by send_at.
    """
    dnd_start = get_dnd_start_for_date(payment_time)

    sorted_templates = sorted(DAY0_TEMPLATES, key=lambda t: t.drop_priority)

    accepted: list[ScheduledSlot] = []
    accepted_times: list[datetime] = []

    for template in sorted_templates:
        send_at = _calculate_send_time(template, payment_time, dnd_start)

        if send_at is None:
            logger.debug(
                "Day0 slot dropped: could not calculate send time",
                slot=template.slot,
                name=template.name,
            )
            continue

        # Slot 1 (immediate, delay=0) always fires regardless of DND
        if template.delay_minutes != 0 and send_at >= dnd_start:
            logger.debug(
                "Day0 slot dropped: falls in DND",
                slot=template.slot,
                name=template.name,
                send_at=send_at.isoformat(),
                dnd_start=dnd_start.isoformat(),
            )
            continue

        if template.delay_minutes != 0 and not has_minimum_gap(
            send_at, accepted_times
        ):
            logger.debug(
                "Day0 slot dropped: gap conflict",
                slot=template.slot,
                name=template.name,
                min_gap=MIN_GAP_MINUTES,
            )
            continue

        accepted.append(
            ScheduledSlot(
                slot=template.slot,
                name=template.name,
                send_at=send_at,
                drop_priority=template.drop_priority,
                theme=template.theme,
                segment=template.segment,
            )
        )
        accepted_times.append(send_at)

    accepted.sort(key=lambda s: s.send_at)

    logger.info(
        "Day0 schedule calculated",
        payment_time=payment_time.isoformat(),
        total_slots=len(accepted),
        dropped=len(DAY0_TEMPLATES) - len(accepted),
        slots=[s.slot for s in accepted],
    )

    return accepted


def _calculate_send_time(
    template: Day0Template,
    payment_time: datetime,
    dnd_start: datetime,
) -> datetime | None:
    """Calculate the send time for a single Day 0 template.

    Args:
        template: The Day 0 template definition.
        payment_time: UTC datetime of the payment event.
        dnd_start: UTC datetime of DND start (23:00 IST).

    Returns:
        The calculated send time in UTC, or None if invalid.
    """
    if template.delay_minutes == 0:
        return payment_time

    if template.delay_minutes == -1:
        send_at = dnd_start - timedelta(minutes=30)
        if send_at <= payment_time:
            return None
        return send_at

    return payment_time + timedelta(minutes=template.delay_minutes)
