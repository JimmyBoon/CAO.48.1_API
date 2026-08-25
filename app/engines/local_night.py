"""
local_night.py — Shared "local night" derivation logic.

CAO 48.1 §6.1 (definitions): local night means a period of 8 consecutive
hours which includes the hours between 2200 and 0500 local time.

An off-duty period "includes a local night" only if it fully spans that
2200->0500 window on some calendar night — merely overlapping part of the
window (e.g. an off-duty period ending at 0400) does not qualify, even if
the period is otherwise long.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

_WINDOW_START_HOUR = 22  # 2200 local
_WINDOW_END_HOUR = 5     # 0500 local, on the following calendar day
_WINDOW_SPAN_HOURS = (24 - _WINDOW_START_HOUR) + _WINDOW_END_HOUR  # 7h


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def contains_local_night(
    period_start_utc: datetime,
    period_end_utc: datetime,
    local_offset_hours: float,
) -> bool:
    """
    Return True if the off-duty period fully spans a 2200->0500 local-time
    window (§6.1) on at least one night within the period.

    Derived purely from the period's own timestamps and the supplied local
    offset — never trusts a caller-supplied flag.
    """
    offset = timedelta(hours=local_offset_hours)
    start_local = _to_utc(period_start_utc) + offset
    end_local = _to_utc(period_end_utc) + offset

    day = start_local.replace(hour=0, minute=0, second=0, microsecond=0)
    last_day = end_local.replace(hour=0, minute=0, second=0, microsecond=0)

    while day <= last_day:
        window_start = day.replace(hour=_WINDOW_START_HOUR)
        window_end = window_start + timedelta(hours=_WINDOW_SPAN_HOURS)
        if start_local <= window_start and end_local >= window_end:
            return True
        day += timedelta(days=1)

    return False
