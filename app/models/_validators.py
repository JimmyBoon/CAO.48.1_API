"""
Shared request-model validators.

CAO 48.1 is a compliance instrument: a request the API cannot interpret must be
rejected, never coerced into something that looks plausible. A transposed
start/end in a roster feed is an ordinary integration bug, and before these
validators existed it produced a negative FDP duration that passed validation
("Actual FDP -8.00h <= limit 10.00h"). A silent `% 24` on an out-of-range UTC
offset did the same thing to the time-band lookup.

Every helper here raises ValueError, which Pydantic surfaces as a 422 naming
the offending field.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Union

# Real-world UTC offsets span Baker Island (-12) to Line Islands (+14).
# Fractional offsets are legitimate and must keep working: IST +5.5,
# Eucla +8.75, Chatham +12.75.
UTC_OFFSET_MIN_HOURS = -12.0
UTC_OFFSET_MAX_HOURS = 14.0

# Tolerance when reconciling a supplied duration against its own timestamps.
DURATION_TOLERANCE_MINUTES = 1.0


def validate_utc_offset(value: Optional[float], field_name: str) -> Optional[float]:
    """Reject a UTC offset outside the range of offsets that actually exist."""
    if value is None:
        return value
    if not UTC_OFFSET_MIN_HOURS <= value <= UTC_OFFSET_MAX_HOURS:
        raise ValueError(
            f"{field_name} must be between {UTC_OFFSET_MIN_HOURS:+g} and "
            f"{UTC_OFFSET_MAX_HOURS:+g} hours; got {value:g}. "
            "Out-of-range offsets are rejected rather than wrapped, because a "
            "wrapped offset yields a plausible-looking but incorrect time band."
        )
    return value


def parse_utc(value: Union[str, datetime], field_name: str) -> datetime:
    """Parse an ISO 8601 timestamp to a UTC-aware datetime."""
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                f"{field_name} is not a valid ISO 8601 timestamp: {value!r}"
            ) from exc
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def require_end_after_start(
    start: Union[str, datetime],
    end: Union[str, datetime],
    start_field: str,
    end_field: str,
) -> tuple[datetime, datetime]:
    """Require end strictly after start. Returns the parsed pair."""
    start_dt = parse_utc(start, start_field)
    end_dt = parse_utc(end, end_field)
    if end_dt <= start_dt:
        delta_hours = (end_dt - start_dt).total_seconds() / 3600
        raise ValueError(
            f"{end_field} must be strictly after {start_field}; got "
            f"{start_field}={start_dt.isoformat()} and "
            f"{end_field}={end_dt.isoformat()} "
            f"({delta_hours:+.2f}h). Check for transposed start/end times."
        )
    return start_dt, end_dt


def require_duration_agrees(
    start: Union[str, datetime],
    end: Union[str, datetime],
    duration_hours: Optional[float],
    duration_field: str,
    start_field: str,
    end_field: str,
) -> None:
    """Require a supplied duration to agree with its own timestamps."""
    if duration_hours is None:
        return
    start_dt = parse_utc(start, start_field)
    end_dt = parse_utc(end, end_field)
    elapsed_hours = (end_dt - start_dt).total_seconds() / 3600
    drift_minutes = abs(elapsed_hours - duration_hours) * 60
    if drift_minutes > DURATION_TOLERANCE_MINUTES:
        raise ValueError(
            f"{duration_field} ({duration_hours:g}h) disagrees with "
            f"{end_field} - {start_field} ({elapsed_hours:.4f}h) by "
            f"{drift_minutes:.1f} minutes, which exceeds the "
            f"{DURATION_TOLERANCE_MINUTES:g}-minute tolerance. "
            "Correct whichever is wrong rather than sending both."
        )


def _event_span(event) -> Optional[tuple[datetime, datetime, str]]:
    """Return (start, end, kind) for a sequence/roster event, or None."""
    if getattr(event, "event_type", None) == "fdp":
        return (
            parse_utc(event.fdp_start_utc, "fdp_start_utc"),
            parse_utc(event.fdp_end_utc, "fdp_end_utc"),
            "fdp",
        )
    start = getattr(event, "start_utc", None)
    end = getattr(event, "end_utc", None)
    if start is None or end is None:
        return None
    return (
        parse_utc(start, "start_utc"),
        parse_utc(end, "end_utc"),
        getattr(event, "event_type", "event"),
    )


def require_events_ordered(events: list) -> list:
    """
    Require events to be chronologically ordered and FDPs not to overlap.

    Both engines walk the event list in the order supplied and carry state
    across it (consecutive early starts, WOCL infringements, the preceding
    ODP). An out-of-order list silently produces a wrong answer rather than
    an error, so ordering is a precondition, not a convenience.

    Non-FDP events are permitted to abut and to sit inside one another —
    only overlapping *duty* is a contradiction.
    """
    spans = []
    for index, event in enumerate(events):
        span = _event_span(event)
        if span is not None:
            spans.append((index, *span))

    for position in range(1, len(spans)):
        prev_index, prev_start, prev_end, prev_kind = spans[position - 1]
        index, start, end, kind = spans[position]

        if start < prev_start:
            raise ValueError(
                f"events must be in chronological order: event {index} "
                f"({kind}) starts {start.isoformat()}, before event "
                f"{prev_index} ({prev_kind}) at {prev_start.isoformat()}."
            )

        if kind == "fdp" and prev_kind == "fdp" and start < prev_end:
            raise ValueError(
                f"FDPs must not overlap: event {index} starts "
                f"{start.isoformat()} while event {prev_index} runs until "
                f"{prev_end.isoformat()}."
            )

    return events
