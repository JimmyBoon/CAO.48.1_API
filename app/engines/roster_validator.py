"""
roster_validator.py — Validate a full ordered roster of FDP, off-duty, and rest-day events.

Processes events in chronological order maintaining state for:
  - Consecutive early starts (§13.x)
  - Consecutive WOCL infringements (§13.2)
  - Days-off accumulation

Validates each FDP and each off-duty period individually, tracks sequence-level
checks (§13.2 WOCL guard, consecutive early-start reductions), then runs a
cumulative check across all FDPs combined with any prior-history log.

Returns a structured response with per-FDP results, per-ODP results,
sequence-level checks, cumulative results, and a flat all_violations list.

All logic derived from CAO 48.1 Instrument 2019 (Compilation No. 3, F2021C01239).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.engines.cumulative_validator import validate_cumulative
from app.engines.fdp_validator import validate_fdp
from app.engines.off_duty_validator import validate_off_duty
from app.data.cumulative_limits import CUMULATIVE_CONFIGS


# ─── Early-start window ──────────────────────────────────────────────
_EARLY_START_MIN_HHMM = 500   # 0500
_EARLY_START_MAX_HHMM = 659   # 0659

# Appendices with WOCL/consecutive-start rules
_WOCL_APPENDICES = {"2", "3", "4", "4B", "5", "5A", "6"}


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_iso(dt: datetime) -> str:
    dt = _to_utc(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _local_hhmm(utc_dt: datetime, offset_hours: float) -> int:
    local_dt = _to_utc(utc_dt) + timedelta(hours=offset_hours)
    return local_dt.hour * 100 + local_dt.minute


def _is_early_start(fdp_start_utc: datetime, local_offset_hours: float) -> bool:
    hhmm = _local_hhmm(fdp_start_utc, local_offset_hours)
    return _EARLY_START_MIN_HHMM <= hhmm <= _EARLY_START_MAX_HHMM


def _get(event: Any, attr: str, default=None):
    """Access an attribute from a Pydantic model or a plain dict."""
    if hasattr(event, attr):
        return getattr(event, attr)
    if isinstance(event, dict):
        return event.get(attr, default)
    return default


# ─── Public API ───────────────────────────────────────────────────────

def validate_roster(
    appendix: str,
    roster_start_utc: datetime,
    roster_end_utc: datetime,
    events: list[Any],
    prior_fdp_log: Optional[list] = None,
    prior_summary: Optional[Any] = None,
) -> dict:
    """
    Validate a full ordered roster of FDP, off-duty, and rest-day events.

    Parameters
    ----------
    appendix : str
        CAO 48.1 appendix identifier.
    roster_start_utc : datetime
        Start of the roster period.
    roster_end_utc : datetime
        End of the roster period. Used as the cumulative as_of timestamp.
    events : list
        Ordered list of RosterFdpEvent / RosterOdpEvent / RosterRestDayEvent
        (Pydantic objects or dicts with the same shape).
    prior_fdp_log : list, optional
        FDP history before the roster period (list of FdpHistoryRecord objects or
        dicts). Combined with the roster's own FDPs for cumulative checks.
    prior_summary : CumulativeSummaryInput, optional
        Pre-aggregated cumulative totals used when prior_fdp_log is not supplied.

    Returns
    -------
    dict
        Matches RosterValidationResponse shape.
    """
    appendix_upper = appendix.upper()
    if appendix_upper not in CUMULATIVE_CONFIGS:
        raise ValueError(f"Unknown appendix: {appendix!r}")

    has_wocl_rules = appendix_upper in _WOCL_APPENDICES

    # ── State tracking ────────────────────────────────────────────────
    consecutive_early_starts: int = 0
    consecutive_wocl: int = 0
    last_odp_had_local_night: bool = True   # optimistic default at roster start

    # Preceding FDP info for ODP validator
    preceding_fdp_hours: Optional[float] = None
    preceding_fdp_was_extended: bool = False
    preceding_fdp_extension_hours: float = 0.0

    # Accumulated results
    fdp_results: list[dict] = []
    odp_results: list[dict] = []
    sequence_checks: list[dict] = []
    sequence_violations: list[dict] = []
    warnings: list[str] = []
    fdp_history: list[dict] = []

    # Totals for summary
    total_flight_time_hours: float = 0.0
    total_duty_time_hours: float = 0.0
    total_rest_days: int = 0

    fdp_index: int = 0
    odp_index: int = 0

    for event in events:
        event_type = _get(event, "event_type")

        # ── FDP event ──────────────────────────────────────────────────
        if event_type == "fdp":
            fdp_index += 1

            fdp_start    = _to_utc(_get(event, "fdp_start_utc"))
            fdp_end      = _to_utc(_get(event, "fdp_end_utc"))
            flight_h     = _get(event, "actual_flight_time_hours", 0.0)
            duty_h       = _get(event, "actual_duty_time_hours", 0.0)
            offset       = _get(event, "local_time_offset_hours", 0.0)
            sectors      = _get(event, "sectors", 1)
            crosses_wocl = _get(event, "crosses_wocl", False)
            extension    = _get(event, "extension", None)
            augmented    = _get(event, "augmented_crew", None)
            split_duty   = _get(event, "split_duty", None)
            accl         = _get(event, "acclimatisation", None)
            single_pilot = _get(event, "single_pilot", False)

            duration_h = (fdp_end - fdp_start).total_seconds() / 3600

            # ── §13.2 WOCL sequence check (before per-FDP validation) ──
            if has_wocl_rules and crosses_wocl and consecutive_wocl >= 3:
                passed_wocl = last_odp_had_local_night
                clause = "§13.2" if appendix_upper == "2" else "§11.2"
                check = {
                    "check": f"fdp{fdp_index}_wocl_local_night_required",
                    "passed": passed_wocl,
                    "clause": clause,
                    "actual": None,
                    "limit": None,
                    "detail": (
                        f"FDP {fdp_index} infringes WOCL after "
                        f"{consecutive_wocl} consecutive WOCL infringements. "
                        + (
                            "Preceding ODP includes a local night — permitted."
                            if passed_wocl else
                            "Preceding ODP does NOT include a local night — "
                            "not permitted without an intervening off-duty "
                            "period that includes a local night."
                        )
                    ),
                }
                sequence_checks.append(check)
                if not passed_wocl:
                    sequence_violations.append({
                        **check,
                        "severity": "hard_limit",
                        "remediation": (
                            "Ensure an off-duty period including a local night "
                            "precedes any FDP that infringes the WOCL after "
                            "3 consecutive WOCL infringements."
                        ),
                    })

            # ── Per-FDP validation ──────────────────────────────────────
            fdp_item_violations: list[dict] = []
            fdp_item_checks: list[dict] = []
            fdp_item_notes: list[str] = []
            fdp_item_warnings: list[str] = []

            try:
                fdp_result = validate_fdp(
                    appendix=appendix_upper,
                    fdp_start_utc=_to_iso(fdp_start),
                    fdp_end_utc=_to_iso(fdp_end),
                    local_time_offset_hours=offset,
                    sectors=sectors,
                    actual_flight_time_hours=flight_h,
                    extension=(
                        extension.model_dump()
                        if hasattr(extension, "model_dump") else extension
                    ),
                    acclimatisation_state=(
                        accl.state
                        if hasattr(accl, "state") else "not_applicable"
                    ),
                    acclimatised_time_offset_hours=(
                        accl.acclimatised_time_offset_hours
                        if hasattr(accl, "acclimatised_time_offset_hours") else None
                    ),
                    augmented_crew=(
                        augmented.model_dump()
                        if hasattr(augmented, "model_dump") else augmented
                    ),
                    split_duty=(
                        split_duty.model_dump()
                        if hasattr(split_duty, "model_dump") else split_duty
                    ),
                    consecutive_early_starts=consecutive_early_starts,
                    consecutive_wocl_infringements=consecutive_wocl,
                    single_pilot=single_pilot,
                )
                fdp_item_violations = fdp_result.get("violations", [])
                fdp_item_checks = fdp_result.get("checks", [])
                fdp_item_notes = fdp_result.get("calculation_notes", [])
                fdp_item_warnings = fdp_result.get("warnings", [])
            except ValueError as exc:
                warnings.append(f"FDP {fdp_index}: validation skipped — {exc}")

            fdp_results.append({
                "fdp_number": fdp_index,
                "fdp_start_utc": fdp_start,
                "fdp_end_utc": fdp_end,
                "duration_hours": round(duration_h, 4),
                "valid": len(fdp_item_violations) == 0,
                "violations": fdp_item_violations,
                "checks": fdp_item_checks,
                "warnings": fdp_item_warnings,
                "calculation_notes": fdp_item_notes,
            })

            # ── Update state ────────────────────────────────────────────
            this_early_start = _is_early_start(fdp_start, offset)
            consecutive_early_starts = (
                consecutive_early_starts + 1 if this_early_start else 0
            )
            consecutive_wocl = consecutive_wocl + 1 if crosses_wocl else 0
            last_odp_had_local_night = False  # pessimistic until next ODP

            total_flight_time_hours += flight_h
            total_duty_time_hours += duty_h

            # Track for ODP & cumulative
            preceding_fdp_hours = duration_h
            preceding_fdp_was_extended = extension is not None
            preceding_fdp_extension_hours = (
                _get(extension, "hours_used", 0.0)
                if extension is not None else 0.0
            )

            fdp_history.append({
                "fdp_start_utc": fdp_start,
                "fdp_end_utc": fdp_end,
                "actual_flight_time_hours": flight_h,
                "actual_duty_time_hours": duty_h,
                "local_time_offset_hours": offset,
            })

        # ── Off-duty event ─────────────────────────────────────────────
        elif event_type == "off_duty":
            odp_index += 1

            odp_start       = _to_utc(_get(event, "start_utc"))
            odp_end         = _to_utc(_get(event, "end_utc"))
            duration_h      = _get(event, "duration_hours", 0.0)
            includes_night  = _get(event, "includes_local_night", False)
            following_night = _get(event, "following_includes_local_night", True)
            location        = _get(event, "location", "away")

            odp_item_violations: list[dict] = []
            odp_item_checks: list[dict] = []
            odp_item_warnings: list[str] = []

            if preceding_fdp_hours is not None:
                try:
                    odp_result = validate_off_duty(
                        appendix=appendix_upper,
                        preceding_fdp_duration_hours=preceding_fdp_hours,
                        actual_off_duty_hours=duration_h,
                        location=location,
                        was_extended=preceding_fdp_was_extended,
                        extension_hours=preceding_fdp_extension_hours,
                        following_includes_local_night=following_night,
                    )
                    odp_item_violations = odp_result.get("violations", [])
                    odp_item_checks = odp_result.get("checks", [])
                    odp_item_warnings = odp_result.get("warnings", [])
                except ValueError as exc:
                    warnings.append(f"ODP {odp_index}: validation skipped — {exc}")

            odp_results.append({
                "odp_number": odp_index,
                "start_utc": odp_start,
                "end_utc": odp_end,
                "duration_hours": round(duration_h, 4),
                "valid": len(odp_item_violations) == 0,
                "violations": odp_item_violations,
                "checks": odp_item_checks,
                "warnings": odp_item_warnings,
            })

            # A qualifying recovery (≥36h + local night) resets streaks
            if duration_h >= 36 and includes_night:
                consecutive_early_starts = 0
                consecutive_wocl = 0

            last_odp_had_local_night = includes_night
            # Reset preceding FDP tracking so next ODP doesn't re-validate same FDP
            preceding_fdp_hours = None

        # ── Rest day event ─────────────────────────────────────────────
        elif event_type == "rest_day":
            count          = _get(event, "count", 1)
            includes_night = _get(event, "includes_local_night", True)
            total_rest_days += count

            # Two or more consecutive rest days (or a single rest day with
            # a local night) functions like a qualifying recovering, resetting
            # the consecutive-start and WOCL counters.
            if count >= 2 or (count >= 1 and includes_night):
                consecutive_early_starts = 0
                consecutive_wocl = 0
                if includes_night:
                    last_odp_had_local_night = True

    # ── Cumulative check across roster + prior history ─────────────────
    # Build combined FDP log: prior history (if any) + roster FDPs
    combined_log = list(prior_fdp_log or []) + fdp_history
    cum_result: dict = {}

    if combined_log or prior_summary is not None:
        as_of = _to_utc(roster_end_utc)
        try:
            cum_result = validate_cumulative(
                appendix=appendix_upper,
                as_of_utc=as_of,
                fdp_log=combined_log if combined_log else None,
                summary=prior_summary if not combined_log else None,
            )
        except ValueError as exc:
            warnings.append(f"Cumulative check skipped — {exc}")
    else:
        warnings.append(
            "No FDPs in roster and no prior history provided — cumulative checks skipped."
        )

    # ── Build flat all_violations list ────────────────────────────────
    all_violations: list[dict] = []
    fdp_violation_count = 0
    odp_violation_count = 0

    for item in fdp_results:
        if item["violations"]:
            fdp_violation_count += 1
            all_violations.extend(item["violations"])

    for item in odp_results:
        if item["violations"]:
            odp_violation_count += 1
            all_violations.extend(item["violations"])

    all_violations.extend(sequence_violations)
    cum_violations = cum_result.get("violations", [])
    all_violations.extend(cum_violations)

    # ── Summary ───────────────────────────────────────────────────────
    summary = {
        "total_fdps": fdp_index,
        "total_off_duty_periods": odp_index,
        "total_rest_days": total_rest_days,
        "total_flight_time_hours": round(total_flight_time_hours, 4),
        "total_duty_time_hours": round(total_duty_time_hours, 4),
        "fdp_violations": fdp_violation_count,
        "odp_violations": odp_violation_count,
        "sequence_violations": len(sequence_violations),
        "cumulative_violations": len(cum_violations),
        "total_violations": len(all_violations),
    }

    return {
        "valid": len(all_violations) == 0,
        "appendix": appendix_upper,
        "roster_start_utc": _to_utc(roster_start_utc),
        "roster_end_utc": _to_utc(roster_end_utc),
        "summary": summary,
        "fdp_results": fdp_results,
        "odp_results": odp_results,
        "sequence_checks": sequence_checks,
        "sequence_violations": sequence_violations,
        "cumulative_result": cum_result,
        "all_violations": all_violations,
        "warnings": warnings,
    }
