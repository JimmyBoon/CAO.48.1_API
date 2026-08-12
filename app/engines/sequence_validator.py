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
from app.engines.off_duty_validator import validate_off_duty
from app.data.fdp_tables import FDP_CONFIGS
from app.data.cumulative_limits import CUMULATIVE_CONFIGS


# ─── Early-start window ──────────────────────────────────────────────
# CAO 48.1: early start = FDP start between 0500 and 0659 local time.
_EARLY_START_MIN_HHMM = 500   # 0500
_EARLY_START_MAX_HHMM = 659   # 0659

# Appendices that have WOCL/early-start rules (§13/§11/§10 etc.)
_WOCL_APPENDICES = {"2", "3", "4", "4B", "5", "5A", "6"}

# Appendix 2 §3.4 — maximum consecutive FDPs in an unknown state of
# acclimatisation before an adaptation period under §7.4 is required.
#
# The run is ended by an FDP assigned in any state other than 'unknown'. It is
# deliberately NOT reset by a long off-duty period on its own: whether an
# off-duty period is a *sufficient* adaptation period depends on the greatest
# time zone displacement and its direction (Table 7.1), which the sequence
# events do not carry. Callers who have completed an adaptation period express
# that by declaring the following FDP as 'acclimatised' — which is what their
# state genuinely is at that point. POST /calculate/acclimatisation determines
# it for them.
_MAX_CONSECUTIVE_UNKNOWN_FDPS = 4


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


