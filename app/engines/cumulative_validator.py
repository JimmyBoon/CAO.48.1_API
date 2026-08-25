"""
cumulative_validator.py — Rolling-window cumulative limit checks.

Validates flight time, duty time, and recovery requirements against the
per-appendix limits defined in cumulative_limits.py.

Accepts either:
  - A raw FDP history log (preferred): API computes all rolling windows.
  - Pre-aggregated summary totals (fallback): used when full history is
    not available.

Appendix 5/5A reset rule: flight time accumulation resets to zero after
5+ consecutive days off. The API detects this from the log automatically.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.data.cumulative_limits import CUMULATIVE_CONFIGS, CumulativeLimitsConfig


def _get_summary(summary, field: str, default=None):
    """Read a field from either a Pydantic model or a plain dict."""
    if summary is None:
        return default
    if isinstance(summary, dict):
        return summary.get(field, default)
    return getattr(summary, field, default)


# ─── Local-night definition ───────────────────────────────────────────
# CAO 48.1 §(definition): a period of 8 consecutive hours that includes
# the period 0100–0559 local time.  We use a simple proxy: an off-duty
# gap that contains any minute between 0100 and 0559 local counts.

_LOCAL_NIGHT_START_HOUR = 1   # 0100
_LOCAL_NIGHT_END_HOUR   = 6   # exclusive upper bound (0559)


def _contains_local_night(
    period_start_utc: datetime,
    period_end_utc: datetime,
    local_offset_hours: float,
) -> bool:
    """Return True if the gap contains any part of 0100–0559 local time."""
    # Walk hourly through the gap and check for local night hours.
    # Gap can be many hours, so we scan at 15-min resolution.
    offset = timedelta(hours=local_offset_hours)
    cursor = period_start_utc
    while cursor < period_end_utc:
        local_hour = (cursor + offset).hour
        if _LOCAL_NIGHT_START_HOUR <= local_hour < _LOCAL_NIGHT_END_HOUR:
            return True
        cursor += timedelta(minutes=15)
    return False


def _count_local_nights_in_gap(
    gap_start_utc: datetime,
    gap_end_utc: datetime,
    local_offset_hours: float,
) -> int:
    """Count how many distinct local nights (0100–0559 windows) the gap passes through."""
    offset = timedelta(hours=local_offset_hours)
    nights: set[int] = set()
    cursor = gap_start_utc
    while cursor < gap_end_utc:
        local = cursor + offset
        if _LOCAL_NIGHT_START_HOUR <= local.hour < _LOCAL_NIGHT_END_HOUR:
            # Key by date + hour to count distinct nights
            nights.add((local.date(), local.hour // (_LOCAL_NIGHT_END_HOUR - _LOCAL_NIGHT_START_HOUR)))
        cursor += timedelta(minutes=15)
    return len(nights)


# ─── Internal record type (mirrors FdpHistoryRecord fields) ───────────

class _Rec:
    __slots__ = ("start", "end", "flight", "duty", "offset")

    def __init__(
        self,
        start: datetime,
        end: datetime,
        flight: float,
        duty: float,
        offset: Optional[float],
    ) -> None:
        self.start = start
        self.end = end
        self.flight = flight
        self.duty = duty
        self.offset = offset  # None means timezone unknown


def _to_utc(dt: datetime) -> datetime:
    """Ensure datetime is UTC-aware; assume UTC if naive."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _make_records(fdp_log: list) -> list[_Rec]:
    """Convert Pydantic FdpHistoryRecord objects (or dicts) to internal _Rec."""
    recs = []
    for r in fdp_log:
        if hasattr(r, "fdp_start_utc"):
            start = _to_utc(r.fdp_start_utc)
            end   = _to_utc(r.fdp_end_utc)
            flight = r.actual_flight_time_hours
            duty   = r.actual_duty_time_hours
            offset = r.local_time_offset_hours
        else:
            start  = _to_utc(r["fdp_start_utc"])
            end    = _to_utc(r["fdp_end_utc"])
            flight = r["actual_flight_time_hours"]
            duty   = r["actual_duty_time_hours"]
            offset = r.get("local_time_offset_hours")
        recs.append(_Rec(start, end, flight, duty, offset))
    recs.sort(key=lambda r: r.start)
    return recs


