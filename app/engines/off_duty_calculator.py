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
    fdp_commencement_utc_offset_hours: float | None = None,
    following_off_duty_utc_offset_hours: float | None = None,
) -> dict:
    """
    Calculate the minimum required off-duty period.

    Parameters
    ----------
    fdp_commencement_utc_offset_hours : float, optional
        UTC offset of local time at the place the FDP commenced.
    following_off_duty_utc_offset_hours : float, optional
        UTC offset of local time at the place the following off-duty period is
        taken. Supplied together with the above, these let the API derive
        displacement time per the §6 definition — "the difference in local time
        between (a) the place where an FCM commenced an FDP; and (b) the place
        where the FCM undertakes an off-duty period following the FDP".

        Taking offsets rather than a pre-computed figure removes a class of
        caller error: west and east are easy to transpose, and transposing them
        shortens the required rest.

    Returns
    -------
    dict
        Matching the MinOffDutyResponse model shape.
    """
    config = OFF_DUTY_CONFIGS.get(appendix)
    if config is None:
        raise ValueError(f"Unknown appendix: {appendix}")

    notes: list[str] = []

    # ─── Derive displacement time from the two offsets ────────────────
    displacement_hours, displacement_direction = _derive_displacement(
        fdp_commencement_utc_offset_hours,
        following_off_duty_utc_offset_hours,
        notes,
    )

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
            config, effective_duration, exceeds_threshold, location,
            acclimatisation_state, notes,
        )

    elif config.calc_type == "home_away_displacement":
        base, clause = _calc_home_away_displacement(
            config, effective_duration, exceeds_threshold, location,
            acclimatisation_state, displacement_hours, displacement_direction,
            notes,
        )

    elif config.calc_type == "night_branching":
        base, clause = _calc_night_branching(
            config, effective_duration, exceeds_threshold,
            was_extended, extension_hours,
            displacement_hours, displacement_direction, acclimatisation_state,
            notes,
        )

    elif config.calc_type == "formula":
        base, clause = _calc_formula(config, effective_duration, exceeds_threshold, notes)

    else:
        raise ValueError(f"Unknown calc_type: {config.calc_type}")

    # ─── Check reduction eligibility ──────────────────────────────
    # effective_duration — the figure AFTER any split-duty credit — is what the
    # §10.3 / §8.3 ten-hour ceiling tests. §3.2 (and §4.2 under Appendix 2) says
    # the credit applies "in determining the subsequent off-duty period ... under
    # clause 8 [or 10]", and the reduction subclause sits inside that clause.
    reduction = _check_reduction(
        config, base, location, preceding_odp_duration_hours,
        preceding_odp_included_night, following_includes_local_night,
        was_extended, acclimatisation_state, effective_duration, notes,
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
# Displacement time
# ═══════════════════════════════════════════════════════════════════════

def _derive_displacement(
    fdp_offset: float | None,
    odp_offset: float | None,
    notes: list[str],
) -> tuple[float | None, str | None]:
    """
    Derive displacement time and direction of travel from two UTC offsets.

    §6: "displacement time means the difference in local time between (a) the
    place where an FCM commenced an FDP; and (b) the place where the FCM
    undertakes an off-duty period following the FDP."

    Travelling to a location with a LARGER UTC offset means local time runs
    further ahead, which is eastward travel.

    Returns
    -------
    (magnitude_hours, direction) or (None, None) if either offset is absent.
    """
    if fdp_offset is None or odp_offset is None:
        return None, None

    delta = float(odp_offset) - float(fdp_offset)
    magnitude = round(abs(delta), 6)

    if magnitude == 0:
        notes.append(
            "Displacement time 0h — the FDP commenced and the off-duty period "
            "is taken on the same clock."
        )
        return 0.0, None

    direction = "east" if delta > 0 else "west"
    notes.append(
        f"Displacement time derived from offsets: UTC{_fmt_offset(fdp_offset)} "
        f"-> UTC{_fmt_offset(odp_offset)} = {magnitude}h {direction} (§6)."
    )
    return magnitude, direction


def _fmt_offset(offset_hours: float) -> str:
    """Render a UTC offset as +8 / +9:30 / -5:45 for the notes."""
    sign = "+" if offset_hours >= 0 else "-"
    magnitude = abs(offset_hours)
    hours = int(magnitude)
    minutes = round((magnitude - hours) * 60)
    return f"{sign}{hours}" if minutes == 0 else f"{sign}{hours}:{minutes:02d}"


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
    acclim_state: str,
    notes: list[str],
) -> tuple[float, str]:
    """
    Home/away branching, with the unknown-state branch where one exists.

    Under Appendix 2 the unknown state is a SEPARATE branch (§10.1(c) and
    §10.2(b)), not a modifier on the acclimatised ones: the base is 14 hours and
    the home base / away distinction does not apply. Appendices 3 and 4 have no
    unknown-state branch, so they fall through to the home/away logic whatever
    state is declared.
    """
    unknown = (
        acclim_state == "unknown"
        and config.unknown_state_base_hours is not None
    )

    if exceeds_threshold:
        excess = total_duty - config.threshold_hours
        if unknown:
            # §10.2(b): 14h + 1.5 x excess.
            base_component = config.unknown_state_over_threshold_base_hours
            clause = config.clause_over_threshold_unknown
            label = "unknown state"
        else:
            # §10.2(a) / §8.2: 12h + 1.5 x excess. No home/away distinction here.
            base_component = config.over_threshold_base_hours
            clause = config.clause_over_threshold
            label = "acclimatised" if config.unknown_state_base_hours else "all states"
        base = base_component + config.over_threshold_multiplier * excess
        notes.append(
            f">{config.threshold_hours}h, {label} -> {base_component}h + "
            f"{config.over_threshold_multiplier} x {excess}h excess = "
            f"{round(base, 4)}h ({clause})"
        )

    elif unknown:
        # §10.1(c): 14h, regardless of home base or away.
        base = config.unknown_state_base_hours
        clause = config.clause_le_threshold_unknown
        notes.append(
            f"Unknown state of acclimatisation -> base {base}h ({clause}). "
            f"This branch has no home base / away distinction."
        )

    elif location == "away":
        base = config.base_away_hours
        clause = config.clause_le_threshold_away
        notes.append(f"Away from home base -> base {base}h ({clause})")

    else:
        base = config.base_home_hours
        clause = config.clause_le_threshold_home
        notes.append(f"At home base -> base {base}h ({clause})")

    return base, clause


