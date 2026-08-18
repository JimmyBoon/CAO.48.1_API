"""
wocl.py — Shared WOCL (window of circadian low) derivation logic.

CAO 48.1 §6.1(a)(i)/(ii)/(b): WOCL means 0200-0559 local time — at the
acclimatised location for Appendix 2, or at the location where the FCM
commences the duty for every other appendix.

§6.2: if any duty is performed during all, or any part, of the WOCL, the
WOCL is infringed — this is an "any overlap" test, unlike a local night
(§6.1's 8-consecutive-hour definition), which requires full containment.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

_WOCL_START_HOUR = 2  # 0200 local
_WOCL_END_HOUR = 6    # 0600 local (exclusive upper bound, i.e. up to 0559)


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def crosses_wocl(
    period_start_utc: datetime,
    period_end_utc: datetime,
    local_offset_hours: float,
) -> bool:
    """
    Return True if any part of [period_start_utc, period_end_utc) falls
    within 0200-0559 local time on any day (§6.2: any part infringes).

    Derived purely from the period's own timestamps and the governing local
    offset — never trusts a caller-supplied flag.
    """
    offset = timedelta(hours=local_offset_hours)
    start_local = _to_utc(period_start_utc) + offset
    end_local = _to_utc(period_end_utc) + offset

    if start_local >= end_local:
        return False

    day = start_local.replace(hour=0, minute=0, second=0, microsecond=0)
    last_day = end_local.replace(hour=0, minute=0, second=0, microsecond=0)

    while day <= last_day:
        window_start = day.replace(hour=_WOCL_START_HOUR)
        window_end = day.replace(hour=_WOCL_END_HOUR)
        if start_local < window_end and end_local > window_start:
            return True
        day += timedelta(days=1)

    return False