# ─── Appendix 5/5A reset detection ───────────────────────────────────

def _detect_app5_reset(
    recs: list[_Rec],
    reset_days: int = 5,
) -> Optional[datetime]:
    """
    Return the start of the most recent post-reset FDP, or None if no
    5+-day gap is found.  Flight time before the reset is excluded.
    """
    if len(recs) < 2:
        return None
    threshold = timedelta(days=reset_days)
    cutoff: Optional[datetime] = None
    for i in range(len(recs) - 1, 0, -1):
        gap = recs[i].start - recs[i - 1].end
        if gap >= threshold:
            cutoff = recs[i].start
            break
    return cutoff


# ─── Window helpers ───────────────────────────────────────────────────

def _recs_in_window(
    recs: list[_Rec],
    window_start: datetime,
    window_end: datetime,
) -> list[_Rec]:
    """Return FDPs that overlap the [window_start, window_end) interval."""
    return [r for r in recs if r.start < window_end and r.end > window_start]


def _sum_flight(recs: list[_Rec]) -> float:
    return sum(r.flight for r in recs)


def _sum_duty(recs: list[_Rec]) -> float:
    return sum(r.duty for r in recs)


def _count_days_off(
    recs: list[_Rec],
    window_start: datetime,
    window_end: datetime,
) -> int:
    """
    Count calendar days (local midnight boundaries) completely free of duty
    within [window_start, window_end).  Uses UTC days as proxy when offset
    data is unavailable.
    """
    busy_days: set = set()
    for r in _recs_in_window(recs, window_start, window_end):
        cursor = r.start.date()
        end_d  = r.end.date()
        while cursor <= end_d:
            busy_days.add(cursor)
            cursor = cursor + timedelta(days=1)

    total_days = (window_end.date() - window_start.date()).days
    return max(0, total_days - len(busy_days))


def _find_recovery_block(
    recs: list[_Rec],
    min_gap_hours: float,
    min_local_nights: int,
    window_hours: float,
    as_of_utc: datetime,
) -> Optional[bool]:
    """
    Scan for a continuous off-duty gap >= min_gap_hours that contains at
    least min_local_nights local nights, within the preceding window_hours.

    Returns:
      True  — qualifying block found
      False — no qualifying block found
      None  — timezone data missing; cannot evaluate local-night requirement
    """
    window_start = as_of_utc - timedelta(hours=window_hours)
    gaps_in_window = _recs_in_window(recs, window_start, as_of_utc)

    # Build gap list: bookend with window bounds
    boundary_points = [(window_start, None), (as_of_utc, None)]
    for r in gaps_in_window:
        boundary_points.append((r.start, "start"))
        boundary_points.append((r.end, "end"))
    boundary_points.sort(key=lambda x: x[0])

    # Collect free intervals
    min_gap = timedelta(hours=min_gap_hours)
    in_duty = False
    last_free_start: Optional[datetime] = None
    gaps: list[tuple[datetime, datetime]] = []

    for t, kind in boundary_points:
        if kind == "start":
            if not in_duty and last_free_start is not None:
                if t - last_free_start >= min_gap:
                    gaps.append((last_free_start, t))
            in_duty = True
            last_free_start = None
        elif kind == "end":
            in_duty = False
            last_free_start = t
        else:
            # window boundary point
            if not in_duty:
                last_free_start = last_free_start or t

    if last_free_start is not None and not in_duty:
        end = as_of_utc
        if end - last_free_start >= min_gap:
            gaps.append((last_free_start, end))

    if min_local_nights == 0:
        return len(gaps) > 0

    # Need timezone data to count local nights
    # Check if any record in the window has an offset
    offsets = [r.offset for r in gaps_in_window if r.offset is not None]
    if not offsets and min_local_nights > 0:
        # Can't verify — treat as unknown
        return None

    offset_used = offsets[0] if offsets else 0.0

    for gap_start, gap_end in gaps:
        nights = _count_local_nights_in_gap(gap_start, gap_end, offset_used)
        if nights >= min_local_nights:
            return True

    return False


# ─── Check builder (same pattern as fdp_validator.py ) ───────────────

