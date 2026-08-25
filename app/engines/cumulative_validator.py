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
    coverage_start: Optional[datetime] = None,
) -> int:
    """
    Count calendar days completely free of duty within the window.

    Counting is clamped to the period the supplied data actually covers. A day
    before the earliest supplied event is not a day off — it is a day about
    which nothing is known, and treating the two alike is what produced
    "26 days off in the previous 28 days" for a 2-day roster with no history.

    Uses UTC days as a proxy when offset data is unavailable.
    """
    effective_start = window_start
    if coverage_start is not None and coverage_start > window_start:
        effective_start = coverage_start

    busy_days: set = set()
    for r in _recs_in_window(recs, effective_start, window_end):
        cursor = r.start.date()
        end_d  = r.end.date()
        while cursor <= end_d:
            busy_days.add(cursor)
            cursor = cursor + timedelta(days=1)

    total_days = (window_end.date() - effective_start.date()).days
    return max(0, total_days - len(busy_days))


def _find_recovery_block(
    recs: list[_Rec],
    min_gap_hours: float,
    min_local_nights: int,
    window_hours: float,
    as_of_utc: datetime,
    coverage_start: Optional[datetime] = None,
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
    # Clamp the scan to the period the data covers. Empty space before the
    # earliest supplied event is not an off-duty block; reporting one there
    # invents a recovery period that may never have happened.
    if coverage_start is not None and coverage_start > window_start:
        window_start = coverage_start
        if as_of_utc - window_start < timedelta(hours=min_gap_hours):
            # Not enough covered time for a qualifying block to fit.
            return False
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
    skip_reason: str = "",
) -> None:
    """
    Append a check result and, when failing, a violation.

    A skipped check is REPORTED, not dropped. Removing it from `checks[]`
    entirely — which is what happened before — leaves a consumer unable to
    tell a condition that passed from one that was never evaluated, and makes
    an incomplete assessment indistinguishable from a clean one.
    """
    if skipped:
        notes.append(f"{check_id}: skipped (data_unavailable)")
        checks.append(
            {
                "check": check_id,
                "passed": None,
                "status": "data_unavailable",
                "clause": clause,
                # `actual` is retained where one was computed: it is a genuine
                # lower bound from the data supplied, and more useful to a
                # caller than a null. `passed: None` is what stops it counting
                # as compliance.
                "actual": actual,
                "limit": limit,
                "detail": skip_reason or (
                    f"{check_id} could not be evaluated from the data supplied. "
                    "This is not a pass."
                ),
            }
        )
        return

    checks.append(
        {
            "check": check_id,
            "passed": passed,
            "status": "passed" if passed else "failed",
            "clause": clause,
            "actual": actual,
            "limit": limit,
            "detail": detail,
        }
    )
    # `passed is False`, not `not passed`: a data_unavailable check
    # carries passed=None, and None is falsy. Treating it as a
    # failure would turn "could not check" into "breached".
    if passed is False:
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

    # ─── Data coverage ────────────────────────────────────────────────
    # A rolling window that reaches back further than the earliest supplied
    # event is being computed over empty space. Counting that space as
    # compliant is how a 2-day roster reported "26 days off in the previous
    # 28 days" and "found a 36h+ off-duty block" where no such block existed.
    #
    # Coverage is decided per window, and the verdict depends on direction:
    #
    #   * Accumulating limits (flight time, duty time) can only RISE with more
    #     data. A total that already breaches is a genuine breach; one that
    #     does not, over an under-covered window, is unknown.
    #   * Minimum requirements (days off, recovery blocks) can only be HELPED
    #     by more data. A requirement already met within covered data is
    #     genuinely met; one not met, over an under-covered window, is unknown.
    #
    # Either way the safe answer for an under-covered window is
    # data_unavailable, never a pass.
    coverage_start = recs[0].start if recs else None

    def _covered(
        window_hours: Optional[float] = None,
        window_days: Optional[float] = None,
        summary_field: Optional[str] = None,
    ) -> bool:
        """True when supplied data spans the whole lookback window."""
        if recs is None:
            # Pre-aggregated totals describe the whole window by construction.
            return summary is not None and _get_summary(summary, summary_field) is not None
        if (
            baseline_summary is not None
            and summary_field is not None
            and _get_summary(baseline_summary, summary_field) is not None
        ):
            # A prior_summary carries the part of the window the log predates.
            return True
        if coverage_start is None:
            return False
        if window_hours is not None:
            window_start = as_of_utc - timedelta(hours=window_hours)
        elif window_days is not None:
            window_start = as_of_utc - timedelta(days=window_days)
        else:
            return False
        return coverage_start <= window_start

    def _shortfall(window_hours=None, window_days=None) -> str:
        """How far the window reaches beyond the supplied data."""
        if coverage_start is None:
            return "no history was supplied"
        if window_hours is not None:
            window_start = as_of_utc - timedelta(hours=window_hours)
        else:
            window_start = as_of_utc - timedelta(days=window_days)
        gap = (coverage_start - window_start).total_seconds() / 3600
        return (
            f"the lookback window begins {gap:.0f} hours before the earliest "
            f"supplied event ({coverage_start.isoformat()})"
        )

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
            clause=ft.period_168h_clause,
            actual=round(val, 2) if val is not None else None,
            limit=ft.period_168h_hours,
            detail=(
                f"{val:.2f}h flight time in the previous 168h (limit {ft.period_168h_hours}h)"
                if val is not None else "Flight time in the previous 168h"
            ),
            remediation=f"Ensure flight time in any 168h does not exceed {ft.period_168h_hours}h.",
            skipped=(
                val is None
                or (val <= ft.period_168h_hours
                    and not _covered(window_hours=168, summary_field="flight_time_168h_hours"))
            ),
            skip_reason=(
                f"flight_time_168h could not be established: {_shortfall(window_hours=168)}. "
                f"The {val:.2f}h computed from supplied data is a lower bound, "
                f"so a breach of the {ft.period_168h_hours}h limit cannot be ruled out."
                if val is not None else
                f"flight_time_168h could not be evaluated: no data for this window."
            ),
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
            clause=ft.period_28d_clause,
            actual=round(val, 2) if val is not None else None,
            limit=ft.period_28d_hours,
            detail=(
                f"{val:.2f}h flight time in the previous 28 days (limit {ft.period_28d_hours}h)"
                if val is not None else "Flight time in the previous 28 days"
            ),
            remediation=f"Ensure flight time in any 28 days does not exceed {ft.period_28d_hours}h.",
            skipped=(
                val is None
                or (val <= ft.period_28d_hours
                    and not _covered(window_days=28, summary_field="flight_time_28d_hours"))
            ),
            skip_reason=(
                f"flight_time_28d could not be established: {_shortfall(window_days=28)}. "
                f"The {val:.2f}h computed from supplied data is a lower bound, "
                f"so a breach of the {ft.period_28d_hours}h limit cannot be ruled out."
                if val is not None else
                f"flight_time_28d could not be evaluated: no data for this window."
            ),
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
            clause=ft.period_90d_clause,
            actual=round(val, 2) if val is not None else None,
            limit=ft.period_90d_hours,
            detail=(
                f"{val:.2f}h flight time in the previous 90 days (limit {ft.period_90d_hours}h)"
                if val is not None else "Flight time in the previous 90 days"
            ),
            remediation=f"Ensure flight time in any 90 days does not exceed {ft.period_90d_hours}h.",
            skipped=(
                val is None
                or (val <= ft.period_90d_hours
                    and not _covered(window_days=90, summary_field="flight_time_90d_hours"))
            ),
            skip_reason=(
                f"flight_time_90d could not be established: {_shortfall(window_days=90)}. "
                f"The {val:.2f}h computed from supplied data is a lower bound, "
                f"so a breach of the {ft.period_90d_hours}h limit cannot be ruled out."
                if val is not None else
                f"flight_time_90d could not be evaluated: no data for this window."
            ),
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
            clause=ft.period_365d_clause,
            actual=round(val, 2) if val is not None else None,
            limit=ft.period_365d_hours,
            detail=(
                f"{val:.2f}h flight time in the previous 365 days (limit {ft.period_365d_hours}h)"
                if val is not None else "Flight time in the previous 365 days"
            ),
            remediation=f"Ensure flight time in any 365 days does not exceed {ft.period_365d_hours}h.",
            skipped=(
                val is None
                or (val <= ft.period_365d_hours
                    and not _covered(window_days=365, summary_field="flight_time_365d_hours"))
            ),
            skip_reason=(
                f"flight_time_365d could not be established: {_shortfall(window_days=365)}. "
                f"The {val:.2f}h computed from supplied data is a lower bound, "
                f"so a breach of the {ft.period_365d_hours}h limit cannot be ruled out."
                if val is not None else
                f"flight_time_365d could not be evaluated: no data for this window."
            ),
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
            clause=ft.period_384h_clause,
            actual=round(val, 2) if val is not None else None,
            limit=ft.period_384h_hours,
            detail=(
                f"{val:.2f}h flight time in the previous 384h (limit {ft.period_384h_hours}h)"
                if val is not None else "Flight time in the previous 384h"
            ),
            remediation=f"Ensure flight time in any 384h does not exceed {ft.period_384h_hours}h.",
            skipped=(
                val is None
                or (val <= ft.period_384h_hours
                    and not _covered(window_hours=384, summary_field="flight_time_384h_hours"))
            ),
            skip_reason=(
                f"flight_time_384h could not be established: {_shortfall(window_hours=384)}. "
                f"The {val:.2f}h computed from supplied data is a lower bound, "
                f"so a breach of the {ft.period_384h_hours}h limit cannot be ruled out."
                if val is not None else
                f"flight_time_384h could not be evaluated: no data for this window."
            ),
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
            clause=dt.period_168h_clause,
            actual=round(val, 2) if val is not None else None,
            limit=dt.period_168h_hours,
            detail=(
                f"{val:.2f}h duty time in the previous 168h (limit {dt.period_168h_hours}h)"
                if val is not None else "Duty time in the previous 168h"
            ),
            remediation=f"Ensure duty time in any 168h does not exceed {dt.period_168h_hours}h.",
            skipped=(
                val is None
                or (val <= dt.period_168h_hours
                    and not _covered(window_hours=168, summary_field="duty_time_168h_hours"))
            ),
            skip_reason=(
                f"duty_time_168h could not be established: {_shortfall(window_hours=168)}. "
                f"The {val:.2f}h computed from supplied data is a lower bound, "
                f"so a breach of the {dt.period_168h_hours}h limit cannot be ruled out."
                if val is not None else
                f"duty_time_168h could not be evaluated: no data for this window."
            ),
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
            clause=dt.period_336h_clause,
            actual=round(val, 2) if val is not None else None,
            limit=dt.period_336h_hours,
            detail=(
                f"{val:.2f}h duty time in the previous 336h (limit {dt.period_336h_hours}h)"
                if val is not None else "Duty time in the previous 336h"
            ),
            remediation=f"Ensure duty time in any 336h does not exceed {dt.period_336h_hours}h.",
            skipped=(
                val is None
                or (val <= dt.period_336h_hours
                    and not _covered(window_hours=336, summary_field="duty_time_336h_hours"))
            ),
            skip_reason=(
                f"duty_time_336h could not be established: {_shortfall(window_hours=336)}. "
                f"The {val:.2f}h computed from supplied data is a lower bound, "
                f"so a breach of the {dt.period_336h_hours}h limit cannot be ruled out."
                if val is not None else
                f"duty_time_336h could not be evaluated: no data for this window."
            ),
        )

    # ── Recovery block checks ─────────────────────────────────────────

    caller_must_verify: list[dict] = []

    if rec.period_168h_min_hours and rec.period_168h_min_hours > 0 and rec.period_168h_trigger:
        # Conditional requirement — the trigger is not visible to this API.
        caller_must_verify.append({
            "clause": rec.period_168h_clause,
            "description": (
                f"If {rec.period_168h_trigger}, the FCM must have an off-duty "
                f"period of at least {rec.period_168h_min_hours:.0f} consecutive "
                f"hours including {rec.period_168h_local_nights} local nights "
                f"during that period."
            ),
        })
        notes.append(
            f"{rec.period_168h_clause} is conditional on a trigger this API "
            f"cannot see; surfaced for the caller to verify rather than "
            f"asserted as a check."
        )
    elif rec.period_168h_min_hours and rec.period_168h_min_hours > 0:
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
                coverage_start=coverage_start,
            )
        else:
            result = _get_summary(summary, "recovery_36h_block_in_168h")

        clause = rec.period_168h_clause
        _add_check(
            checks, violations, notes,
            check_id="recovery_36h_2ln_in_168h",
            passed=result is True,
            clause=clause,
            actual=None,
            limit=None,
            detail=(
                f"{'Found' if result is True else 'Missing'} required 36h+ off-duty block "
                f"with 2 local nights in the previous 168h ({clause})."
            ),
            remediation=(
                "Ensure at least one 36h+ continuous off-duty period including "
                "2 local nights occurs in any 168h window before the next FDP."
            ),
            skipped=(
                result is None
                or (result is not True
                    and not _covered(window_hours=168, summary_field="recovery_36h_block_in_168h"))
            ),
            skip_reason=(
                f"recovery_36h_2ln_in_168h could not be established: "
                f"{_shortfall(window_hours=168)}. No qualifying 36h+ off-duty block with 2 local nights was found in "
                f"the data supplied, but the window is not fully covered, so "
                f"its absence cannot be confirmed."
            ),
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
                coverage_start=coverage_start,
            )
        else:
            result = _get_summary(summary, "recovery_36h_block_in_336h")

        _add_check(
            checks, violations, notes,
            check_id="recovery_36h_2ln_in_336h",
            passed=result is True,
            clause=rec.period_336h_clause,
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
            skipped=(
                result is None
                or (result is not True
                    and not _covered(window_hours=336, summary_field="recovery_36h_block_in_336h"))
            ),
            skip_reason=(
                f"recovery_36h_2ln_in_336h could not be established: "
                f"{_shortfall(window_hours=336)}. No qualifying off-duty block was found in "
                f"the data supplied, but the window is not fully covered, so "
                f"its absence cannot be confirmed."
            ),
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
                coverage_start=coverage_start,
            )
        else:
            result = _get_summary(summary, "recovery_72h_block_in_504h")

        _add_check(
            checks, violations, notes,
            check_id="recovery_72h_3ln_in_504h",
            passed=result is True,
            clause=rec.period_504h_clause,
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
            skipped=(
                result is None
                or (result is not True
                    and not _covered(window_hours=504, summary_field="recovery_72h_block_in_504h"))
            ),
            skip_reason=(
                f"recovery_72h_3ln_in_504h could not be established: "
                f"{_shortfall(window_hours=504)}. No qualifying off-duty block was found in "
                f"the data supplied, but the window is not fully covered, so "
                f"its absence cannot be confirmed."
            ),
        )

    # ── "At least 1 of the following" recovery alternatives ───────────
    # App 4B §5.4 and App 5 §5.2 each offer two limbs and require only one.
    # Evaluating them as two independent mandatory checks raises a violation
    # the instrument does not support.
    if rec.alternative_336h_504h:
        pair = [
            c for c in checks
            if c["check"] in ("recovery_36h_2ln_in_336h", "recovery_72h_3ln_in_504h")
        ]
        if any(c["status"] == "passed" for c in pair):
            names = {c["check"] for c in pair if c["status"] != "passed"}
            for c in pair:
                if c["status"] != "passed":
                    c["status"] = "passed"
                    c["passed"] = True
                    c["detail"] = (
                        (c["detail"] or "")
                        + f" Requirement discharged by the alternative limb: "
                          f"{rec.period_336h_clause} / {rec.period_504h_clause} "
                          f"requires at least 1 of the two, and the other is met."
                    )
            if names:
                violations[:] = [v for v in violations if v["check"] not in names]
                notes.append(
                    f"{rec.period_336h_clause} / {rec.period_504h_clause}: "
                    f"at least 1 of the two limbs is satisfied, which "
                    f"discharges the requirement."
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
            actual_days_off = _count_days_off(recs, ws, as_of_utc, coverage_start)
        else:
            actual_days_off = _get_summary(summary, "days_off_in_28d")

        _add_check(
            checks, violations, notes,
            check_id="days_off_in_28d",
            passed=actual_days_off is not None and actual_days_off >= rec.period_28d_days_off,
clause=rec.period_28d_days_off_clause,
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
            skipped=(
                actual_days_off is None
                or (actual_days_off < rec.period_28d_days_off
                    and not _covered(window_days=28, summary_field="days_off_in_28d"))
            ),
            skip_reason=(
                f"days_off_in_28d could not be established: {_shortfall(window_days=28)}. "
                f"Only {actual_days_off} day(s) off are visible in the "
                f"supplied data against a requirement of {rec.period_28d_days_off}; days "
                f"before the earliest supplied event are unknown and are not "
                f"counted as days off."
                if actual_days_off is not None else
                f"days_off_in_28d could not be evaluated: no data for this window."
            ),
        )

    if rec.period_384h_days_off is not None:
        prior = _get_summary(baseline_summary, "days_off_in_384h")
        if prior is not None:
            actual_days_off = prior
        elif recs is not None:
            ws = as_of_utc - timedelta(hours=384)
            actual_days_off = _count_days_off(recs, ws, as_of_utc, coverage_start)
        else:
            actual_days_off = _get_summary(summary, "days_off_in_384h")

        _add_check(
            checks, violations, notes,
            check_id="days_off_in_384h",
            passed=actual_days_off is not None and actual_days_off >= rec.period_384h_days_off,
            clause=rec.period_384h_days_off_clause,
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
            skipped=(
                actual_days_off is None
                or (actual_days_off < rec.period_384h_days_off
                    and not _covered(window_hours=384, summary_field="days_off_in_384h"))
            ),
            skip_reason=(
                f"days_off_in_384h could not be established: {_shortfall(window_hours=384)}. "
                f"Only {actual_days_off} day(s) off are visible in the "
                f"supplied data against a requirement of {rec.period_384h_days_off}; days "
                f"before the earliest supplied event are unknown and are not "
                f"counted as days off."
                if actual_days_off is not None else
                f"days_off_in_384h could not be evaluated: no data for this window."
            ),
        )

    skipped = [c for c in checks if c.get("status") == "data_unavailable"]
    warnings: list[str] = []
    if skipped:
        warnings.append(
            "Not a complete assessment: "
            + ", ".join(c["check"] for c in skipped)
            + " could not be established from the data supplied. Supply a "
              "prior_fdp_log covering the full lookback window, or a "
              "prior_summary, to resolve them."
        )

    return {
        # `valid` tracks violations only. A skipped check means the assessment
        # is incomplete, not that something is wrong — and validating a roster
        # without prior history is an ordinary thing to do, so flagging it as
        # invalid would cry wolf on the common case. Incompleteness is carried
        # by checks_skipped and the accompanying warning; a caller who needs a
        # complete assessment reads those.
        "valid": len(violations) == 0,
        "appendix": appendix,
        "checks_run": len(checks) - len(skipped),
        "checks_skipped": len(skipped),
        "violations": violations,
        "checks": checks,
        "warnings": warnings,
        "calculation_notes": notes,
    }