def _calc_home_away_displacement(
    config: OffDutyConfig,
    total_duty: float,
    exceeds_threshold: bool,
    location: str,
    acclim_state: str,
    displacement_hours: float | None,
    displacement_direction: str | None,
    notes: list[str],
) -> tuple[float, str]:
    """
    Home/away with displacement time (Appendices 2, 4).

    Displacement is an ADDEND in the instrument, not an optional extra, so where
    it cannot be computed the response says so rather than presenting an
    incomplete figure as a total.
    """
    base, clause = _calc_home_away(
        config, total_duty, exceeds_threshold, location, acclim_state, notes,
    )

    if not config.displacement_time:
        return base, clause

    if displacement_hours is None:
        notes.append(
            "Displacement time NOT included — the figure above is a floor, not "
            "a total. Supply preceding_fdp.commencement_utc_offset_hours and "
            "following_off_duty_utc_offset_hours and the API will compute and "
            "add it."
        )
        return base, clause

    addition, detail = _displacement_addition(
        config, displacement_hours, displacement_direction, acclim_state,
    )
    notes.append(detail)
    return base + addition, clause


def _displacement_addition(
    config: OffDutyConfig,
    displacement_hours: float,
    displacement_direction: str | None,
    acclim_state: str,
) -> tuple[float, str]:
    """
    Work out how much of the displacement time is added.

    Three regimes, and the difference between them matters:

      - Appendix 2 in an UNKNOWN state (§10.1(c)(ii), §10.2(b)(ii)) — the FULL
        displacement time, with no threshold.
      - Appendix 4B (§5.1(a)(iii)/(b)(iii)) — likewise the full amount.
      - Otherwise (§10.1(a)(ii), §10.1(b)(ii), §10.2(a)(ii), §8.1, §8.2) — only
        the amount by which the displacement EXCEEDS 3 hours travelling west or
        2 hours travelling east.

    Returns
    -------
    (hours_to_add, note)
    """
    magnitude = abs(displacement_hours)
    unknown = (
        acclim_state == "unknown"
        and config.unknown_state_base_hours is not None
    )

    if unknown or config.displacement_full_always:
        reason = (
            "unknown state of acclimatisation" if unknown
            else f"Appendix {config.appendix}"
        )
        return magnitude, (
            f"Displacement time {magnitude}h added in full ({reason} takes the "
            f"whole displacement, not just the excess)."
        )

    threshold = (
        config.displacement_west_threshold if displacement_direction == "west"
        else config.displacement_east_threshold
    )
    excess = max(magnitude - threshold, 0.0)
    if excess > 0:
        detail = (
            f"Displacement time {magnitude}h {displacement_direction} exceeds "
            f"the {threshold}h threshold by {round(excess, 4)}h — added."
        )
    else:
        detail = (
            f"Displacement time {magnitude}h {displacement_direction} does not "
            f"exceed the {threshold}h threshold — nothing added."
        )
    return excess, detail