def _add_check(
    checks: list,
    violations: list,
    notes: list,
    check_id: str,
    passed: bool,
    clause: str,
    actual: Optional[float],
    limit: Optional[float],
    detail: str,
    severity: str = "hard_limit",
    remediation: str = "",
    skipped: bool = False,
) -> None:
    """Append a check result and, when failing, a violation."""
    if skipped:
        notes.append(f"{check_id}: skipped (data_unavailable)")
        return

    checks.append(
        {
            "check": check_id,
            "passed": passed,
            "clause": clause,
            "actual": actual,
            "limit": limit,
            "detail": detail,
        }
    )
    if not passed:
        if not remediation:
            remediation = f"Ensure {check_id} does not exceed {limit}."
        violations.append(
            {
                "check": check_id,
                "clause": clause,
                "severity": severity,
                "actual": actual,
                "limit": limit,
                "detail": detail,
                "remediation": remediation,
            }
        )


# ─── Public API ───────────────────────────────────────────────────────

def validate_cumulative(
    appendix: str,
    as_of_utc: datetime,
    fdp_log: Optional[list] = None,
    summary=None,
    baseline_summary=None,
) -> dict:
    """
    Validate cumulative flight time, duty time, and recovery requirements.

    Parameters
    ----------
    appendix : str
        CAO 48.1 appendix identifier.
    as_of_utc : datetime
        Point in time to evaluate limits against (usually next FDP start).
    fdp_log : list of FdpHistoryRecord, optional
        Full FDP history (preferred). Computes all rolling windows.
    summary : CumulativeSummaryInput, optional
        Pre-aggregated totals (fallback when log not available). Used only
        when ``fdp_log`` is absent.
    baseline_summary : CumulativeSummaryInput, optional
        Pre-aggregated totals for history *preceding* the supplied log,
        combined with the log-derived figures rather than replacing them.
        Hour-based windows are additive (prior + computed). Days-off counts
        and recovery-block booleans are assertions about the whole window,
        so the caller's value is authoritative for those and the log-derived
        figure is not used — the API cannot see the period the caller is
        describing, and treating its own empty-space figure as better data
        is how S9 under-reports.

    Returns
    -------
    dict
        Matches ValidationResponse shape.
    """
    appendix = appendix.upper()
    config: Optional[CumulativeLimitsConfig] = CUMULATIVE_CONFIGS.get(appendix)
    if config is None:
        raise ValueError(f"Unknown appendix: {appendix!r}")

    as_of_utc = _to_utc(as_of_utc)

    checks: list = []
    violations: list = []
    notes: list = []

    # ── Prepare records ───────────────────────────────────────────────
    recs: Optional[list[_Rec]] = None
    if fdp_log is not None:
        recs = _make_records(fdp_log)
        # Apply App 5/5A reset: truncate history before a 5-day gap
        if appendix in {"5", "5A"} and config.flight_time.reset_after_days_off:
            cutoff = _detect_app5_reset(
                recs, reset_days=config.flight_time.reset_after_days_off
            )
            if cutoff:
                recs = [r for r in recs if r.start >= cutoff]
                notes.append(
                    f"App {appendix}: flight time accumulation reset detected "
                    f"(≥{config.flight_time.reset_after_days_off} consecutive days off). "
                    f"Only FDPs from {cutoff.date()} onwards included."
                )

    ft = config.flight_time
    dt = config.duty_time
    rec = config.recovery

    # Helper: get a value from recs (plus any prior baseline) or from summary
    def _from_log_or_summary(
        window_hours: Optional[float],
        window_days: Optional[float],
        agg_fn,
        summary_field_name: str,
        label: str,
    ) -> Optional[float]:
        if recs is not None:
            if window_hours is not None:
                ws = as_of_utc - timedelta(hours=window_hours)
            elif window_days is not None:
                ws = as_of_utc - timedelta(days=window_days)
            else:
                return None
            computed = agg_fn(_recs_in_window(recs, ws, as_of_utc))
            prior = _get_summary(baseline_summary, summary_field_name)
            if prior is not None:
                notes.append(
                    f"{label}: {computed:.2f}h from supplied events + "
                    f"{prior:.2f}h carried from prior_summary = {computed + prior:.2f}h."
                )
                return computed + prior
            return computed
        if summary is not None:
            val = _get_summary(summary, summary_field_name)
            if val is not None:
                return val
        return None  # unavailable

    def _assertion_from_summary(field_name: str):
        """
        Read a whole-window assertion (days-off count, recovery boolean) from
        whichever summary applies. A baseline value is authoritative: it
        describes a window the supplied events do not cover.
        """
        for src in (baseline_summary, summary):
            if src is not None:
                val = _get_summary(src, field_name)
                if val is not None:
                    return val
        return None

    # ── Flight time checks ────────────────────────────────────────────

    if ft.period_168h_hours is not None:
        val = _from_log_or_summary(
            168, None, _sum_flight,
            "flight_time_168h_hours",
            "168h",
        )
        _add_check(
            checks, violations, notes,
            check_id="flight_time_168h",
            passed=val is not None and val <= ft.period_168h_hours,
            clause="§6.1",
            actual=round(val, 2) if val is not None else None,
            limit=ft.period_168h_hours,
            detail=(
                f"{val:.2f}h flight time in the previous 168h (limit {ft.period_168h_hours}h)"
                if val is not None else "Flight time in the previous 168h"
            ),
            remediation=f"Ensure flight time in any 168h does not exceed {ft.period_168h_hours}h.",
            skipped=val is None,
        )

    if ft.period_28d_hours is not None:
        val = _from_log_or_summary(
            None, 28, _sum_flight,
            "flight_time_28d_hours",
            "28d",
        )
        _add_check(
            checks, violations, notes,
            check_id="flight_time_28d",
            passed=val is not None and val <= ft.period_28d_hours,
            clause="§5.1" if appendix == "1" else "§11.1",
            actual=round(val, 2) if val is not None else None,
            limit=ft.period_28d_hours,
            detail=(
                f"{val:.2f}h flight time in the previous 28 days (limit {ft.period_28d_hours}h)"
                if val is not None else "Flight time in the previous 28 days"
            ),
            remediation=f"Ensure flight time in any 28 days does not exceed {ft.period_28d_hours}h.",
            skipped=val is None,
        )

    if ft.period_90d_hours is not None:
        val = _from_log_or_summary(
            None, 90, _sum_flight,
            "flight_time_90d_hours",
            "90d",
        )
        _add_check(
            checks, violations, notes,
            check_id="flight_time_90d",
            passed=val is not None and val <= ft.period_90d_hours,
            clause="§6.3",
            actual=round(val, 2) if val is not None else None,
            limit=ft.period_90d_hours,
            detail=(
                f"{val:.2f}h flight time in the previous 90 days (limit {ft.period_90d_hours}h)"
                if val is not None else "Flight time in the previous 90 days"
            ),
            remediation=f"Ensure flight time in any 90 days does not exceed {ft.period_90d_hours}h.",
            skipped=val is None,
        )

    if ft.period_365d_hours is not None:
        val = _from_log_or_summary(
            None, 365, _sum_flight,
            "flight_time_365d_hours",
            "365d",
        )
        _add_check(
            checks, violations, notes,
            check_id="flight_time_365d",
            passed=val is not None and val <= ft.period_365d_hours,
            clause="§5.2" if appendix == "1" else "§11.2",
            actual=round(val, 2) if val is not None else None,
            limit=ft.period_365d_hours,
            detail=(
                f"{val:.2f}h flight time in the previous 365 days (limit {ft.period_365d_hours}h)"
                if val is not None else "Flight time in the previous 365 days"
            ),
            remediation=f"Ensure flight time in any 365 days does not exceed {ft.period_365d_hours}h.",
            skipped=val is None,
        )

    if ft.period_384h_hours is not None:
        val = _from_log_or_summary(
            384, None, _sum_flight,
            "flight_time_384h_hours",
            "384h",
        )
        _add_check(
            checks, violations, notes,
            check_id="flight_time_384h",
            passed=val is not None and val <= ft.period_384h_hours,
            clause="§5.1",
            actual=round(val, 2) if val is not None else None,
            limit=ft.period_384h_hours,
            detail=(
                f"{val:.2f}h flight time in the previous 384h (limit {ft.period_384h_hours}h)"
                if val is not None else "Flight time in the previous 384h"
            ),
            remediation=f"Ensure flight time in any 384h does not exceed {ft.period_384h_hours}h.",
            skipped=val is None,
        )

    # ── Duty time checks ──────────────────────────────────────────────

    if dt.period_168h_hours is not None:
        val = _from_log_or_summary(
            168, None, _sum_duty,
            "duty_time_168h_hours",
            "168h",
        )
        _add_check(
            checks, violations, notes,
            check_id="duty_time_168h",
            passed=val is not None and val <= dt.period_168h_hours,
            clause="§10.1" if appendix in {"3", "4", "4B", "6"} else "§12.1",
            actual=round(val, 2) if val is not None else None,
            limit=dt.period_168h_hours,
            detail=(
                f"{val:.2f}h duty time in the previous 168h (limit {dt.period_168h_hours}h)"
                if val is not None else "Duty time in the previous 168h"
            ),
            remediation=f"Ensure duty time in any 168h does not exceed {dt.period_168h_hours}h.",
            skipped=val is None,
        )

    if dt.period_336h_hours is not None:
        val = _from_log_or_summary(
            336, None, _sum_duty,
            "duty_time_336h_hours",
            "336h",
        )
        _add_check(
            checks, violations, notes,
            check_id="duty_time_336h",
            passed=val is not None and val <= dt.period_336h_hours,
            clause="§10.2" if appendix in {"3", "4", "4B", "6"} else "§12.2",
            actual=round(val, 2) if val is not None else None,
            limit=dt.period_336h_hours,
            detail=(
                f"{val:.2f}h duty time in the previous 336h (limit {dt.period_336h_hours}h)"
                if val is not None else "Duty time in the previous 336h"
            ),
            remediation=f"Ensure duty time in any 336h does not exceed {dt.period_336h_hours}h.",
            skipped=val is None,
        )

    # ── Recovery block checks ─────────────────────────────────────────

    if rec.period_168h_min_hours and rec.period_168h_min_hours > 0:
        prior = _get_summary(baseline_summary, "recovery_36h_block_in_168h")
        if prior is not None:
            result = prior
            notes.append(
                "recovery_36h_2ln_in_168h: taken from prior_summary "
                f"({prior}) rather than derived from supplied events."
            )
        elif recs is not None:
            result = _find_recovery_block(
                recs,
                min_gap_hours=rec.period_168h_min_hours,
                min_local_nights=rec.period_168h_local_nights,
                window_hours=168,
                as_of_utc=as_of_utc,
            )
        else:
            result = _get_summary(summary, "recovery_36h_block_in_168h")

        clause = "§4.1a" if appendix == "1" else "§10.5a"
        _add_check(
            checks, violations, notes,
            check_id="recovery_36h_2ln_in_168h",
            passed=result is True,
            clause=clause,
            actual=None,
            limit=None,
            detail=(
                f"{'Found' if result is True else 'Missing'} required 36h+ off-duty block "
                f"with 2 local nights in the previous 168h (§{clause})."
            ),
            remediation=(
                "Ensure at least one 36h+ continuous off-duty period including "
                "2 local nights occurs in any 168h window before the next FDP."
            ),
            skipped=result is None,
        )

    if rec.period_336h_min_hours is not None:
        prior = _get_summary(baseline_summary, "recovery_36h_block_in_336h")
        if prior is not None:
            result = prior
        elif recs is not None:
            result = _find_recovery_block(
                recs,
                min_gap_hours=rec.period_336h_min_hours,
                min_local_nights=rec.period_336h_local_nights or 0,
                window_hours=336,
                as_of_utc=as_of_utc,
            )
        else:
            result = _get_summary(summary, "recovery_36h_block_in_336h")

        _add_check(
            checks, violations, notes,
            check_id="recovery_36h_2ln_in_336h",
            passed=result is True,
            clause="§5.3a",
            actual=None,
            limit=None,
            detail=(
                f"{'Found' if result is True else 'Missing'} required "
                f"{rec.period_336h_min_hours:.0f}h+ off-duty block "
                f"with {rec.period_336h_local_nights or 0} local nights in the previous 336h."
            ),
            remediation=(
                f"Ensure at least one {rec.period_336h_min_hours:.0f}h+ continuous off-duty "
                f"period including {rec.period_336h_local_nights or 0} local nights occurs "
                "in any 336h window."
            ),
            skipped=result is None,
        )

    if rec.period_504h_min_hours is not None:
        prior = _get_summary(baseline_summary, "recovery_72h_block_in_504h")
        if prior is not None:
            result = prior
        elif recs is not None:
            result = _find_recovery_block(
                recs,
                min_gap_hours=rec.period_504h_min_hours,
                min_local_nights=rec.period_504h_local_nights or 0,
                window_hours=504,
                as_of_utc=as_of_utc,
            )
        else:
            result = _get_summary(summary, "recovery_72h_block_in_504h")

        _add_check(
            checks, violations, notes,
            check_id="recovery_72h_3ln_in_504h",
            passed=result is True,
            clause="§5.4",
            actual=None,
            limit=None,
            detail=(
                f"{'Found' if result is True else 'Missing'} required "
                f"{rec.period_504h_min_hours:.0f}h+ off-duty block "
                f"with {rec.period_504h_local_nights or 0} local nights in the previous 504h."
            ),
            remediation=(
                f"Ensure at least one {rec.period_504h_min_hours:.0f}h+ continuous off-duty "
                f"period including {rec.period_504h_local_nights or 0} local nights occurs "
                "in any 504h window."
            ),
            skipped=result is None,
        )

    # ── Days off checks ───────────────────────────────────────────────

    if rec.period_28d_days_off is not None:
        prior = _get_summary(baseline_summary, "days_off_in_28d")
        if prior is not None:
            actual_days_off = prior
            notes.append(
                f"days_off_in_28d: taken from prior_summary ({prior}) rather "
                "than derived from supplied events."
            )
        elif recs is not None:
            ws = as_of_utc - timedelta(days=28)
            actual_days_off = _count_days_off(recs, ws, as_of_utc)
        else:
            actual_days_off = _get_summary(summary, "days_off_in_28d")

        _add_check(
            checks, violations, notes,
            check_id="days_off_in_28d",
            passed=actual_days_off is not None and actual_days_off >= rec.period_28d_days_off,
            clause="§4.1b" if appendix == "1" else "§10.5b",
            actual=float(actual_days_off) if actual_days_off is not None else None,
            limit=float(rec.period_28d_days_off),
            detail=(
                f"{actual_days_off} days off in the previous 28 days "
                f"(minimum {rec.period_28d_days_off} required)"
                if actual_days_off is not None else
                "Days off in the previous 28 days"
            ),
            remediation=(
                f"Ensure at least {rec.period_28d_days_off} days off occur in any rolling "
                "28-day window before the next FDP."
            ),
            skipped=actual_days_off is None,
        )

    if rec.period_384h_days_off is not None:
        prior = _get_summary(baseline_summary, "days_off_in_384h")
        if prior is not None:
            actual_days_off = prior
        elif recs is not None:
            ws = as_of_utc - timedelta(hours=384)
            actual_days_off = _count_days_off(recs, ws, as_of_utc)
        else:
            actual_days_off = _get_summary(summary, "days_off_in_384h")

        _add_check(
            checks, violations, notes,
            check_id="days_off_in_384h",
            passed=actual_days_off is not None and actual_days_off >= rec.period_384h_days_off,
            clause="§5.1",
            actual=float(actual_days_off) if actual_days_off is not None else None,
            limit=float(rec.period_384h_days_off),
            detail=(
                f"{actual_days_off} days off in the previous 384h "
                f"(minimum {rec.period_384h_days_off} required)"
                if actual_days_off is not None else
                "Days off in the previous 384h"
            ),
            remediation=(
                f"Ensure at least {rec.period_384h_days_off} full days off occur in any "
                "384h (16-day) window."
            ),
            skipped=actual_days_off is None,
        )

    return {
        "valid": len(violations) == 0,
        "appendix": appendix,
        "violations": violations,
        "checks": checks,
        "warnings": [],
        "calculation_notes": notes,
    }