def _as_dict(value: Any) -> Optional[dict]:
    """
    Normalise a Pydantic sub-model or plain dict to a dict, or None.

    Sequence events arrive either as Pydantic objects (from the route) or as
    plain dicts (from tests and internal callers), so every nested object has to
    be handled both ways.
    """
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return dict(value)


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
    consecutive_unknown_fdps: int = 0   # Appendix 2 §3.4, count BEFORE current FDP
    last_odp_had_local_night: bool = True  # optimistic default at sequence start

    # For the cumulative check at sequence end
    fdp_history: list[dict] = []

    # For the ODP validator: everything the minimum-ODP calculation needs from
    # the preceding FDP. Carrying only the duration meant the split-duty credit,
    # the post-FDP duty and the acclimatisation state were all silently dropped.
    preceding_fdp_hours: Optional[float] = None
    preceding_fdp_was_extended: bool = False
    preceding_fdp_extension_hours: float = 0.0
    preceding_post_fdp_duty_hours: float = 0.0
    preceding_split_duty: Optional[dict] = None
    preceding_acclim_state: str = "not_applicable"
    preceding_fdp_offset: Optional[float] = None
    # The ODP before the last FDP, for the §10.3(a)/§8.3(a) reduction conditions.
    previous_odp_duration_hours: Optional[float] = None
    previous_odp_included_night: bool = False

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
                crosses_wocl = event.crosses_wocl
                accl_state = getattr(event, "acclimatisation_state", "not_applicable")
                accl_offset = getattr(event, "acclimatised_time_offset_hours", None)
                split_duty = getattr(event, "split_duty", None)
                extension = getattr(event, "extension", None)
                augmented = getattr(event, "augmented_crew", None)
                single_pilot = getattr(event, "single_pilot", False)
                fdp_offset = getattr(event, "commencement_utc_offset_hours", None)
            else:
                fdp_start = _to_utc(event["fdp_start_utc"])
                fdp_end   = _to_utc(event["fdp_end_utc"])
                flight_h  = event["actual_flight_time_hours"]
                duty_h    = event["actual_duty_time_hours"]
                offset    = event["local_time_offset_hours"]
                sectors   = event["sectors"]
                crosses_wocl = event.get("crosses_wocl", False)
                accl_state = event.get("acclimatisation_state", "not_applicable")
                accl_offset = event.get("acclimatised_time_offset_hours", None)
                split_duty = event.get("split_duty", None)
                extension = event.get("extension", None)
                augmented = event.get("augmented_crew", None)
                single_pilot = event.get("single_pilot", False)
                fdp_offset = event.get("commencement_utc_offset_hours", None)

            # ── Appendix 2 §3.4: max 4 consecutive unknown-state FDPs ────
            # "An FCM may only be assigned 4 consecutive FDPs in an unknown
            # state of acclimatisation after which the FCM must have an
            # adaptation period sufficient to become reacclimatised in
            # accordance with paragraph 7.4." The violation lands on the 5th.
            if appendix_upper == "2" and accl_state == "unknown":
                run_length = consecutive_unknown_fdps + 1
                _add_check(
                    checks, violations,
                    check_id=f"{label}consecutive_unknown_state_fdps",
                    passed=run_length <= _MAX_CONSECUTIVE_UNKNOWN_FDPS,
                    clause="Appendix 2 §3.4",
                    actual=float(run_length),
                    limit=float(_MAX_CONSECUTIVE_UNKNOWN_FDPS),
                    detail=(
                        f"FDP {fdp_index} is consecutive unknown-state FDP "
                        f"#{run_length}. "
                        + (
                            "Within the limit of 4."
                            if run_length <= _MAX_CONSECUTIVE_UNKNOWN_FDPS else
                            "Exceeds the maximum of 4 consecutive FDPs in an "
                            "unknown state of acclimatisation."
                        )
                    ),
                    remediation=(
                        "Insert an adaptation period sufficient for the FCM to "
                        "become reacclimatised under §7.4 before assigning a "
                        "further FDP. Use POST /calculate/acclimatisation to "
                        "determine the required adaptation period."
                    ),
                )

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
                    acclimatisation_state=accl_state,
                    acclimatised_time_offset_hours=accl_offset,
                    extension=_as_dict(extension),
                    augmented_crew=_as_dict(augmented),
                    split_duty=_as_dict(split_duty),
                    single_pilot=single_pilot,
                )
                _merge_result(checks, violations, fdp_result, prefix=label)
                notes.extend(
                    [f"FDP {fdp_index}: {n}" for n in fdp_result.get("calculation_notes", [])]
                )
            except ValueError as exc:
                notes.append(f"FDP {fdp_index}: skipped — {exc}")

            # ── Update state after this FDP ────────────────────────────
            # §3.4 run length: an unknown-state FDP extends the run, any other
            # state ends it.
            consecutive_unknown_fdps = (
                consecutive_unknown_fdps + 1 if accl_state == "unknown" else 0
            )

            # Early-start streaks are assessed on the clock that governs the
            # appendix — acclimatised time for Appendix 2 (§6), departure-point
            # local time everywhere else.
            early_start_offset = (
                accl_offset
                if appendix_upper == "2"
                and accl_state in ("acclimatised", "unknown")
                and accl_offset is not None
                else offset
            )
            this_early_start = _is_early_start(fdp_start, early_start_offset)
            consecutive_early_starts = (
                consecutive_early_starts + 1 if this_early_start else 0
            )
            consecutive_wocl = consecutive_wocl + 1 if crosses_wocl else 0

            # After each FDP, assume (pessimistically) next ODP has no local night
            # until an ODP event updates it.
            last_odp_had_local_night = False

            # ── Carry forward everything the following ODP needs ────────
            fdp_hours = (fdp_end - fdp_start).total_seconds() / 3600
            preceding_fdp_hours = fdp_hours
            extension_dict = _as_dict(extension)
            preceding_fdp_was_extended = extension_dict is not None
            preceding_fdp_extension_hours = (
                extension_dict.get("hours_used", 0.0) if extension_dict else 0.0
            )
            # Duty beyond the FDP's wall-clock duration is post-FDP duty, which
            # counts towards the 12-hour threshold in §10.1/§10.2 and §8.1/§8.2.
            preceding_post_fdp_duty_hours = max(duty_h - fdp_hours, 0.0)
            preceding_split_duty = _as_dict(split_duty)
            preceding_acclim_state = accl_state
            preceding_fdp_offset = fdp_offset if fdp_offset is not None else offset

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
                includes_night = event.includes_local_night
                location = event.location
                location_supplied = "location" in getattr(
                    event, "model_fields_set", set(),
                )
                odp_offset = getattr(event, "utc_offset_hours", None)
            else:
                duration_h = event["duration_hours"]
                includes_night = event.get("includes_local_night", False)
                location = event.get("location", "home_base")
                location_supplied = "location" in event
                odp_offset = event.get("utc_offset_hours", None)

            # Validate the ODP if we have a preceding FDP
            if preceding_fdp_hours is not None:
                try:
                    odp_result = validate_off_duty(
                        appendix=appendix_upper,
                        preceding_fdp_duration_hours=preceding_fdp_hours,
                        actual_off_duty_hours=duration_h,
                        post_fdp_duty_hours=preceding_post_fdp_duty_hours,
                        location=location,
                        split_duty_duration_hours=(
                            preceding_split_duty.get("duration_hours")
                            if preceding_split_duty else None
                        ),
                        split_duty_accommodation=(
                            preceding_split_duty.get("accommodation")
                            if preceding_split_duty else None
                        ),
                        split_duty_overlaps_night=bool(
                            preceding_split_duty.get("overlaps_2300_0529")
                            if preceding_split_duty else False
                        ),
                        was_extended=preceding_fdp_was_extended,
                        extension_hours=preceding_fdp_extension_hours,
                        preceding_odp_duration_hours=previous_odp_duration_hours,
                        preceding_odp_included_night=previous_odp_included_night,
                        following_includes_local_night=includes_night,
                        acclimatisation_state=preceding_acclim_state,
                        fdp_commencement_utc_offset_hours=preceding_fdp_offset,
                        following_off_duty_utc_offset_hours=odp_offset,
                    )
                    _merge_result(checks, violations, odp_result, prefix=label)
                    notes.extend(
                        [f"ODP {odp_index}: {n}" for n in odp_result.get("calculation_notes", [])]
                    )
                    if not location_supplied:
                        notes.append(
                            f"ODP {odp_index}: location not supplied — assumed "
                            f"'{location}', the longer of the two requirements. "
                            f"Away and home base differ by 2 hours."
                        )
                except ValueError as exc:
                    notes.append(f"ODP {odp_index}: skipped — {exc}")

            # A qualifying recovery (≥36h off + local night) resets streaks
            if duration_h >= 36 and includes_night:
                consecutive_early_starts = 0
                consecutive_wocl = 0

            last_odp_had_local_night = includes_night

            # Carry this ODP forward for the §10.3(a)/§8.3(a) conditions on the
            # 9-hour reduction, then clear the preceding-FDP state so the next
            # ODP does not re-validate against the same duty.
            previous_odp_duration_hours = duration_h
            previous_odp_included_night = includes_night
            preceding_post_fdp_duty_hours = 0.0
            preceding_split_duty = None
            preceding_acclim_state = "not_applicable"
            preceding_fdp_offset = None

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
