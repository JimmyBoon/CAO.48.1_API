"""
Off-duty period (ODP) calculator engine.

Pure calculation functions for determining the minimum required off-duty period
given a preceding FDP and its parameters.

All logic derived from CAO 48.1 Instrument 2019 (Compilation No. 3, F2021C01239).
"""

from app.data.off_duty_rules import OFF_DUTY_CONFIGS, OffDutyConfig


def calculate_min_off_duty(
    appendix: str,
    preceding_fdp_duration_hours: float,
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
) -> dict:
    """
    Calculate the minimum required off-duty period.

    Returns a dict matching the MinOffDutyResponse model shape.
    """
    config = OFF_DUTY_CONFIGS.get(appendix)
    if config is None:
        raise ValueError(f"Unknown appendix: {appendix}")

    notes: list[str] = []

    # ─── Total duty calculation ───────────────────────────────────
    total_duty = preceding_fdp_duration_hours + post_fdp_duty_hours
    notes.append(f"FDP + post-FDP duty = {total_duty}h")

    # ─── Apply split duty credit (before base calc) ───────────────
    split_credit = 0.0
    split_credit_clause = None
    effective_duration = total_duty

    if split_duty_duration_hours and split_duty_accommodation == "sleeping":
        split_credit, split_credit_clause = _calc_split_credit(
            config, appendix, split_duty_duration_hours,
            split_duty_overlaps_night, notes,
        )
        effective_duration = total_duty - split_credit

    exceeds_threshold = effective_duration > config.threshold_hours
    notes.append(
        f"Effective duration = {effective_duration}h "
        f"({'>' if exceeds_threshold else '<='}{config.threshold_hours}h)"
    )

    # ─── Calculate base minimum by type ───────────────────────────
    if config.calc_type == "simple_fixed":
        return _calc_simple_fixed(config, total_duty, notes)

    elif config.calc_type == "home_away":
        base, clause = _calc_home_away(
            config, effective_duration, exceeds_threshold, location, notes,
        )

    elif config.calc_type == "home_away_displacement":
        base, clause = _calc_home_away_displacement(
            config, effective_duration, exceeds_threshold, location,
            acclimatisation_state, notes,
        )

    elif config.calc_type == "night_branching":
        base, clause = _calc_night_branching(
            config, effective_duration, exceeds_threshold,
            was_extended, extension_hours, notes,
        )

    elif config.calc_type == "formula":
        base, clause = _calc_formula(config, effective_duration, exceeds_threshold, notes)

    else:
        raise ValueError(f"Unknown calc_type: {config.calc_type}")

    # ─── Check reduction eligibility ──────────────────────────────
    reduction = _check_reduction(
        config, base, location, preceding_odp_duration_hours,
        preceding_odp_included_night, following_includes_local_night,
        was_extended, acclimatisation_state, notes,
    )

    # ─── Determine final minimum ──────────────────────────────────
    final_min = base
    if reduction and reduction["eligible"] and reduction["reduced_min_odp_hours"] is not None:
        final_min = reduction["reduced_min_odp_hours"]
        notes.append(
            f"Reduction {reduction['clause']} eligible: "
            f"may reduce to {final_min}h subject to conditions"
        )

    return {
        "appendix": appendix,
        "fdp_plus_post_duty_hours": total_duty,
        "exceeds_12h": exceeds_threshold,
        "base_min_odp_hours": base,
        "clause": clause,
        "split_duty_credit_hours": split_credit,
        "split_duty_credit_clause": split_credit_clause,
        "effective_duration_for_calc_hours": effective_duration,
        "reduction_applicable": reduction,
        "final_min_odp_hours": final_min,
        "calculation_notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════
# Calculation type handlers
# ═══════════════════════════════════════════════════════════════════════

def _calc_simple_fixed(config: OffDutyConfig, total_duty: float, notes: list[str]) -> dict:
    """Simple fixed minimum (Appendices 1, 4A, 5A)."""
    base = config.fixed_min_hours
    notes.append(f"Fixed minimum off-duty: {base}h ({config.clause})")
    return {
        "appendix": config.appendix,
        "fdp_plus_post_duty_hours": total_duty,
        "exceeds_12h": total_duty > 12,
        "base_min_odp_hours": base,
        "clause": config.clause,
        "split_duty_credit_hours": 0.0,
        "split_duty_credit_clause": None,
        "effective_duration_for_calc_hours": total_duty,
        "reduction_applicable": None,
        "final_min_odp_hours": base,
        "calculation_notes": notes,
    }


def _calc_home_away(
    config: OffDutyConfig,
    total_duty: float,
    exceeds_threshold: bool,
    location: str,
    notes: list[str],
) -> tuple[float, str]:
    """Home/away branching without displacement (Appendix 3)."""
    if exceeds_threshold:
        excess = total_duty - config.threshold_hours
        base = config.over_threshold_base_hours + config.over_threshold_multiplier * excess
        clause = f"{config.clause}.1b"
        notes.append(
            f">{config.threshold_hours}h -> {config.over_threshold_base_hours}h + "
            f"{config.over_threshold_multiplier} x {excess}h excess = {base}h ({clause})"
        )
    elif location == "away":
        base = config.base_away_hours
        clause = f"{config.clause}.1a"
        notes.append(f"Away from home base -> base {base}h ({clause})")
    else:
        base = config.base_home_hours
        clause = f"{config.clause}.1a"
        notes.append(f"At home base -> base {base}h ({clause})")

    return base, clause


def _calc_home_away_displacement(
    config: OffDutyConfig,
    total_duty: float,
    exceeds_threshold: bool,
    location: str,
    acclim_state: str,
    notes: list[str],
) -> tuple[float, str]:
    """Home/away with displacement time (Appendices 2, 4)."""
    base, clause = _calc_home_away(config, total_duty, exceeds_threshold, location, notes)

    # Displacement time is provided by the caller's context; the calculator
    # notes it as applicable but cannot compute it without timezone data.
    if config.displacement_time:
        notes.append(
            "Displacement time may apply: add excess displacement hours "
            f"(west >{config.displacement_west_threshold}h, "
            f"east >{config.displacement_east_threshold}h) to base ODP"
        )

    return base, clause


def _calc_night_branching(
    config: OffDutyConfig,
    total_duty: float,
    exceeds_threshold: bool,
    was_extended: bool,
    extension_hours: float,
    notes: list[str],
) -> tuple[float, str]:
    """Night window branching with extension penalty (Appendices 4B, 5)."""
    # The night window check depends on whether the FDP included 2300-0559.
    # For calculation purposes, we use the base_without_night as default
    # since the caller can specify which applies. Using the more conservative.
    base = config.base_without_night_hours
    clause = f"{config.clause}.1"
    notes.append(f"Base ODP: {base}h ({clause})")

    # Add excess over threshold
    if exceeds_threshold and config.over_threshold_multiplier > 0:
        excess = total_duty - config.threshold_hours
        addition = config.over_threshold_multiplier * excess
        base += addition
        notes.append(
            f"Excess over {config.threshold_hours}h: +{addition}h"
        )

    # Extension penalty
    if was_extended and extension_hours > 0 and config.extension_penalty_hours_per_30min > 0:
        penalty_units = extension_hours / 0.5  # per 30 minutes
        penalty = penalty_units * config.extension_penalty_hours_per_30min
        base += penalty
        notes.append(
            f"Extension penalty: {extension_hours}h extension -> +{penalty}h ODP"
        )

    return base, clause


def _calc_formula(
    config: OffDutyConfig,
    total_duty: float,
    exceeds_threshold: bool,
    notes: list[str],
) -> tuple[float, str]:
    """Formula-based calculation (Appendix 6)."""
    if exceeds_threshold:
        excess = total_duty - config.threshold_hours
        base = config.over_threshold_base_hours + config.over_threshold_multiplier * excess
        clause = f"{config.clause}.1"
        notes.append(
            f">{config.threshold_hours}h -> {config.over_threshold_base_hours}h + "
            f"{config.over_threshold_multiplier} x {excess}h = {base}h ({clause})"
        )
    else:
        base = config.fixed_min_hours
        clause = f"{config.clause}.1"
        notes.append(f"<={config.threshold_hours}h -> base {base}h ({clause})")

    return base, clause


# ═══════════════════════════════════════════════════════════════════════
# Split duty credit
# ═══════════════════════════════════════════════════════════════════════

def _calc_split_credit(
    config: OffDutyConfig,
    appendix: str,
    duration: float,
    overlaps_night: bool,
    notes: list[str],
) -> tuple[float, str | None]:
    """Calculate split duty credit for ODP reduction."""
    from app.data.fdp_tables import FDP_CONFIGS

    fdp_config = FDP_CONFIGS.get(appendix)
    if fdp_config is None:
        return 0.0, None

    sd_rules = fdp_config.split_duty

    # Night overlap cancels credit for some appendices
    if overlaps_night and sd_rules.night_overlap_credit_reduction:
        notes.append("Split duty with night overlap: no ODP credit reduction")
        return 0.0, None

    credit = sd_rules.split_duty_odp_credit_hours
    if credit > 0:
        clause = f"§{'4' if appendix == '2' else '3'}.2"
        notes.append(
            f"Split duty credit: -{credit}h from effective FDP for ODP calc ({clause})"
        )
        return credit, clause

    # Appendix 4B: 50% of rest duration
    if appendix == "4B":
        credit = duration * 0.5
        clause = "§2.credit"
        notes.append(
            f"Split duty credit: 50% of {duration}h = -{credit}h ({clause})"
        )
        return credit, clause

    return 0.0, None


# ═══════════════════════════════════════════════════════════════════════
# Reduction eligibility
# ═══════════════════════════════════════════════════════════════════════

def _check_reduction(
    config: OffDutyConfig,
    base_min: float,
    location: str,
    preceding_odp_hours: float | None,
    preceding_odp_night: bool,
    following_night: bool,
    was_extended: bool,
    acclim_state: str,
    notes: list[str],
) -> dict | None:
    """Check if ODP reduction conditions are met."""
    reductions = config.reductions

    # Check 9h reduction (Appendices 2, 3, 4)
    if reductions.reduction_to_9h:
        conditions_met = []
        eligible = True

        if preceding_odp_hours is not None and preceding_odp_hours >= 12 and preceding_odp_night:
            conditions_met.append("Previous ODP >=12h including local night")
        else:
            eligible = False

        if following_night:
            conditions_met.append("ODP over a local night")
        else:
            eligible = False

        if location == "away":
            conditions_met.append("ODP away from home base")
        else:
            eligible = False

        # Next ODP check — caller must verify
        conditions_met.append("Next ODP >=12h including local night (caller must verify)")

        if eligible:
            return {
                "eligible": True,
                "clause": reductions.reduction_to_9h_clause,
                "conditions_met": conditions_met,
                "reduced_min_odp_hours": 9.0,
            }

    # Check 14h reduction (Appendices 2, 3, 4)
    if reductions.reduction_to_14h and base_min > 14:
        conditions_met = []
        eligible = True

        if location == "away":
            conditions_met.append("Away from home base")
        else:
            eligible = False

        if not was_extended:
            conditions_met.append("FDP not extended beyond limit")
        else:
            eligible = False

        conditions_met.append("Subsequent ODP >=36h with 2 local nights (caller must verify)")

        if eligible:
            return {
                "eligible": True,
                "clause": reductions.reduction_to_14h_clause,
                "conditions_met": conditions_met,
                "reduced_min_odp_hours": 14.0,
            }

    # Check 12h reduction (Appendices 4B, 5)
    if reductions.reduction_to_12h and base_min > 12:
        return {
            "eligible": True,
            "clause": reductions.reduction_to_12h_clause,
            "conditions_met": list(reductions.reduction_to_12h_conditions),
            "reduced_min_odp_hours": 12.0,
        }

    return None
