"""
FDP (Flight Duty Period) calculator engine.

Pure calculation functions with no HTTP concerns. Takes operational parameters,
looks up the correct FDP table, applies adjustments (split duty, WOCL/early
start reductions), and returns a clause-referenced audit trail.

All logic derived from CAO 48.1 Instrument 2019 (Compilation No. 3, F2021C01239).
"""

from datetime import datetime

from app.models._validators import validate_utc_offset
from app.data.fdp_tables import (
    AppendixFdpConfig,
    EarlyStartRules,
    ExtensionRules,
    FdpTable,
    FdpTableRow,
    FDP_CONFIGS,
    SplitDutyRules,
    resolve_sector_key_6col,
    resolve_sector_key_3col,
    _hm,
)


def calculate_max_fdp(
    appendix: str,
    fdp_start_utc: str,
    local_time_offset_hours: float,
    sectors: int,
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
    Calculate the maximum permissible FDP given operational parameters.

    Returns a dict matching the MaxFdpResponse model shape.
    """
    config = FDP_CONFIGS.get(appendix)
    if config is None:
        raise ValueError(f"Unknown appendix: {appendix}")

    notes: list[str] = []
    adjustments: list[dict] = []
    violations: list[dict] = []

    # ─── Resolve local start time ─────────────────────────────────
    start_dt = datetime.fromisoformat(fdp_start_utc.replace("Z", "+00:00"))
    local_minutes = _utc_to_local_minutes(start_dt, local_time_offset_hours)
    local_hhmm = f"{local_minutes // 60:02d}{local_minutes % 60:02d}"

    # ─── Determine which time to use for table lookup ─────────────
    if appendix == "2" and acclimatisation_state == "acclimatised" and acclimatised_time_offset_hours is not None:
        lookup_minutes = _utc_to_local_minutes(start_dt, acclimatised_time_offset_hours)
        lookup_label = "acclimatised"
    else:
        lookup_minutes = local_minutes
        lookup_label = "local"

    lookup_hhmm = f"{lookup_minutes // 60:02d}{lookup_minutes % 60:02d}"

    # ─── Select the correct sub-table ─────────────────────────────
    table_key, table = _select_table(
        config, appendix, acclimatisation_state, augmented_crew, split_duty,
    )
    sector_key = _resolve_sector_key(
        table, appendix, sectors, single_pilot, augmented_crew,
    )

    # ─── Look up base FDP ─────────────────────────────────────────
    base_fdp = _lookup_base_fdp(
        table, lookup_minutes, sector_key, appendix,
        preceding_off_duty_hours, split_duty,
    )

    time_band_label = _find_time_band_label(table, lookup_minutes, appendix, preceding_off_duty_hours, split_duty)
    notes.append(
        f"FDP start {lookup_label} time: {lookup_hhmm} -> "
        f"{table.table_id} band {time_band_label}, "
        f"{_sector_description(sector_key)} = {base_fdp}h"
    )

    running_total = base_fdp
    flight_time_limit = table.flight_time_limit_hours

    # ─── Apply WOCL / early start reduction ───────────────────────
    wocl_reduction = 0.0
    if config.wocl_early_start and config.early_starts.available:
        wocl_reduction = _calculate_wocl_reduction(
            config.early_starts, consecutive_early_starts,
            consecutive_wocl_infringements, local_minutes, notes, violations,
        )
        if wocl_reduction > 0:
            running_total -= wocl_reduction
            adjustments.append({
                "clause": config.early_starts.clause_relief,
                "description": (
                    f"{_ordinal(consecutive_early_starts + 1)} consecutive early "
                    f"start: -{wocl_reduction}h reduction"
                ),
                "adjustment_hours": -wocl_reduction,
                "running_total_hours": running_total,
            })

    # ─── Apply split duty extension ───────────────────────────────
    post_split_max = None
    if split_duty and config.split_duty.available:
        sd_result = _apply_split_duty(
            config.split_duty, split_duty, running_total, notes, appendix,
            config, violations,
        )
        if sd_result["extension"] > 0 or sd_result.get("explicit_zero"):
            running_total = sd_result["new_total"]
            adjustments.append({
                "clause": sd_result["clause"],
                "description": sd_result["description"],
                "adjustment_hours": sd_result["extension"],
                "running_total_hours": running_total,
            })
        post_split_max = sd_result.get("post_split_max")

    final_max = running_total

    # ─── Extension allowance ──────────────────────────────────────
    # The default provision is the unforeseen-circumstances extension, keyed
    # on crew composition. An urgent-operations extension (App 4B §3.2) is a
    # separate provision with its own figure and ceiling; validate_fdp selects
    # it when the caller names that type.
    ext_rules = config.extensions
    split_duty_applied = any(a["adjustment_hours"] > 0 for a in adjustments if a is not None) and bool(split_duty)

    if not ext_rules.available:
        max_extension = 0.0
        notes.append(
            f"Appendix {appendix} provides no FDP extension."
        )
    elif augmented_crew is not None and ext_rules.unforeseen_hours_augmented_crew is not None:
        max_extension = ext_rules.unforeseen_hours_augmented_crew
        notes.append(
            f"Extension allowance {max_extension}h for an augmented crew "
            f"operation ({ext_rules.clause_unforeseen_augmented})"
        )
    else:
        max_extension = (
            ext_rules.unforeseen_hours_single_pilot if single_pilot
            else ext_rules.unforeseen_hours_multi_pilot
        )
        notes.append(
            f"Extension allowance {max_extension}h "
            f"({'single-pilot' if single_pilot else 'multi-pilot'}, "
            f"{ext_rules.clause_unforeseen})"
        )

    absolute_max = final_max + max_extension
    if ext_rules.available and max_extension > 0:
        ceiling = _extension_ceiling(ext_rules, "unforeseen", split_duty_applied)
        if ceiling is not None and absolute_max > ceiling:
            notes.append(
                f"Extended FDP capped at {ceiling}h by the proviso attaching to "
                f"{ext_rules.clause_unforeseen}."
            )
            absolute_max = ceiling
        elif ceiling is None:
            notes.append(
                f"{ext_rules.clause_unforeseen} states no explicit ceiling on the "
                f"extended FDP, so absolute_max_with_extension_hours is the sum "
                f"of the limit and the allowance. Clause 'Maximum durations must "
                f"not be exceeded' defers to the AOC holder's operations manual, "
                f"which this API cannot see — the operations manual limit may be "
                f"lower."
            )

    return {
        "appendix": appendix,
        "base_max_fdp_hours": base_fdp,
        "adjustments": adjustments,
        "wocl_early_start_reduction_hours": wocl_reduction,
        "final_max_fdp_hours": final_max,
        "max_extension_hours": max_extension,
        "absolute_max_with_extension_hours": absolute_max,
        "post_split_max_hours": post_split_max,
        "flight_time_limit_hours": flight_time_limit,
        "calculation_notes": notes,
        "violations": violations,
        "extension_options": _extension_options(ext_rules, single_pilot, split_duty_applied),
        "split_duty_applied": split_duty_applied,
    }


def _extension_ceiling(
    rules: ExtensionRules, extension_type: str, split_duty_applied: bool,
) -> float | None:
    """
    The ceiling on the extended FDP for a given provision.

    App 4B §3.1's 16h proviso attaches to §3.1(b) — an extension off a
    split-duty-increased limit — and not to §3.1(a). §3.2's applies to both
    (c) and (d), so it is unconditional.
    """
    if extension_type == "urgent":
        return rules.urgent_ceiling_hours
    if split_duty_applied and rules.unforeseen_ceiling_after_split_duty_hours is not None:
        return rules.unforeseen_ceiling_after_split_duty_hours
    return rules.unforeseen_ceiling_hours


def _extension_options(
    rules: ExtensionRules, single_pilot: bool, split_duty_applied: bool,
) -> dict:
    """Describe every extension provision available under this appendix."""
    if not rules.available:
        return {"available": False, "provisions": [], "conditions_caller_must_verify": []}

    provisions = [{
        "type": "unforeseen",
        "clause": rules.clause_unforeseen,
        "max_hours": (
            rules.unforeseen_hours_single_pilot if single_pilot
            else rules.unforeseen_hours_multi_pilot
        ),
        "extended_fdp_ceiling_hours": _extension_ceiling(
            rules, "unforeseen", split_duty_applied,
        ),
    }]
    if rules.urgent_available:
        provisions.append({
            "type": "urgent",
            "clause": rules.clause_urgent,
            "max_hours": rules.urgent_hours,
            "extended_fdp_ceiling_hours": rules.urgent_ceiling_hours,
        })
    return {
        "available": True,
        "provisions": provisions,
        "conditions_caller_must_verify": [
            {"clause": clause, "description": description}
            for clause, description in rules.caller_must_verify
        ],
        "clause_cumulative_crosscheck": rules.clause_cumulative_crosscheck,
    }


# ═══════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════

def _utc_to_local_minutes(dt: datetime, offset_hours: float) -> int:
    """
    Convert a UTC datetime to local minutes from midnight.

    The modulo below is the legitimate midnight wrap (2300Z at +0800 is 0700
    local the next day) and must stay. What it must NOT do is silently absorb
    an offset that does not exist: at +50 it produced a plausible-looking time
    band from nonsense. Request models reject out-of-range offsets, and this
    guard repeats the check for callers that reach the engines directly.
    """
    validate_utc_offset(offset_hours, "local_time_offset_hours")
    total_minutes = dt.hour * 60 + dt.minute + int(offset_hours * 60)
    return total_minutes % 1440  # midnight wrap


def _select_table(
    config: AppendixFdpConfig,
    appendix: str,
    acclim_state: str,
    augmented_crew: dict | None,
    split_duty: dict | None,
) -> tuple[str, FdpTable]:
    """Select the correct sub-table based on operational parameters."""
    if appendix == "2":
        has_augmented = augmented_crew is not None
        if has_augmented and acclim_state == "acclimatised":
            return "augmented_acclimatised", config.tables["augmented_acclimatised"]
        elif has_augmented and acclim_state == "unknown":
            return "augmented_unknown", config.tables["augmented_unknown"]
        elif acclim_state == "unknown":
            return "unknown", config.tables["unknown"]
        else:
            return "acclimatised", config.tables["acclimatised"]

    # All other appendices use "default"
    return "default", config.tables["default"]


def _resolve_sector_key(
    table: FdpTable,
    appendix: str,
    sectors: int,
    single_pilot: bool,
    augmented_crew: dict | None,
) -> str:
    """Resolve the sector/crew key for table lookup."""
    # Check first row to determine key format
    first_row = table.rows[0]
    if "all" in first_row.sectors:
        return "all"

    if appendix in ("4B", "5"):
        return resolve_sector_key_3col(sectors, single_pilot)

    if appendix == "2" and augmented_crew is not None:
        # Augmented crew tables use class+fcm keys
        rest_class = augmented_crew.get("rest_facility_class", "class_1")
        additional = augmented_crew.get("additional_fcms", 1)
        class_num = rest_class.split("_")[1]  # "class_1" -> "1"
        return f"c{class_num}_{additional}fcm"

    return resolve_sector_key_6col(sectors)


def _lookup_base_fdp(
    table: FdpTable,
    lookup_minutes: int,
    sector_key: str,
    appendix: str,
    preceding_off_duty_hours: float | None = None,
    split_duty: dict | None = None,
) -> float:
    """Look up the base FDP from the table."""
    # Special case: Appendix 4A uses split duty status
    if appendix == "4A":
        row_label = "with_split" if split_duty else "no_split"
        for row in table.rows:
            if row.time_band.label == row_label:
                return row.sectors[sector_key]
        return table.rows[0].sectors[sector_key]

    # Special case: Appendix 2 unknown acclimatisation uses off-duty duration
    if appendix == "2" and table.table_id in ("Table 3.1", "Table 5.2"):
        if preceding_off_duty_hours is not None and preceding_off_duty_hours >= 30:
            return table.rows[1].sectors[sector_key]  # >=30h row
        return table.rows[0].sectors[sector_key]  # <30h row

    # Standard time-band lookup
    for row in table.rows:
        if _minutes_in_band(lookup_minutes, row.time_band.start, row.time_band.end):
            return row.sectors[sector_key]

    # Fallback: use the most conservative (lowest) value
    return min(row.sectors[sector_key] for row in table.rows)


def _minutes_in_band(minutes: int, start: int, end: int) -> bool:
    """Check if minutes falls within a time band (handles midnight wrap)."""
    if start <= end:
        return start <= minutes <= end
    else:
        # Wraps midnight: e.g. 2300-0459
        return minutes >= start or minutes <= end


def _find_time_band_label(
    table: FdpTable,
    lookup_minutes: int,
    appendix: str,
    preceding_off_duty_hours: float | None = None,
    split_duty: dict | None = None,
) -> str:
    """Find the matching time band label for notes."""
    if appendix == "4A":
        return "with_split" if split_duty else "no_split"

    if appendix == "2" and table.table_id in ("Table 3.1", "Table 5.2"):
        if preceding_off_duty_hours is not None and preceding_off_duty_hours >= 30:
            return ">=30h off-duty"
        return "<30h off-duty"

    for row in table.rows:
        if _minutes_in_band(lookup_minutes, row.time_band.start, row.time_band.end):
            return row.time_band.label

    return "unknown"


def _sector_description(sector_key: str) -> str:
    """Human-readable sector description for notes."""
    if sector_key == "all":
        return "all sectors"
    return f"{sector_key} sectors"


def _calculate_wocl_reduction(
    rules: EarlyStartRules,
    consecutive_early_starts: int,
    consecutive_wocl_infringements: int,
    local_minutes: int,
    notes: list[str],
    violations: list[dict],
) -> float:
    """
    Calculate the FDP reduction for consecutive early starts.

    §11.1 / §13.1 / §10.1: an FCM must not be assigned more than 3 consecutive
    early starts. The relief clause permits "a 4th, or a 4th and a 5th", with
    a 2h and 4h reduction. It enumerates a 4th and a 5th and stops there.

    A 6th consecutive early start is prohibited outright. Clamping the
    reduction at 4 hours, which the previous "5th+" branch did, turned a
    prohibition into a permission.
    """
    # Early start: 0500-0659 local
    is_early_start = _hm(5) <= local_minutes <= _hm(6, 59)

    if not is_early_start:
        return 0.0

    # Ordinal of the early start being assessed, counting this one.
    ordinal = consecutive_early_starts + 1
    reductions = dict(rules.reductions)
    max_relieved = max(reductions) if reductions else rules.max_consecutive

    if ordinal <= rules.max_consecutive:
        notes.append(
            f"Early start #{ordinal} of {rules.max_consecutive} permitted "
            f"without reduction ({rules.clause_limit})"
        )
        return 0.0

    if ordinal in reductions:
        reduction = reductions[ordinal]
        notes.append(
            f"{_ordinal(ordinal)} consecutive early start: maximum FDP reduced "
            f"by {reduction}h ({rules.clause_relief})"
        )
        return reduction

    # Beyond the relief clause: the duty itself is prohibited.
    notes.append(
        f"{_ordinal(ordinal)} consecutive early start is prohibited: "
        f"{rules.clause_limit} permits no more than {rules.max_consecutive} "
        f"consecutive early starts, and {rules.clause_relief} extends this to "
        f"a {_ordinal(max_relieved)} at most."
    )
    violations.append({
        "check": "consecutive_early_starts",
        "clause": rules.clause_limit,
        "severity": "hard_limit",
        "actual": float(ordinal),
        "limit": float(max_relieved),
        "detail": (
            f"This FDP would be the {_ordinal(ordinal)} consecutive early "
            f"start. {rules.clause_limit} permits not more than "
            f"{rules.max_consecutive}; {rules.clause_relief} permits a "
            f"{_ordinal(max_relieved)} at most, with a "
            f"{reductions[max_relieved]}h reduction. There is no relief beyond "
            f"the {_ordinal(max_relieved)}."
        ),
        "remediation": (
            "Break the sequence of early starts with an off-duty period that "
            "includes a local night before assigning a further early start."
        ),
    })
    # Report the deepest relief available so the figure stays meaningful, but
    # the duty is prohibited regardless of the number.
    return reductions.get(max_relieved, 0.0)


def _ordinal(n: int) -> str:
    """1 -> '1st', 2 -> '2nd', 11 -> '11th'."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _apply_split_duty(
    rules: SplitDutyRules,
    split_duty: dict,
    current_fdp: float,
    notes: list[str],
    appendix: str,
    config: AppendixFdpConfig | None = None,
    violations: list[dict] | None = None,
) -> dict:
    """
    Apply a split-duty increase to the FDP limit.

    §3.4 (App 3 and 4; §4.4 in App 2) is a GATE, not an alternative branch.
    Both §3.1 and §3.3 open "Subject to subclause 3.4". Where the rest period
    includes any part of 2300-0529 local, §3.4(a) requires it to be a
    consecutive period of at least 7 hours with sleeping accommodation. A rest
    that overlaps the night window and fails that requirement earns no
    increase at all — not the §3.1 increase, and not the §3.3 half-credit.

    The previous shape tested `if overlaps_night and duration >= 7`, so a
    5-hour night-overlapping rest fell through to the ordinary §3.1 branch and
    collected the full +4h.
    """
    duration = split_duty.get("duration_hours", 0)
    accommodation = split_duty.get("accommodation", "none")
    overlaps_night = split_duty.get("overlaps_2300_0529", False)

    extension = 0.0
    clause = ""
    description = ""
    post_split_max = rules.post_split_max_hours if rules.post_split_max_hours < 99 else None
    clause_sleeping = (config.clause_split_sleeping if config else "") or ""
    clause_resting = (config.clause_split_resting if config else "") or ""
    clause_night = (config.clause_split_night_overlap if config else "") or ""

    if overlaps_night:
        gate_clause = f"{clause_night}(a)" if clause_night else ""
        meets_gate = (
            accommodation == "sleeping"
            and duration >= rules.night_overlap_min_sleeping
        )
        if not meets_gate:
            reason = (
                f"Split-duty rest of {duration}h with {accommodation} "
                f"accommodation includes part of the 2300-0529 local window. "
                f"{gate_clause} requires a consecutive period of at least "
                f"{rules.night_overlap_min_sleeping}h with access to suitable "
                f"sleeping accommodation. No FDP increase is available."
            )
            notes.append(reason)
            if violations is not None:
                violations.append({
                    "check": "split_duty_night_overlap",
                    "clause": gate_clause,
                    "severity": "hard_limit",
                    "actual": duration,
                    "limit": rules.night_overlap_min_sleeping,
                    "detail": reason,
                    "remediation": (
                        f"Extend the split-duty rest to at least "
                        f"{rules.night_overlap_min_sleeping} consecutive hours with "
                        f"suitable sleeping accommodation, or move it clear of the "
                        f"2300-0529 local window."
                    ),
                })
            # An explicit zero adjustment, so the absence of an increase is
            # auditable rather than merely absent.
            return {
                "extension": 0.0,
                "new_total": current_fdp,
                "clause": gate_clause,
                "description": reason,
                "post_split_max": None,
                "explicit_zero": True,
            }

        # §3.4(b): the maximum FDP may be increased to 16 hours.
        new_total = min(current_fdp + duration, rules.night_overlap_cap_hours)
        extension = new_total - current_fdp
        clause = f"{clause_night}(b)" if clause_night else ""
        description = (
            f"Split-duty rest {duration}h sleeping overlapping the 2300-0529 "
            f"window: +{extension}h (increased to at most "
            f"{rules.night_overlap_cap_hours}h)"
        )
        notes.append(
            f"Split duty: {duration}h sleeping with night overlap satisfies "
            f"{clause_night}(a) -> increase to {rules.night_overlap_cap_hours}h "
            f"({clause})"
        )
        return {
            "extension": extension,
            "new_total": new_total,
            "clause": clause,
            "description": description,
            "post_split_max": post_split_max,
        }

    # Standard sleeping accommodation
    if accommodation == "sleeping" and duration >= rules.sleeping_min_hours:
        if rules.sleeping_extension_type == "fixed":
            raw_extension = rules.sleeping_fixed_extension
        else:  # "duration"
            raw_extension = duration

        new_total = min(current_fdp + raw_extension, rules.sleeping_cap_hours)
        extension = new_total - current_fdp
        clause = clause_sleeping
        description = (
            f"Split-duty rest >={rules.sleeping_min_hours}h with sleeping accommodation: "
            f"+{extension}h (capped at {rules.sleeping_cap_hours}h)"
        )
        notes.append(
            f"Split duty: {duration}h sleeping accommodation -> "
            f"+{extension}h, capped at {rules.sleeping_cap_hours}h ({clause})"
        )
        if post_split_max is not None:
            notes.append(f"Post-split FDP must not exceed {post_split_max}h")

    # Resting accommodation
    elif accommodation == "resting" and duration >= rules.resting_min_hours:
        raw_extension = min(duration * rules.resting_extension_pct, rules.resting_max_extension)
        new_total = current_fdp + raw_extension
        extension = raw_extension
        # The resting-accommodation increase is §3.3 (App 3/4) or §4.3
        # (App 2). §3.2 is the ODP credit, a different rule.
        clause = clause_resting
        description = (
            f"Split-duty rest >={rules.resting_min_hours}h with resting accommodation: "
            f"+{extension}h (50% of rest, max {rules.resting_max_extension}h)"
        )
        notes.append(
            f"Split duty: {duration}h resting accommodation -> "
            f"+{extension}h ({clause})"
        )

    if extension == 0:
        notes.append(
            f"Split duty: {duration}h {accommodation} does not meet minimum requirements"
        )

    return {
        "extension": extension,
        "new_total": current_fdp + extension if extension > 0 else current_fdp,
        "clause": clause,
        "description": description,
        "post_split_max": post_split_max if extension > 0 else None,
    }
