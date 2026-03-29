"""
FDP (Flight Duty Period) validator engine.

Calls the FDP calculator to determine the applicable limits, then compares
the actual FDP duration against those limits. Handles extension validation
and per-FDP flight time limit checks.

Returns a dict matching the ValidationResponse model shape, with every check
run included (pass or fail) and clause-referenced violations for failures.

All logic derived from CAO 48.1 Instrument 2019 (Compilation No. 3, F2021C01239).
"""

from datetime import datetime

from app.engines.fdp_calculator import calculate_max_fdp

# Extension type "urgent" is only valid for emergency service operations (Appendix 4B)
_URGENT_EXTENSION_APPENDICES = {"4B"}


def validate_fdp(
    appendix: str,
    fdp_start_utc: str,
    fdp_end_utc: str,
    local_time_offset_hours: float,
    sectors: int,
    actual_flight_time_hours: float | None = None,
    extension: dict | None = None,
    acclimatisation_state: str = "not_applicable",
    acclimatised_time_offset_hours: float | None = None,
    augmented_crew: dict | None = None,
    split_duty: dict | None = None,
    consecutive_early_starts: int = 0,
    consecutive_wocl_infringements: int = 0,
    single_pilot: bool = False,
    preceding_off_duty_hours: float | None = None,
) -> dict:
    """
    Validate an FDP against all applicable CAO 48.1 rules.

    Returns a dict matching the ValidationResponse model shape.
    Raises ValueError for an unrecognised appendix.
    """
    # ─── Calculate limits ─────────────────────────────────────────────
    limits = calculate_max_fdp(
        appendix=appendix,
        fdp_start_utc=fdp_start_utc,
        local_time_offset_hours=local_time_offset_hours,
        sectors=sectors,
        acclimatisation_state=acclimatisation_state,
        acclimatised_time_offset_hours=acclimatised_time_offset_hours,
        augmented_crew=augmented_crew,
        split_duty=split_duty,
        consecutive_early_starts=consecutive_early_starts,
        consecutive_wocl_infringements=consecutive_wocl_infringements,
        single_pilot=single_pilot,
        preceding_off_duty_hours=preceding_off_duty_hours,
    )

    # ─── Compute actual FDP duration ─────────────────────────────────
    start_dt = datetime.fromisoformat(fdp_start_utc.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(fdp_end_utc.replace("Z", "+00:00"))
    actual_fdp_hours = (end_dt - start_dt).total_seconds() / 3600

    checks: list[dict] = []
    violations: list[dict] = []

    def _add_check(
        check_id: str,
        passed: bool,
        clause: str,
        actual: float | None,
        limit: float | None,
        detail: str | None,
        severity: str = "hard_limit",
        remediation: str = "",
    ) -> None:
        checks.append({
            "check": check_id,
            "passed": passed,
            "clause": clause,
            "actual": actual,
            "limit": limit,
            "detail": detail,
        })
        if not passed:
            violations.append({
                "check": check_id,
                "clause": clause,
                "severity": severity,
                "actual": actual,
                "limit": limit,
                "detail": detail or "",
                "remediation": remediation,
            })

    # ─── Check 1: FDP within applicable limit ──────────────────────────
    # When extension provided, the applicable limit is the base max plus
    # the extension hours claimed. Extension validity is a separate check.
    final_max = limits["final_max_fdp_hours"]
    extension_hours_used = extension["hours_used"] if extension else 0.0
    applicable_limit = final_max + extension_hours_used
    extension_note = " (including extension)" if extension else ""

    fdp_passed = actual_fdp_hours <= applicable_limit
    _add_check(
        check_id="fdp_within_limit",
        passed=fdp_passed,
        clause=f"CAO 48.1 Appendix {appendix}",
        actual=round(actual_fdp_hours, 4),
        limit=round(applicable_limit, 4),
        detail=(
            f"Actual FDP {actual_fdp_hours:.2f}h "
            f"{'≤' if fdp_passed else '>'} "
            f"limit {applicable_limit:.2f}h{extension_note}"
        ),
        severity="hard_limit",
        remediation=(
            f"Reduce FDP to {applicable_limit:.2f}h or less."
            if not fdp_passed else ""
        ),
    )

    # ─── Check 2: Extension permitted (only when extension provided) ───
    if extension:
        ext_type = extension["type"]
        hours_used = extension["hours_used"]
        max_ext = limits["max_extension_hours"]

        reasons: list[str] = []
        if max_ext == 0:
            reasons.append(
                f"Appendix {appendix} does not permit FDP extensions"
            )
        if ext_type == "urgent" and appendix not in _URGENT_EXTENSION_APPENDICES:
            reasons.append(
                "Extension type 'urgent' is only valid for emergency service "
                "operations (Appendix 4B)"
            )
        if hours_used > max_ext > 0:
            reasons.append(
                f"{hours_used}h extension exceeds the maximum permitted "
                f"extension of {max_ext}h for Appendix {appendix}"
            )

        ext_passed = len(reasons) == 0
        _add_check(
            check_id="extension_permitted",
            passed=ext_passed,
            clause=f"CAO 48.1 Appendix {appendix}",
            actual=hours_used,
            limit=max_ext if max_ext > 0 else None,
            detail=(
                f"Extension {hours_used}h ({ext_type}): "
                + ("permitted" if ext_passed else "; ".join(reasons))
            ),
            severity="hard_limit",
            remediation=(
                "; ".join(reasons) + "." if not ext_passed else ""
            ),
        )

    # ─── Check 3: Flight time within per-FDP limit ────────────────────
    ft_limit = limits["flight_time_limit_hours"]
    if actual_flight_time_hours is not None and ft_limit is not None:
        ft_passed = actual_flight_time_hours <= ft_limit
        _add_check(
            check_id="flight_time_within_limit",
            passed=ft_passed,
            clause=f"CAO 48.1 Appendix {appendix}",
            actual=actual_flight_time_hours,
            limit=ft_limit,
            detail=(
                f"Actual flight time {actual_flight_time_hours:.2f}h "
                f"{'≤' if ft_passed else '>'} limit {ft_limit:.2f}h"
            ),
            severity="hard_limit",
            remediation=(
                f"Reduce flight time to {ft_limit:.2f}h or less."
                if not ft_passed else ""
            ),
        )

    return {
        "valid": len(violations) == 0,
        "appendix": appendix,
        "violations": violations,
        "checks": checks,
        "warnings": [],
        "calculation_notes": limits["calculation_notes"],
    }
