"""
Off-duty period (ODP) validator engine.

Calls the off-duty calculator to determine the minimum required ODP, then
compares the actual off-duty period against that minimum. Optionally checks
that reduction eligibility conditions are satisfied when a reduced ODP is claimed.

Returns a dict matching the ValidationResponse model shape.

All logic derived from CAO 48.1 Instrument 2019 (Compilation No. 3, F2021C01239).
"""

from app.data.off_duty_rules import OFF_DUTY_CONFIGS
from app.engines.off_duty_calculator import calculate_min_off_duty


def validate_off_duty(
    appendix: str,
    preceding_fdp_duration_hours: float,
    actual_off_duty_hours: float,
    post_fdp_duty_hours: float = 0.0,
    location: str = "away",
    split_duty_duration_hours: float | None = None,
    split_duty_accommodation: str | None = None,
    split_duty_overlaps_night: bool = False,
    was_extended: bool = False,
    extension_hours: float = 0.0,
    preceding_odp_duration_hours: float | None = None,
    preceding_odp_included_night: bool = False,
    following_includes_local_night: bool = True,
    acclimatisation_state: str = "not_applicable",
    reduction_claimed: bool = False,
    fdp_commencement_utc_offset_hours: float | None = None,
    following_off_duty_utc_offset_hours: float | None = None,
) -> dict:
    """
    Validate an off-duty period against all applicable CAO 48.1 rules.

    Returns a dict matching the ValidationResponse model shape.
    Raises ValueError for an unrecognised appendix.
    """
    config = OFF_DUTY_CONFIGS.get(appendix)
    if config is None:
        raise ValueError(f"Unknown appendix: {appendix}")

    # ─── Calculate minimum ODP ────────────────────────────────────────
    limits = calculate_min_off_duty(
        appendix=appendix,
        preceding_fdp_duration_hours=preceding_fdp_duration_hours,
        post_fdp_duty_hours=post_fdp_duty_hours,
        location=location,
        split_duty_duration_hours=split_duty_duration_hours,
        split_duty_accommodation=split_duty_accommodation,
        split_duty_overlaps_night=split_duty_overlaps_night,
        was_extended=was_extended,
        extension_hours=extension_hours,
        preceding_odp_duration_hours=preceding_odp_duration_hours,
        preceding_odp_included_night=preceding_odp_included_night,
        following_includes_local_night=following_includes_local_night,
        acclimatisation_state=acclimatisation_state,
        fdp_commencement_utc_offset_hours=fdp_commencement_utc_offset_hours,
        following_off_duty_utc_offset_hours=following_off_duty_utc_offset_hours,
    )

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

    # ─── Check 1: ODP meets minimum ───────────────────────────────────
    min_odp = limits["final_min_odp_hours"]
    odp_passed = actual_off_duty_hours >= min_odp
    _add_check(
        check_id="odp_meets_minimum",
        passed=odp_passed,
        clause=limits["clause"],
        actual=actual_off_duty_hours,
        limit=min_odp,
        detail=(
            f"Actual ODP {actual_off_duty_hours:.2f}h "
            f"{'≥' if odp_passed else '<'} "
            f"minimum {min_odp:.2f}h"
        ),
        severity="hard_limit",
        remediation=(
            f"Extend off-duty period to at least {min_odp:.2f}h."
            if not odp_passed else ""
        ),
    )

    # ─── Check 2: Reduction conditions met (if reduction claimed) ─────
    if reduction_claimed:
        reduction = limits["reduction_applicable"]

        if reduction is None:
            # Appendix has no reduction provisions at all
            red_passed = False
            detail = f"Appendix {appendix} does not have off-duty reduction provisions."
            remediation = (
                f"No ODP reduction is available under Appendix {appendix}. "
                f"The full minimum off-duty period must be observed."
            )
            clause = config.clause
            limit_val = None
        else:
            red_passed = reduction["eligible"]
            conditions = (
                "; ".join(reduction["conditions_met"])
                if reduction["conditions_met"]
                else "Conditions not met"
            )
            detail = (
                f"Reduction to {reduction.get('reduced_min_odp_hours')}h "
                f"{'eligible' if red_passed else 'not eligible'}: {conditions}"
            )
            remediation = (
                "" if red_passed else
                "Ensure all eligibility conditions for the reduction provision "
                "are satisfied before applying a reduced ODP."
            )
            clause = reduction.get("clause") or config.clause
            limit_val = reduction.get("reduced_min_odp_hours") if red_passed else None

        _add_check(
            check_id="reduction_conditions_met",
            passed=red_passed,
            clause=clause,
            actual=actual_off_duty_hours,
            limit=limit_val,
            detail=detail,
            severity="hard_limit",
            remediation=remediation,
        )

    return {
        "valid": len(violations) == 0,
        "appendix": appendix,
        "violations": violations,
        "checks": checks,
        "warnings": [],
        "calculation_notes": limits["calculation_notes"],
    }
