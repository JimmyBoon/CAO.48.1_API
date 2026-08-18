"""
sequence_validator.py — Validate an ordered sequence of FDP and off-duty events.

Processes events in chronological order maintaining state for:
  - Consecutive early starts (§13.x)
  - Consecutive WOCL infringements (§13.2)

Validates each FDP and each off-duty period individually, then runs a
cumulative check across all FDPs in the sequence.

All logic derived from CAO 48.1 Instrument 2019 (Compilation No. 3, F2021C01239).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.engines.cumulative_validator import validate_cumulative
from app.engines.fdp_validator import validate_fdp
from app.engines.local_night import contains_local_night
from app.engines.off_duty_validator import validate_off_duty
from app.engines.wocl import crosses_wocl as _derive_crosses_wocl
from app.data.fdp_tables import FDP_CONFIGS
from app.data.cumulative_limits import CUMULATIVE_CONFIGS


# ─── Early-start window ──────────────────────────────────────────────
# CAO 48.1: early start = FDP start between 0500 and 0659 local time.
_EARLY_START_MIN_HHMM = 500   # 0500
_EARLY_START_MAX_HHMM = 659   # 0659

# Appendices that have WOCL/early-start rules (§13/§11/§10 etc.)
_WOCL_APPENDICES = {"2", "3", "4", "4B", "5", "5A", "6"}


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_iso(dt: datetime) -> str:
    """Return a timezone-aware datetime as an ISO 8601 Z-suffix string."""
    dt = _to_utc(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _local_hhmm(utc_dt: datetime, offset_hours: float) -> int:
    """Return the local time as an integer HHMM (e.g. 0530 → 530)."""
    local_dt = _to_utc(utc_dt) + timedelta(hours=offset_hours)
    return local_dt.hour * 100 + local_dt.minute


def _is_early_start(fdp_start_utc: datetime, local_offset_hours: float) -> bool:
    hhmm = _local_hhmm(fdp_start_utc, local_offset_hours)
    return _EARLY_START_MIN_HHMM <= hhmm <= _EARLY_START_MAX_HHMM


# ─── Check/violation helpers ──────────────────────────────────────────

def _add_check(
    checks: list,
    violations: list,
    check_id: str,
    passed: bool,
    clause: str,
    actual: Optional[float],
    limit: Optional[float],
    detail: str,
    severity: str = "hard_limit",
    remediation: str = "",
) -> None:
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


def _merge_result(
    checks: list,
    violations: list,
    result: dict,
    prefix: str,
) -> None:
    """Merge checks/violations from a sub-validator into the parent lists."""
    for c in result.get("checks", []):
        checks.append({**c, "check": f"{prefix}{c['check']}"})
    for v in result.get("violations", []):
        violations.append({**v, "check": f"{prefix}{v['check']}"})


# ─── Public API ───────────────────────────────────────────────────────

def validate_sequence(
    appendix: str,
    events: list[Any],
) -> dict:
    """
    Validate an ordered sequence of FDP and off-duty events.

    Parameters
    ----------
    appendix : str
        CAO 48.1 appendix identifier.
    events : list
        Ordered list of SequenceFdpEvent / SequenceOdpEvent Pydantic objects
        (or dicts with the same shape).

    Returns
    -------
    dict
        Matches ValidationResponse shape.
    """
    appendix_upper = appendix.upper()
    if appendix_upper not in CUMULATIVE_CONFIGS:
        raise ValueError(f"Unknown appendix: {appendix!r}")

    checks: list = []
    violations: list = []
    notes: list = []

    has_wocl_rules = appendix_upper in _WOCL_APPENDICES

    # State tracking
    consecutive_early_starts: int = 0    # count BEFORE current FDP
    consecutive_wocl: int = 0           # count BEFORE current FDP
    last_odp_had_local_night: bool = True  # optimistic default at sequence start

    # For the cumulative check at sequence end
    fdp_history: list[dict] = []

    # For the ODP validator: track preceding FDP duration
    preceding_fdp_hours: Optional[float] = None
    preceding_fdp_was_extended: bool = False
    preceding_fdp_extension_hours: float = 0.0

    # Local offset of the most recently seen FDP, used to derive whether an
    # off-duty period includes a local night from its own timestamps.
    last_known_offset: Optional[float] = None

    # Counters for labelling purposes
    fdp_index: int = 0
    odp_index: int = 0

    for event in events:
        # Support both Pydantic models and plain dicts
        if hasattr(event, "event_type"):
            event_type = event.event_type
        else:
            event_type = event["event_type"]

        # ── FDP event ──────────────────────────────────────────────────
        if event_type == "fdp":
            fdp_index += 1
            label = f"fdp{fdp_index}_"

            if hasattr(event, "fdp_start_utc"):
                fdp_start = _to_utc(event.fdp_start_utc)
                fdp_end   = _to_utc(event.fdp_end_utc)
                flight_h  = event.actual_flight_time_hours
                duty_h    = event.actual_duty_time_hours
                offset    = event.local_time_offset_hours
                sectors   = event.sectors
            else:
                fdp_start = _to_utc(event["fdp_start_utc"])
                fdp_end   = _to_utc(event["fdp_end_utc"])
                flight_h  = event["actual_flight_time_hours"]
                duty_h    = event["actual_duty_time_hours"]
                offset    = event["local_time_offset_hours"]
                sectors   = event["sectors"]

            # Derived from the FDP's own timestamps (§6.1/§6.2) — a caller-supplied
            # crosses_wocl value is never trusted, since it can't be cross-checked
            # and silently disables the entire §13.2 consecutive-WOCL check.
            crosses_wocl = _derive_crosses_wocl(fdp_start, fdp_end, offset)
            notes.append(f"FDP {fdp_index}: crosses_wocl={crosses_wocl} (derived, not caller-supplied)")

            last_known_offset = offset

            # ── §13.2 WOCL sequence check (before calling validate_fdp) ──
            if has_wocl_rules and crosses_wocl and consecutive_wocl >= 3:
                passed_wocl = last_odp_had_local_night
                _add_check(
                    checks, violations,
                    check_id=f"{label}wocl_local_night_required",
                    passed=passed_wocl,
                    clause="§13.2" if appendix_upper == "2" else "§11.2",
                    actual=None,
                    limit=None,
                    detail=(
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
                    remediation=(
                        "Ensure an off-duty period including a local night "
                        "precedes any FDP that infringes the WOCL after "
                        "3 consecutive WOCL infringements."
                    ),
                )

            # ── Per-FDP validation (FDP duration + flight time + ext) ──
            try:
                fdp_result = validate_fdp(
                    appendix=appendix_upper,
                    fdp_start_utc=_to_iso(fdp_start),
                    fdp_end_utc=_to_iso(fdp_end),
                    local_time_offset_hours=offset,
                    sectors=sectors,
                    actual_flight_time_hours=flight_h,
                    consecutive_early_starts=consecutive_early_starts,
                    consecutive_wocl_infringements=consecutive_wocl,
                )
                _merge_result(checks, violations, fdp_result, prefix=label)
                notes.extend(
                    [f"FDP {fdp_index}: {n}" for n in fdp_result.get("calculation_notes", [])]
                )
            except ValueError as exc:
                notes.append(f"FDP {fdp_index}: skipped — {exc}")

            # ── Update state after this FDP ────────────────────────────
            this_early_start = _is_early_start(fdp_start, offset)
            consecutive_early_starts = (
                consecutive_early_starts + 1 if this_early_start else 0
            )
            consecutive_wocl = consecutive_wocl + 1 if crosses_wocl else 0

            # After each FDP, assume (pessimistically) next ODP has no local night
            # until an ODP event updates it.
            last_odp_had_local_night = False

            # Accumulate for cumulative check
            fdp_hours = (fdp_end - fdp_start).total_seconds() / 3600
            preceding_fdp_hours = fdp_hours
            preceding_fdp_was_extended = False
            preceding_fdp_extension_hours = 0.0

            fdp_history.append(
                {
                    "fdp_start_utc": fdp_start,
                    "fdp_end_utc": fdp_end,
                    "actual_flight_time_hours": flight_h,
                    "actual_duty_time_hours": duty_h,
                    "local_time_offset_hours": offset,
                }
            )

        # ── Off-duty event ─────────────────────────────────────────────
        elif event_type == "off_duty":
            odp_index += 1
            label = f"odp{odp_index}_"

            if hasattr(event, "duration_hours"):
                duration_h = event.duration_hours
                odp_start = _to_utc(event.start_utc)
                odp_end = _to_utc(event.end_utc)
                location = event.location
            else:
                duration_h = event["duration_hours"]
                odp_start = _to_utc(event["start_utc"])
                odp_end = _to_utc(event["end_utc"])
                location = event.get("location", "away")

            # Derived from the ODP's own timestamps (§6.1) — a caller-supplied
            # includes_local_night value is never trusted, since it can't be
            # cross-checked and silently masks WOCL violations if wrong.
            includes_night = (
                contains_local_night(odp_start, odp_end, last_known_offset)
                if last_known_offset is not None else False
            )
            notes.append(
                f"ODP {odp_index}: includes_local_night={includes_night} (derived, not caller-supplied)"
            )

            # Validate the ODP if we have a preceding FDP
            if preceding_fdp_hours is not None:
                try:
                    odp_result = validate_off_duty(
                        appendix=appendix_upper,
                        preceding_fdp_duration_hours=preceding_fdp_hours,
                        actual_off_duty_hours=duration_h,
                        location=location,
                        was_extended=preceding_fdp_was_extended,
                        extension_hours=preceding_fdp_extension_hours,
                        following_includes_local_night=includes_night,
                    )
                    _merge_result(checks, violations, odp_result, prefix=label)
                    notes.extend(
                        [f"ODP {odp_index}: {n}" for n in odp_result.get("calculation_notes", [])]
                    )
                except ValueError as exc:
                    notes.append(f"ODP {odp_index}: skipped — {exc}")

            # A qualifying recovery (≥36h off + local night) resets streaks
            if duration_h >= 36 and includes_night:
                consecutive_early_starts = 0
                consecutive_wocl = 0

            last_odp_had_local_night = includes_night

    # ── Cumulative check across all FDPs in the sequence ─────────────
    if fdp_history:
        last_fdp_end = max(r["fdp_end_utc"] for r in fdp_history)
        try:
            cum_result = validate_cumulative(
                appendix=appendix_upper,
                as_of_utc=last_fdp_end,
                fdp_log=fdp_history,
            )
            _merge_result(checks, violations, cum_result, prefix="cumulative_")
            notes.extend(
                [f"Cumulative: {n}" for n in cum_result.get("calculation_notes", [])]
            )
        except ValueError as exc:
            notes.append(f"Cumulative check skipped — {exc}")

    return {
        "valid": len(violations) == 0,
        "appendix": appendix_upper,
        "violations": violations,
        "checks": checks,
        "warnings": [],
        "calculation_notes": notes,
    }
