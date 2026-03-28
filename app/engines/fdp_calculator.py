"""
FDP (Flight Duty Period) calculator engine.

Pure calculation functions with no HTTP concerns. Takes operational parameters,
looks up the correct FDP table, applies adjustments (split duty, WOCL/early
start reductions), and returns a clause-referenced audit trail.

All logic derived from CAO 48.1 Instrument 2019 (Compilation No. 3, F2021C01239).
"""

from datetime import datetime

from app.data.fdp_tables import (
    AppendixFdpConfig,
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
    if config.wocl_early_start:
        wocl_reduction = _calculate_wocl_reduction(
            consecutive_early_starts, consecutive_wocl_infringements,
            local_minutes, notes,
        )
        if wocl_reduction > 0:
            running_total -= wocl_reduction
            adjustments.append({
                "clause": "WOCL/early start",
                "description": f"Consecutive early starts/WOCL: -{wocl_reduction}h reduction",
                "adjustment_hours": -wocl_reduction,
                "running_total_hours": running_total,
            })

    # ─── Apply split duty extension ───────────────────────────────
    post_split_max = None
    if split_duty and config.split_duty.available:
        sd_result = _apply_split_duty(
            config.split_duty, split_duty, running_total, notes, appendix,
        )
        if sd_result["extension"] > 0:
            running_total = sd_result["new_total"]
            adjustments.append({
                "clause": sd_result["clause"],
                "description": sd_result["description"],
                "adjustment_hours": sd_result["extension"],
                "running_total_hours": running_total,
            })
        post_split_max = sd_result.get("post_split_max")

    final_max = running_total
    max_extension = config.max_extension_hours

    return {
        "appendix": appendix,
        "base_max_fdp_hours": base_fdp,
        "adjustments": adjustments,
        "wocl_early_start_reduction_hours": wocl_reduction,
        "final_max_fdp_hours": final_max,
        "max_extension_hours": max_extension,
        "absolute_max_with_extension_hours": final_max + max_extension,
        "post_split_max_hours": post_split_max,
        "flight_time_limit_hours": flight_time_limit,
        "calculation_notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════

def _utc_to_local_minutes(dt: datetime, offset_hours: float) -> int:
    """Convert a UTC datetime to local minutes from midnight."""
    total_minutes = dt.hour * 60 + dt.minute + int(offset_hours * 60)
    return total_minutes % 1440  # wrap around midnight


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
    consecutive_early_starts: int,
    consecutive_wocl_infringements: int,
    local_minutes: int,
    notes: list[str],
) -> float:
    """Calculate FDP reduction for WOCL/early start rules."""
    # Early start: 0500-0659 local
    is_early_start = _hm(5) <= local_minutes <= _hm(6, 59)

    if not is_early_start:
        return 0.0

    # Consecutive early start count (including this one)
    total_consecutive = consecutive_early_starts + 1

    if total_consecutive <= 3:
        notes.append(
            f"Early start #{total_consecutive} of 3 allowed: no reduction"
        )
        return 0.0
    elif total_consecutive == 4:
        notes.append(
            f"4th consecutive early start: FDP reduced by 2h (WOCL rule)"
        )
        return 2.0
    else:
        notes.append(
            f"5th+ consecutive early start: FDP reduced by 4h (WOCL rule)"
        )
        return 4.0


def _apply_split_duty(
    rules: SplitDutyRules,
    split_duty: dict,
    current_fdp: float,
    notes: list[str],
    appendix: str,
) -> dict:
    """Apply split duty extension to the FDP limit."""
    duration = split_duty.get("duration_hours", 0)
    accommodation = split_duty.get("accommodation", "none")
    overlaps_night = split_duty.get("overlaps_2300_0529", False)

    extension = 0.0
    clause = ""
    description = ""
    post_split_max = rules.post_split_max_hours if rules.post_split_max_hours < 99 else None

    # Check night overlap special rules first
    if overlaps_night and accommodation == "sleeping":
        if duration >= rules.night_overlap_min_sleeping:
            # Night overlap with sufficient sleeping rest
            new_total = min(current_fdp + duration, rules.night_overlap_cap_hours)
            extension = new_total - current_fdp
            clause = f"§{'4' if appendix == '2' else '3'}.night"
            description = (
                f"Split-duty rest {duration}h sleeping overlapping night window: "
                f"+{extension}h (capped at {rules.night_overlap_cap_hours}h)"
            )
            notes.append(
                f"Split duty: {duration}h sleeping with night overlap -> "
                f"cap {rules.night_overlap_cap_hours}h ({clause})"
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
        clause = f"§{'4' if appendix == '2' else '3'}.1"
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
        clause = f"§{'4' if appendix == '2' else '3'}.2"
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
