"""
Off-duty period (ODP) calculator engine.

Pure calculation functions for determining the minimum required off-duty period
given a preceding FDP and its parameters.

Three principles govern this module:

1. **A concession is never applied on the API's own initiative.** The reduction
   provisions (§8.3/§8.4, §10.3/§10.4) say the ODP "may be reduced ... provided
   that". `final_min_odp_hours` is therefore always the unreduced minimum, and
   the reduction is reported alongside it as an available option. The caller
   claims it explicitly, or it does not apply.

2. **A condition the API cannot check is never counted as met.** Conditions
   split into `conditions_verified` and `conditions_caller_must_verify`;
   eligibility is decided by the first list alone.

3. **Each appendix owns its own rules.** Appendix 2 branches on acclimatisation
   and adds displacement time; Appendix 4 adds displacement but does not branch;
   Appendix 3 does neither.

All logic derived from CAO 48.1 Instrument 2019 (Compilation No. 3, F2021C01239),
verified against the text served by GET /sections/{id}.
"""

from app.data.off_duty_rules import OFF_DUTY_CONFIGS, OdpCondition, OffDutyConfig


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
    fdp_start_offset_hours: float | None = None,
    odp_start_offset_hours: float | None = None,
) -> dict:
    """
    Calculate the minimum required off-duty period.

    Returns a dict matching the MinOffDutyResponse model shape.

    `final_min_odp_hours` is the minimum required *before* any reduction
    provision is claimed. Where a reduction is available it appears in
    `reduction_applicable`; applying it is the caller's decision, validated by
    validate_off_duty when `reduction_claimed` is set.
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
    displacement: dict | None = None

    if config.calc_type == "simple_fixed":
        return _calc_simple_fixed(config, total_duty, notes)

    elif config.calc_type == "home_away":
        base, clause = _calc_home_away(
            config, effective_duration, exceeds_threshold, location,
            acclimatisation_state, notes,
        )

    elif config.calc_type == "home_away_displacement":
        base, clause, displacement = _calc_home_away_displacement(
            config, effective_duration, exceeds_threshold, location,
            acclimatisation_state, fdp_start_offset_hours,
            odp_start_offset_hours, notes,
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

    # Every appendix reports a displacement block, so a consumer can tell
    # "this appendix has no displacement rule" from "not computed" from
    # "computed as zero". Only home_away_displacement folds it into the base.
    if displacement is None:
        displacement = _displacement_not_modelled(config)

    # ─── Check reduction eligibility ──────────────────────────────
    reduction = _check_reduction(
        config, base, effective_duration, location, preceding_odp_duration_hours,
        preceding_odp_included_night, following_includes_local_night,
        was_extended, acclimatisation_state, notes,
    )

    # ─── Determine the required minimum ───────────────────────────
    # The reduction is an option the caller may claim, never a default. The
    # figure an integrator reads must be the one the legislation requires
    # absent a claim.
    final_min = base
    if reduction is not None and reduction["eligible"]:
        notes.append(
            f"Reduction {reduction['clause']} is available: the minimum may be "
            f"reduced to {reduction['reduced_min_odp_hours']}h if claimed and "
            f"if the caller-verified conditions hold. Not applied here — "
            f"final_min_odp_hours remains the unreduced minimum."
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
        "displacement": displacement,
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
    clause = config.clause_under_threshold_away or config.clause
    notes.append(f"Fixed minimum off-duty: {base}h ({clause})")
    return {
        "appendix": config.appendix,
        "fdp_plus_post_duty_hours": total_duty,
        "exceeds_12h": total_duty > 12,
        "base_min_odp_hours": base,
        "clause": clause,
        "split_duty_credit_hours": 0.0,
        "split_duty_credit_clause": None,
        "effective_duration_for_calc_hours": total_duty,
        "displacement": _displacement_not_modelled(config),
        "reduction_applicable": None,
        "final_min_odp_hours": base,
        "calculation_notes": notes,
    }


def _calc_home_away(
    config: OffDutyConfig,
    total_duty: float,
    exceeds_threshold: bool,
    location: str,
    acclim_state: str,
    notes: list[str],
) -> tuple[float, str]:
    """
    Home/away branching (Appendices 3, 4), with Appendix 2's acclimatisation
    branch layered on where the config enables it.

    Under App 2 §10.1(c) and §10.2(b) an unknown state of acclimatisation
    ignores home base / away entirely — the location branch does not apply.
    """
    unknown = config.acclimatisation_branching and acclim_state == "unknown"

    if exceeds_threshold:
        excess = total_duty - config.threshold_hours
        if unknown:
            base_hours = config.unknown_over_threshold_base_hours
            clause = config.clause_over_threshold_unknown or config.clause_over_threshold
        else:
            base_hours = config.over_threshold_base_hours
            clause = config.clause_over_threshold
        base = base_hours + config.over_threshold_multiplier * excess
        notes.append(
            f">{config.threshold_hours}h -> {base_hours}h + "
            f"{config.over_threshold_multiplier} x {excess}h excess = {base}h ({clause})"
        )
        return base, clause

    if unknown:
        base = config.unknown_base_hours
        clause = config.clause_under_threshold_unknown or config.clause_under_threshold_away
        notes.append(
            f"Unknown state of acclimatisation -> base {base}h ({clause}). "
            "Home base / away does not apply under this branch."
        )
        return base, clause

    if location == "away":
        base = config.base_away_hours
        clause = config.clause_under_threshold_away
        notes.append(f"Away from home base -> base {base}h ({clause})")
    else:
        base = config.base_home_hours
        clause = config.clause_under_threshold_home
        notes.append(f"At home base -> base {base}h ({clause})")

    return base, clause


def _calc_home_away_displacement(
    config: OffDutyConfig,
    total_duty: float,
    exceeds_threshold: bool,
    location: str,
    acclim_state: str,
    fdp_start_offset_hours: float | None,
    odp_start_offset_hours: float | None,
    notes: list[str],
) -> tuple[float, str, dict]:
    """Home/away with displacement time (Appendices 2, 4)."""
    base, clause = _calc_home_away(
        config, total_duty, exceeds_threshold, location, acclim_state, notes,
    )

    displacement = _calc_displacement(
        config, acclim_state, fdp_start_offset_hours, odp_start_offset_hours, notes,
    )
    base += displacement["added_hours"]

    return base, clause, displacement


def _displacement_not_modelled(config: OffDutyConfig) -> dict:
    """
    Displacement block for calculation paths that do not fold it into the base.

    Appendices 3, 5, 6 and the fixed-minimum appendices have no displacement
    rule at all. Appendix 4B does (§5 references it) but its night-branching
    formula does not model it here — that is reported as unavailable rather
    than as inapplicable, so the gap is visible instead of implied.
    """
    if config.displacement_time:
        return {
            "applicable": True,
            "status": "data_unavailable",
            "displacement_hours": None,
            "direction": None,
            "added_hours": 0.0,
            "detail": (
                f"Appendix {config.appendix} applies displacement time, but it "
                "is not modelled on this calculation path. The returned minimum "
                "is a lower bound and may be understated."
            ),
        }
    return {
        "applicable": False,
        "status": "not_applicable",
        "displacement_hours": None,
        "direction": None,
        "added_hours": 0.0,
        "detail": f"Appendix {config.appendix} does not apply displacement time.",
    }


def _calc_displacement(
    config: OffDutyConfig,
    acclim_state: str,
    fdp_start_offset_hours: float | None,
    odp_start_offset_hours: float | None,
    notes: list[str],
) -> dict:
    """
    Compute displacement time and the hours it adds to the base ODP.

    Displacement is the time-zone shift between the start of the FDP and the
    start of the following off-duty period. An acclimatised FCM adds only the
    amount exceeding 3 hours west / 2 hours east; an FCM in an unknown state
    adds the full amount (§10.1(c)(ii), §10.2(b)(ii)).

    Where the caller supplies no offsets this cannot be computed. The base
    figure is then a genuine lower bound — displacement only ever adds — and
    the result says so as structured data rather than as a prose note, so a
    consumer can tell a computed zero from an unknown.
    """
    if not config.displacement_time:
        return {
            "applicable": False,
            "status": "not_applicable",
            "displacement_hours": None,
            "direction": None,
            "added_hours": 0.0,
            "detail": f"Appendix {config.appendix} does not apply displacement time.",
        }

    if fdp_start_offset_hours is None or odp_start_offset_hours is None:
        notes.append(
            "Displacement time could not be computed: supply "
            "fdp_start_offset_hours and odp_start_offset_hours. The minimum "
            "below is a lower bound — displacement can only increase it."
        )
        return {
            "applicable": True,
            "status": "data_unavailable",
            "displacement_hours": None,
            "direction": None,
            "added_hours": 0.0,
            "detail": (
                "Displacement time not computed — fdp_start_offset_hours and "
                "odp_start_offset_hours were not both supplied. The returned "
                "minimum is a lower bound and may be understated."
            ),
        }

    # Travelling east increases the UTC offset; travelling west decreases it.
    shift = odp_start_offset_hours - fdp_start_offset_hours
    magnitude = abs(shift)
    direction = "east" if shift > 0 else "west" if shift < 0 else "none"

    if acclim_state == "unknown" and config.acclimatisation_branching:
        added = magnitude
        rule = "unknown state of acclimatisation — the full displacement time applies"
    else:
        threshold = (
            config.displacement_west_threshold
            if direction == "west"
            else config.displacement_east_threshold
        )
        added = max(0.0, magnitude - threshold)
        rule = (
            f"acclimatised — only the amount exceeding {threshold}h "
            f"{direction if direction != 'none' else 'either way'} applies"
        )

    added = round(added, 4)
    notes.append(
        f"Displacement time {magnitude}h {direction} ({rule}): +{added}h"
    )
    return {
        "applicable": True,
        "status": "computed",
        "displacement_hours": round(magnitude, 4),
        "direction": direction,
        "added_hours": added,
        "detail": f"Displacement time {magnitude}h {direction}; {rule}; +{added}h.",
    }


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
    clause = config.clause_under_threshold_away or f"{config.clause}.1"
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
    clause = config.clause_over_threshold
    if exceeds_threshold:
        excess = total_duty - config.threshold_hours
        base = config.over_threshold_base_hours + config.over_threshold_multiplier * excess
        notes.append(
            f">{config.threshold_hours}h -> {config.over_threshold_base_hours}h + "
            f"{config.over_threshold_multiplier} x {excess}h = {base}h ({clause})"
        )
    else:
        base = config.fixed_min_hours
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

    # A night-overlapping split rest forfeits the credit (App 3 §3.4(c)).
    if overlaps_night and sd_rules.night_overlap_credit_reduction:
        notes.append("Split duty with night overlap: no ODP credit reduction")
        return 0.0, None

    credit = sd_rules.split_duty_odp_credit_hours
    if credit > 0:
        clause = "§4.2" if appendix == "2" else "§3.2"
        notes.append(
            f"Split duty credit: -{credit}h from effective FDP for ODP calc ({clause})"
        )
        return credit, clause

    # Appendix 4B: 50% of rest duration
    if appendix == "4B":
        credit = duration * 0.5
        clause = "§2.2"
        notes.append(
            f"Split duty credit: 50% of {duration}h = -{credit}h ({clause})"
        )
        return credit, clause

    return 0.0, None


# ═══════════════════════════════════════════════════════════════════════
# Reduction eligibility
# ═══════════════════════════════════════════════════════════════════════

def _evaluate_condition(
    condition: OdpCondition,
    *,
    location: str,
    preceding_odp_hours: float | None,
    preceding_odp_night: bool,
    following_night: bool,
    was_extended: bool,
    acclim_state: str,
    base_min: float,
) -> bool:
    """Evaluate one verifiable condition against the supplied data."""
    if condition.key == "preceding_odp_12h_with_local_night":
        return (
            preceding_odp_hours is not None
            and preceding_odp_hours >= 12
            and preceding_odp_night
        )
    if condition.key == "odp_over_local_night":
        return following_night
    if condition.key == "away_from_home_base":
        return location == "away"
    if condition.key == "fdp_not_extended":
        return not was_extended
    if condition.key == "acclimatised":
        return acclim_state == "acclimatised"
    if condition.key == "calculated_over_12h":
        return base_min > 12
    raise ValueError(f"Unknown condition key: {condition.key!r}")


def _assess(
    conditions: tuple[OdpCondition, ...],
    clause: str,
    reduced_to: float,
    **context,
) -> dict:
    """
    Assess a reduction provision's conditions.

    Verified conditions decide eligibility. Conditions the API cannot check are
    listed separately for the caller and never contribute to `eligible` — a
    concession may not be granted on the strength of an unverifiable fact.
    """
    verified: list[dict] = []
    failed: list[dict] = []
    caller_must_verify: list[dict] = []

    for condition in conditions:
        entry = {"clause": condition.clause, "description": condition.description}
        if not condition.verifiable:
            caller_must_verify.append(entry)
            continue
        if _evaluate_condition(condition, **context):
            verified.append(entry)
        else:
            failed.append(entry)

    eligible = not failed

    if eligible:
        reason = (
            f"All conditions the API can check are satisfied. "
            f"{len(caller_must_verify)} condition(s) remain for the caller to "
            f"verify before the reduction may be relied on."
        )
    else:
        reason = "Not eligible — " + "; ".join(
            f"{item['clause']} not satisfied" for item in failed
        )

    return {
        "eligible": eligible,
        "clause": clause,
        "reduced_min_odp_hours": reduced_to if eligible else None,
        "conditions_verified": verified,
        "conditions_failed": failed,
        "conditions_caller_must_verify": caller_must_verify,
        # Deprecated alias, retained for existing consumers. Contains verified
        # conditions only — never a caller-must-verify entry.
        "conditions_met": [item["description"] for item in verified],
        "reason": reason,
    }


def _check_reduction(
    config: OffDutyConfig,
    base_min: float,
    effective_duration: float,
    location: str,
    preceding_odp_hours: float | None,
    preceding_odp_night: bool,
    following_night: bool,
    was_extended: bool,
    acclim_state: str,
    notes: list[str],
) -> dict | None:
    """Check whether an ODP reduction provision is available."""
    reductions = config.reductions
    context = dict(
        location=location,
        preceding_odp_hours=preceding_odp_hours,
        preceding_odp_night=preceding_odp_night,
        following_night=following_night,
        was_extended=was_extended,
        acclim_state=acclim_state,
        base_min=base_min,
    )

    # ─── 9h reduction (App 2 §10.3, App 3 §8.3, App 4 §8.3) ───────────
    # "Despite subclause X.1, if the sum of FDP and other duty time does not
    # exceed 10 hours..." — the provision is gated on the duty total, and it
    # displaces X.1 only. It can never reach a minimum derived from X.2.
    if reductions.reduction_to_9h:
        gate = reductions.reduction_to_9h_max_duty_hours
        if effective_duration <= gate:
            assessment = _assess(
                reductions.reduction_to_9h_conditions,
                reductions.reduction_to_9h_clause,
                9.0,
                **context,
            )
            if assessment["eligible"]:
                return assessment
            nine_hour_assessment = assessment
        else:
            notes.append(
                f"{reductions.reduction_to_9h_clause} not available: FDP plus "
                f"other duty time is {effective_duration}h, which exceeds the "
                f"{gate}h ceiling on this provision."
            )
            nine_hour_assessment = None
    else:
        nine_hour_assessment = None

    # ─── 14h reduction (App 2 §10.4, App 3 §8.4, App 4 §8.4) ──────────
    if reductions.reduction_to_14h and base_min > 14:
        assessment = _assess(
            reductions.reduction_to_14h_conditions,
            reductions.reduction_to_14h_clause,
            14.0,
            **context,
        )
        return assessment

    # ─── 12h reduction (App 4B, App 5) ────────────────────────────────
    if reductions.reduction_to_12h and base_min > 12:
        return _assess(
            reductions.reduction_to_12h_conditions,
            reductions.reduction_to_12h_clause,
            12.0,
            **context,
        )

    # Report an ineligible 9h assessment where nothing else applied, so the
    # caller sees which condition blocked it rather than a bare null.
    return nine_hour_assessment
