"""
Derivation of local-time window overlaps from UTC timestamps.

The principle is the one `/validate/sequence` already applies to
`crosses_wocl`: where the API holds the timestamps and the offset, it derives
the fact rather than trusting a caller-supplied flag. A flag that gates a
prohibition is worth nothing if the caller can simply set it to False.

`overlaps_2300_0529` was the outstanding case. It gates Appendix 3 §3.4(a) —
after Phase 3, a night-overlapping split-duty rest under 7 hours earns no FDP
increase at all — but the value was taken on trust. A rest running 2200-0300
local, which plainly overlaps, could be flagged False and collect the full
§3.1 increase.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _to_utc(dt: datetime | str) -> datetime:
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def overlaps_local_window(
    period_start_utc: datetime | str,
    period_end_utc: datetime | str,
    local_offset_hours: float,
    window_start_minutes: int,
    window_end_minutes: int,
) -> bool:
    """
    True if any part of the period falls inside a daily local-time window.

    The window is given as minutes from local midnight and may wrap midnight
    (2300-0529 does). The test is "any part", matching how §3.4 is phrased:
    "if a split-duty rest period includes **any** period between the hours of
    2300 to 0529 local time".
    """
    offset = timedelta(hours=local_offset_hours)
    start_local = _to_utc(period_start_utc) + offset
    end_local = _to_utc(period_end_utc) + offset

    if start_local >= end_local:
        return False

    wraps = window_start_minutes > window_end_minutes

    day = start_local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    last_day = end_local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

    while day <= last_day:
        if wraps:
            spans = [
                (day + timedelta(minutes=window_start_minutes), day + timedelta(days=1)),
                (day, day + timedelta(minutes=window_end_minutes + 1)),
            ]
        else:
            spans = [(
                day + timedelta(minutes=window_start_minutes),
                day + timedelta(minutes=window_end_minutes + 1),
            )]
        for window_start, window_end in spans:
            if start_local < window_end and end_local > window_start:
                return True
        day += timedelta(days=1)

    return False