def _calc_night_branching(
    config: OffDutyConfig,
    total_duty: float,
    exceeds_threshold: bool,
    was_extended: bool,
    extension_hours: float,
    displacement_hours: float | None,
    displacement_direction: str | None,
    acclim_state: str,
    notes: list[str],
) -> tuple[float, str]:
    """
    Night window branching with extension penalty (Appendices 4B, 5).

    The night window check depends on whether the off-duty period includes
    2300-0559 local time. The conservative base (the longer, not-including-night
    figure) is used because the caller does not currently declare which applies.
    """
    base = config.base_without_night_hours
    clause = f"{config.clause}.1"
    notes.append(f"Base ODP: {base}h ({clause})")

    # Excess over the threshold. Appendix 4B §5.1(a)(ii) adds the excess;
    # Appendix 5 §5.1 has no such term, which is why its multiplier is zero.
    if exceeds_threshold and config.over_threshold_multiplier > 0:
        excess = total_duty - config.threshold_hours
        addition = config.over_threshold_multiplier * excess
        base += addition
        notes.append(f"Excess over {config.threshold_hours}h: +{addition}h")

    # Displacement time — Appendix 4B only among the night-branching appendices.
    if config.displacement_time:
        if displacement_hours is None:
            notes.append(
                "Displacement time NOT included — the figure above is a floor, "
                "not a total. Supply "
                "preceding_fdp.commencement_utc_offset_hours and "
                "following_off_duty_utc_offset_hours and the API will compute "
                "and add it."
            )
        else:
            addition, detail = _displacement_addition(
                config, displacement_hours, displacement_direction, acclim_state,
            )
            base += addition
            notes.append(detail)

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
    effective_duty_hours: float | None,
    notes: list[str],
) -> dict | None:
    """
    Check if ODP reduction conditions are met.

    Parameters
    ----------
    effective_duty_hours : float, optional
        FDP plus other duty time, after any split-duty credit. This is what the
        §10.3 / §8.3 ten-hour ceiling is measured against — see the call site.
    """
    reductions = config.reductions

    # ─── 9-hour reduction (§10.3 / §8.3) ──────────────────────────────
    if reductions.reduction_to_9h:
        conditions_met = []
        eligible = True

        # §10.3 / §8.3 open with a cap on the duty that preceded the rest:
        # "if the sum of an FCM's FDP, and his or her duty time (if any) ...
        # does not exceed 10 hours". Without this the reduction was being
        # offered after duties of any length.
        if (
            effective_duty_hours is not None
            and effective_duty_hours > reductions.reduction_to_9h_max_duty_hours
        ):
            eligible = False
            notes.append(
                f"Reduction {reductions.reduction_to_9h_clause} not available: "
                f"FDP + other duty is {effective_duty_hours}h after any "
                f"split-duty credit, which exceeds the "
                f"{reductions.reduction_to_9h_max_duty_hours}h ceiling in that "
                f"subclause."
            )
        else:
            conditions_met.append(
                f"FDP + other duty time does not exceed "
                f"{reductions.reduction_to_9h_max_duty_hours}h"
            )

        if preceding_odp_hours is not None and preceding_odp_hours >= 12 and preceding_odp_night:
            conditions_met.append("Previous ODP >=12h including local night")
        else:
            eligible = False

        # §10.3(b), Appendix 2 only: the FCM must be acclimatised at the
        # commencement of ODP 2. An unknown-state FCM cannot take this reduction.
        if reductions.reduction_to_9h_requires_acclimatised:
            if acclim_state == "acclimatised":
                conditions_met.append("FCM acclimatised at commencement of ODP 2")
            else:
                eligible = False
                notes.append(
                    f"Reduction {reductions.reduction_to_9h_clause} not "
                    f"available: it requires the FCM to be acclimatised at the "
                    f"commencement of the off-duty period, and the declared "
                    f"state is '{acclim_state}'."
                )

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

    # ─── 14-hour reduction (§10.4 / §8.4) ─────────────────────────────
    if reductions.reduction_to_14h and base_min > 14:
        conditions_met = ["Calculated ODP exceeds 14 hours"]
        eligible = True

        if location == "away":
            conditions_met.append("Away from home base")
        else:
            eligible = False

        if not was_extended:
            conditions_met.append("FDP not extended beyond limit")
        else:
            eligible = False

        # §10.4(c), Appendix 2 only: the FCM must commence the second FDP in an
        # acclimatised state.
        if reductions.reduction_to_14h_requires_acclimatised:
            if acclim_state == "acclimatised":
                conditions_met.append(
                    "FCM commences the second FDP in an acclimatised state"
                )
            else:
                eligible = False
                notes.append(
                    f"Reduction {reductions.reduction_to_14h_clause} not "
                    f"available: it requires the FCM to commence the second FDP "
                    f"in an acclimatised state, and the declared state is "
                    f"'{acclim_state}'."
                )

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
