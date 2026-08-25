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

from app.data.fdp_tables import FDP_CONFIGS
from app.engines.fdp_calculator import calculate_max_fdp, _extension_ceiling


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

    # ─── Resolve the extension actually available in law ───────────────
    final_max = limits["final_max_fdp_hours"]
    ext_rules = FDP_CONFIGS[appendix].extensions
    requested_hours = extension["hours_used"] if extension else 0.0
    ext_type = extension["type"] if extension else None

    permitted_hours, ext_clause, ext_reasons = _resolve_extension(
        appendix, ext_rules, ext_type, requested_hours, single_pilot,
        limits.get("split_duty_applied", False),
    )

    # ─── Check 1: FDP within applicable limit ──────────────────────────
    # The limit is built from the extension the law permits, capped at the
    # appendix maximum — never the one the caller asked for. Crediting the
    # requested figure let a check pass on an extension the adjacent check had
    # just ruled unlawful.
    effective_limit = final_max + permitted_hours
    ceiling = (
        _extension_ceiling(ext_rules, ext_type or "unforeseen",
                           limits.get("split_duty_applied", False))
        if extension else None
    )
    ceiling_applied = ceiling is not None and effective_limit > ceiling
    if ceiling_applied:
        effective_limit = ceiling

    fdp_passed = actual_fdp_hours <= effective_limit

    if extension:
        detail_suffix = (
            f" (base {final_max:.2f}h + {permitted_hours:.2f}h permitted "
            f"extension; {requested_hours:.2f}h requested"
            + (f"; capped at {ceiling:.2f}h by {ext_clause}" if ceiling_applied else "")
            + ")"
        )
    else:
        detail_suffix = ""

    _add_check(
        check_id="fdp_within_limit",
        passed=fdp_passed,
        clause=ext_clause if extension else f"CAO 48.1 Appendix {appendix}",
        actual=round(actual_fdp_hours, 4),
        limit=round(effective_limit, 4),
        detail=(
            f"Actual FDP {actual_fdp_hours:.2f}h "
            f"{'≤' if fdp_passed else '>'} "
            f"limit {effective_limit:.2f}h{detail_suffix}"
        ),
        severity="hard_limit",
        remediation=(
            f"Reduce FDP to {effective_limit:.2f}h or less."
            if not fdp_passed else ""
        ),
    )

    # ─── Check 2: Extension permitted (only when extension provided) ───
    if extension:
        ext_passed = len(ext_reasons) == 0
        _add_check(
            check_id="extension_permitted",
            passed=ext_passed,
            clause=ext_clause,
            actual=requested_hours,
            limit=permitted_hours if permitted_hours > 0 else None,
            detail=(
                f"Extension {requested_hours}h ({ext_type}): "
                + ("permitted" if ext_passed else "; ".join(ext_reasons))
            ),
            severity="hard_limit",
            remediation=(
                "; ".join(ext_reasons) + "." if not ext_passed else ""
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

    # Violations raised during limit calculation (e.g. a prohibited 6th
    # consecutive early start) are part of this FDP's outcome.
    for calc_violation in limits.get("violations", []):
        violations.append(calc_violation)
        checks.append({
            "check": calc_violation["check"],
            "passed": False,
            "clause": calc_violation["clause"],
            "actual": calc_violation["actual"],
            "limit": calc_violation["limit"],
            "detail": calc_violation["detail"],
        })

    warnings: list[str] = []
    if extension and ext_rules.caller_must_verify:
        warnings.append(
            "Conditions this API cannot verify gate the extension: "
            + "; ".join(
                f"{clause} {description}"
                for clause, description in ext_rules.caller_must_verify
            )
        )
    if extension and ext_rules.clause_cumulative_crosscheck:
        warnings.append(
            f"{ext_rules.clause_cumulative_crosscheck}: an FDP limit must not be "
            "extended if doing so would exceed the cumulative flight time "
            "limits. Not checked here — supply history to /validate/cumulative."
        )

    return {
        "valid": len(violations) == 0,
        "appendix": appendix,
        "violations": violations,
        "checks": checks,
        "warnings": warnings,
        "calculation_notes": limits["calculation_notes"],
    }


def _resolve_extension(
    appendix: str,
    rules,
    ext_type: str | None,
    requested_hours: float,
    single_pilot: bool,
    split_duty_applied: bool,
) -> tuple[float, str, list[str]]:
    """
    Return (permitted_hours, clause, reasons_it_is_not_permitted).

    `permitted_hours` is what the law allows, capped at the appendix maximum —
    the figure the duration check must be built from, regardless of what the
    caller requested.
    """
    reasons: list[str] = []

    if ext_type is None:
        return 0.0, f"CAO 48.1 Appendix {appendix}", reasons

    if not rules.available:
        return 0.0, f"CAO 48.1 Appendix {appendix}", [
            f"Appendix {appendix} provides no FDP extension."
        ]

    if ext_type == "urgent":
        if not rules.urgent_available:
            return 0.0, rules.clause_unforeseen, [
                "Extension type 'urgent' applies to urgent operations under "
                "Appendix 4B clause 3.2; it is not available under Appendix "
                f"{appendix}"
            ]
        allowance = rules.urgent_hours
        clause = rules.clause_urgent
    else:
        # "unforeseen" and "final_sector" both run off the unforeseen provision.
        allowance = (
            rules.unforeseen_hours_single_pilot if single_pilot
            else rules.unforeseen_hours_multi_pilot
        )
        clause = rules.clause_unforeseen

    if requested_hours > allowance:
        reasons.append(
            f"{requested_hours}h extension exceeds the maximum of {allowance}h "
            f"permitted under {clause} for a "
            f"{'single-pilot' if single_pilot else 'multi-pilot'} operation"
        )

    permitted = min(requested_hours, allowance)
    return permitted, clause, reasons
