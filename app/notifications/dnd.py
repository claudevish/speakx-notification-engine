"""Do Not Disturb (DND) enforcement for notification scheduling.

Prevents notifications from being sent during night hours in IST (11 PM to 7 AM).
All functions accept UTC datetimes and handle IST conversion internally.
"""

from datetime import datetime, timedelta, timezone

IST_OFFSET = timedelta(hours=5, minutes=30)
DND_START_HOUR = 23  # 11 PM IST
DND_END_HOUR = 7  # 7 AM IST
MIN_GAP_MINUTES = 20  # Minimum gap between consecutive notifications


def to_ist(dt: datetime) -> datetime:
    """Convert a UTC datetime to IST (UTC+5:30).

    Args:
        dt: A datetime in UTC (naive or aware).

    Returns:
        The equivalent IST datetime (naive, for hour extraction).
    """
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt + IST_OFFSET


def is_dnd_active(dt: datetime) -> bool:
    """Check if a UTC datetime falls within the DND window (11 PM - 7 AM IST).

    Args:
        dt: A datetime in UTC to check.

    Returns:
        True if the time is within DND hours in IST.
    """
    ist_time = to_ist(dt)
    hour = ist_time.hour
    return hour >= DND_START_HOUR or hour < DND_END_HOUR


def get_dnd_start_for_date(payment_time: datetime) -> datetime:
    """Get 23:00 IST on the same calendar day as payment_time, returned as UTC.

    Args:
        payment_time: The payment timestamp in UTC.

    Returns:
        The DND start time (23:00 IST) as a UTC datetime.
    """
    ist_time = to_ist(payment_time)
    dnd_start_ist = ist_time.replace(
        hour=DND_START_HOUR,
        minute=0,
        second=0,
        microsecond=0,
    )
    return dnd_start_ist - IST_OFFSET


def get_dnd_end_for_date(payment_time: datetime) -> datetime:
    """Get 07:00 IST on the next calendar day after payment_time, returned as UTC.

    Args:
        payment_time: The payment timestamp in UTC.

    Returns:
        The DND end time (07:00 IST next day) as a UTC datetime.
    """
    ist_time = to_ist(payment_time)
    next_day = ist_time.replace(
        hour=DND_END_HOUR,
        minute=0,
        second=0,
        microsecond=0,
    ) + timedelta(days=1)
    return next_day - IST_OFFSET


def has_minimum_gap(
    send_at: datetime,
    accepted_times: list[datetime],
) -> bool:
    """Check if a proposed send time has at least MIN_GAP_MINUTES from all accepted times.

    Args:
        send_at: The proposed send time (UTC).
        accepted_times: List of already-accepted send times (UTC).

    Returns:
        True if the minimum gap is satisfied against all accepted times.
    """
    for accepted in accepted_times:
        gap = abs((send_at - accepted).total_seconds()) / 60
        if gap < MIN_GAP_MINUTES:
            return False
    return True
