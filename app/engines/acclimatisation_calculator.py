"""
Acclimatisation determination engine — CAO 48.1 §7.

Pure calculation, no HTTP concerns. Given where an FCM was last acclimatised
and every FDP / off-duty period commenced since, determines their state of
acclimatisation at a nominated moment, with the clause that produced it.

The four §7 branches, in the order this engine evaluates them:

  §7.1  Every later location is less than 2 hours different in local time
        -> the FCM is acclimatised to that location.

  §7.4  A continuous off-duty period met the Table 7.1 adaptation period
        (as reduced by §7.4(b)) -> the FCM has reacclimatised to the location
        where that off-duty period was taken. Checked before §7.2/§7.3
        because §7.4 is what ENDS whatever state they were in, and Note 2 to
        Table 7.1 makes clear an adaptation period may commence before the
        FCM comes to be in an unknown state.

  §7.2  Displaced by 2 hours or more, but the period at the new location
        commenced less than 36 hours after the FCM commenced a duty period at
        the original location -> still acclimatised to the ORIGINAL location.

  §7.3  Same, but 36 hours or more -> unknown state.

All logic derived from CAO 48.1 Instrument 2019 (Compilation No. 3,
F2021C01239).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.data.adaptation import (
    ADAPTATION_REDUCTION_PER_ODP_HOURS,
    DISPLACEMENT_THRESHOLD_HOURS,
    UNKNOWN_STATE_THRESHOLD_HOURS,
    lookup_adaptation_period,
)

DISCLAIMER = (
    "This result is derived from CAO 48.1 and is provided for reference "
    "purposes only. It does not replace your operator's approved Fatigue "
    "Management Manual (FMM), a qualified fatigue risk management assessment, "
    "or professional regulatory advice."
)

# §6: a local night is a period of 8 consecutive hours which includes
# 2200 to 0500 local time.
_LOCAL_NIGHT_START_HOUR = 22
_LOCAL_NIGHT_END_HOUR = 5
_LOCAL_NIGHT_MIN_HOURS = 8.0


# ═══════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════

def determine_acclimatisation(
    last_acclimatised: dict,
    as_of_utc: str,
    events: list[dict] | None = None,
    home_base: str | None = None,
) -> dict:
    """
    Determine an FCM's state of acclimatisation at a given moment.

    Parameters
    ----------
    last_acclimatised : dict
        Keys: location, utc_offset_hours, duty_commenced_utc.
    as_of_utc : str
        ISO 8601 UTC instant the determination is being made for.
    events : list of dict, optional
        Chronological FDP / off-duty periods commenced since last acclimatised.
        Keys: event_type, location, utc_offset_hours, start_utc, end_utc,
        and optionally includes_local_night.
    home_base : str, optional
        Home base identifier — only used to gate the §7.4(b) reduction.

    Returns
    -------
    dict
        Matching the AcclimatisationResponse model shape.
    """
    events = list(events or [])
    notes: list[str] = []

    origin_location = last_acclimatised["location"]
    origin_offset = float(last_acclimatised["utc_offset_hours"])
    duty_commenced = _parse(last_acclimatised["duty_commenced_utc"])
    as_of = _parse(as_of_utc)

    origin = {"location": origin_location, "utc_offset_hours": origin_offset}

    notes.append(
        f"Last acclimatised at {origin_location} (UTC{_fmt_offset(origin_offset)}), "
        f"duty commenced there {_iso(duty_commenced)}."
    )

    hours_since = _hours_between(duty_commenced, as_of)
    if hours_since < 0:
        # The question is being asked about a moment before the clock started.
        return _indeterminate(
            origin, hours_since,
            _no_displacement(),
            _empty_adaptation(),
            notes + [
                "as_of_utc precedes last_acclimatised.duty_commenced_utc, so no "
                "determination is possible. Check the supplied history."
            ],
        )

    # ─── §7.5(a),(b) — greatest displacement across all later locations ───
    displacement = _greatest_displacement(events, origin_offset, notes)

    # ─── §7.1 — nothing displaced the FCM by 2 hours or more ─────────────
    if displacement["hours"] < DISPLACEMENT_THRESHOLD_HOURS:
        current = _current_location(events, origin)
        notes.append(
            f"Greatest displacement since last acclimatised: "
            f"{displacement['hours']:.2f}h — less than "
            f"{DISPLACEMENT_THRESHOLD_HOURS:g} hours, so the FCM is acclimatised "
            f"to {current['location']} (§7.1)."
        )
        return _result(
            state="acclimatised",
            acclimatised_to=current,
            origin=origin,
            determination="acclimatised_at_location",
            clause="§7.1",
            hours_since=hours_since,
            displacement=displacement,
            adaptation=_empty_adaptation(
                longest=_longest_continuous_off_duty(events)[0],
            ),
            notes=notes,
        )

    # ─── §7.5(c),(d),(e) — Table 7.1 row for that greatest displacement ──
    lookup = lookup_adaptation_period(displacement["hours"], displacement["direction"])
    notes.append(
        f"Table 7.1: {displacement['hours']:.2f}h {displacement['direction']} "
        f"-> row '{lookup.row_label}' ({lookup.time_zones} time zones, rounded up "
        f"from the raw displacement), {lookup.direction} = "
        f"{lookup.required_hours:g}h adaptation period required."
    )
    displacement["time_zones"] = lookup.time_zones

    # ─── §7.4 — has a qualifying adaptation period been completed? ────────
    adaptation = _assess_adaptation(
        events, lookup.required_hours, lookup.row_label, home_base, notes,
    )

    completed_at = adaptation["acclimatised_at_utc_dt"]
    if completed_at is not None and completed_at <= as_of:
        target = {
            "location": adaptation["adaptation_location"],
            "utc_offset_hours": adaptation["adaptation_offset_hours"],
        }
        notes.append(
            f"Adaptation period completed at {_iso(completed_at)} — the FCM is "
            f"reacclimatised to {target['location']} "
            f"(UTC{_fmt_offset(target['utc_offset_hours'])}) (§7.4)."
        )
        return _result(
            state="acclimatised",
            acclimatised_to=target,
            origin=origin,
            determination="reacclimatised_by_adaptation",
            clause="§7.4",
            hours_since=hours_since,
            displacement=displacement,
            adaptation=adaptation,
            notes=notes,
        )

    # ─── Guard: could an unrecorded gap have concealed an adaptation? ─────
    gap = _largest_unrecorded_gap(events, duty_commenced, as_of)
    if gap is not None and gap["hours"] >= adaptation["effective_required_hours"]:
        notes.append(
            f"The supplied history has an unrecorded gap of {gap['hours']:.1f}h "
            f"between {_iso(gap['start'])} and {_iso(gap['end'])}. That is at "
            f"least the {adaptation['effective_required_hours']:g}h adaptation "
            f"period required here, so it could have been a qualifying §7.4 "
            f"adaptation period. No determination is possible without knowing "
            f"what happened during it."
        )
        return _indeterminate(origin, hours_since, displacement, adaptation, notes)

    # ─── §7.2 / §7.3 — the 36-hour clock from the ORIGINAL location ──────
    if hours_since < UNKNOWN_STATE_THRESHOLD_HOURS:
        notes.append(
            f"{hours_since:.2f}h since duty commenced at {origin_location} — "
            f"less than {UNKNOWN_STATE_THRESHOLD_HOURS:g} hours, so the FCM "
            f"remains acclimatised to {origin_location} (§7.2)."
        )
        return _result(
            state="acclimatised",
            acclimatised_to=origin,
            origin=origin,
            determination="remains_acclimatised_to_original",
            clause="§7.2",
            hours_since=hours_since,
            displacement=displacement,
            adaptation=adaptation,
            notes=notes,
        )

    notes.append(
        f"{hours_since:.2f}h since duty commenced at {origin_location} — "
        f"{UNKNOWN_STATE_THRESHOLD_HOURS:g} hours or more, and no qualifying "
        f"adaptation period has been completed, so the FCM is in an unknown "
        f"state of acclimatisation (§7.3)."
    )
    notes.append(
        f"In an unknown state, Appendix 2's early-start and WOCL tests fall back "
        f"to local time at the location last acclimatised to — {origin_location} "
        f"(UTC{_fmt_offset(origin_offset)}) (§6)."
    )
    return _result(
        state="unknown",
        acclimatised_to=None,
        origin=origin,
        determination="unknown_state",
        clause="§7.3",
        hours_since=hours_since,
        displacement=displacement,
        adaptation=adaptation,
        notes=notes,
    )


# ═══════════════════════════════════════════════════════════════════════
# §7.5 — displacement
# ═══════════════════════════════════════════════════════════════════════

def _greatest_displacement(
    events: list[dict],
    origin_offset: float,
    notes: list[str],
) -> dict:
    """
    Determine the greatest displacement between the original location and each
    later location where an FDP or off-duty period commenced (§7.5(a)-(b)).

    Deliberately NOT the current location's displacement — §7.5(b) says the
    greatest, and the greatest is frequently not the most recent.
    """
    greatest = _no_displacement()

    for event in events:
        offset = float(event["utc_offset_hours"])
        delta = offset - origin_offset
        magnitude = abs(delta)
        if magnitude > greatest["hours"]:
            greatest = {
                "hours": round(magnitude, 6),
                "time_zones": None,
                # A LARGER UTC offset means local time is further ahead, i.e.
                # the FCM travelled east.
                "direction": "east" if delta > 0 else "west",
                "location": event["location"],
            }

    if greatest["location"] is not None:
        notes.append(
            f"§7.5: greatest displacement across all later locations is "
            f"{greatest['hours']:.2f}h {greatest['direction']} at "
            f"{greatest['location']}."
        )
    else:
        notes.append(
            "No FDP or off-duty period has been commenced at another location "
            "since the FCM was last acclimatised."
        )

    return greatest


def _no_displacement() -> dict:
    return {"hours": 0.0, "time_zones": None, "direction": None, "location": None}


def _current_location(events: list[dict], origin: dict) -> dict:
    """
    The location governing the FCM's clock right now.

    Under §7.1 the FCM is acclimatised TO the location they are at, provided it
    is less than 2 hours different. Where there are no events they are still at
    the original location.
    """
    if not events:
        return origin
    last = events[-1]
    return {
        "location": last["location"],
        "utc_offset_hours": float(last["utc_offset_hours"]),
    }


# ═══════════════════════════════════════════════════════════════════════
# §7.4 — adaptation
# ═══════════════════════════════════════════════════════════════════════

def _assess_adaptation(
    events: list[dict],
    required_hours: float,
    table_row: str,
    home_base: str | None,
    notes: list[str],
) -> dict:
    """
    Assess whether a continuous off-duty period satisfies §7.4.

    Takes the longest continuous off-duty period in the history as the
    candidate adaptation period, applies the §7.4(b) reduction where it was
    taken away from home base, and reports when acclimatisation is (or was)
    reached.
    """
    longest_hours, candidate, candidate_index = _longest_continuous_off_duty(events)

    if candidate is None:
        notes.append(
            "No off-duty period in the supplied history, so no §7.4 adaptation "
            "period has commenced."
        )
        return {
            "required_hours": required_hours,
            "table_row": table_row,
            "reduction_hours": 0.0,
            "effective_required_hours": required_hours,
            "longest_continuous_off_duty_hours": 0.0,
            "adaptation_location": None,
            "adaptation_offset_hours": None,
            "acclimatised_at_utc_dt": None,
        }

    location = candidate["location"]
    offset = float(candidate["utc_offset_hours"])

    # ─── §7.4(b) — reduction, away from home base only ────────────────
    reduction = 0.0
    at_home_base = (
        home_base is not None
        and str(location).strip().casefold() == str(home_base).strip().casefold()
    )

    if at_home_base:
        notes.append(
            f"Adaptation period is at home base ({location}), so the §7.4(b) "
            f"12-hour reduction does not apply."
        )
    else:
        qualifying = _count_qualifying_preceding_odps(
            events, candidate_index, offset, notes,
        )
        reduction = qualifying * ADAPTATION_REDUCTION_PER_ODP_HOURS
        if qualifying:
            notes.append(
                f"§7.4(b): {qualifying} immediately preceding off-duty "
                f"period(s) qualify — reduction of "
                f"{ADAPTATION_REDUCTION_PER_ODP_HOURS:g}h each = {reduction:g}h."
            )
        else:
            notes.append(
                "§7.4(b): no immediately preceding off-duty period qualifies "
                "(each must be within 2 hours of the adaptation location and "
                "include an off-duty location local night) — no reduction."
            )

    effective = max(required_hours - reduction, 0.0)
    notes.append(
        f"Adaptation period required: {required_hours:g}h less {reduction:g}h "
        f"= {effective:g}h. Longest continuous off-duty period available: "
        f"{longest_hours:.2f}h at {location}."
    )

    # When does (or did) the FCM become acclimatised?
    acclimatised_at = None
    if longest_hours >= effective:
        acclimatised_at = _parse(candidate["start_utc"]) + timedelta(hours=effective)

    return {
        "required_hours": required_hours,
        "table_row": table_row,
        "reduction_hours": reduction,
        "effective_required_hours": effective,
        "longest_continuous_off_duty_hours": round(longest_hours, 4),
        "adaptation_location": location,
        "adaptation_offset_hours": offset,
        "acclimatised_at_utc_dt": acclimatised_at,
    }


def _longest_continuous_off_duty(
    events: list[dict],
) -> tuple[float, dict | None, int]:
    """
    Find the longest CONTINUOUS off-duty period.

    §6 defines an adaptation period as a continuous off-duty period, so
    consecutive off-duty events that abut in time and share a location are
    merged, while any intervening FDP breaks the run.

    Returns
    -------
    (hours, merged_event_or_None, index_of_first_event_in_run)
    """
    best_hours = 0.0
    best_event: dict | None = None
    best_index = -1

    run_start: datetime | None = None
    run_end: datetime | None = None
    run_event: dict | None = None
    run_index = -1

    def _close_run() -> None:
        nonlocal best_hours, best_event, best_index
        if run_start is None or run_end is None or run_event is None:
            return
        hours = _hours_between(run_start, run_end)
        if hours > best_hours:
            best_hours = hours
            best_event = {**run_event, "start_utc": _iso(run_start), "end_utc": _iso(run_end)}
            best_index = run_index

    for index, event in enumerate(events):
        if event["event_type"] != "off_duty":
            _close_run()
            run_start = run_end = run_event = None
            run_index = -1
            continue

        start = _parse(event["start_utc"])
        end = _parse(event["end_utc"])

        continues = (
            run_end is not None
            and run_event is not None
            and abs((start - run_end).total_seconds()) < 60  # abuts within a minute
            and abs(float(event["utc_offset_hours"]) - float(run_event["utc_offset_hours"])) < 1e-9
        )

        if continues:
            run_end = end
        else:
            _close_run()
            run_start, run_end, run_event, run_index = start, end, event, index

    _close_run()
    return best_hours, best_event, best_index


def _count_qualifying_preceding_odps(
    events: list[dict],
    candidate_index: int,
    adaptation_offset: float,
    notes: list[str],
) -> int:
    """
    Count off-duty periods qualifying for the §7.4(b)(iii) 12-hour reduction.

    Each must have IMMEDIATELY preceded the adaptation period, been at a
    location less than 2 hours different in local time from the adaptation
    location, and included an off-duty location local night.

    'Immediately preceded' is read as an unbroken run of off-duty periods
    working backwards from the adaptation period — the count stops at the first
    period that fails any condition, and any FDP in between ends the run.
    """
    count = 0
    for index in range(candidate_index - 1, -1, -1):
        event = events[index]

        if event["event_type"] != "off_duty":
            break  # an FDP breaks the run of immediately preceding ODPs

        offset = float(event["utc_offset_hours"])
        if abs(offset - adaptation_offset) >= DISPLACEMENT_THRESHOLD_HOURS:
            break  # §7.4(b)(iii)(B)

        includes_night = event.get("includes_local_night")
        if includes_night is None:
            includes_night = _derive_local_night(event)
            notes.append(
                f"includes_local_night not supplied for the off-duty period at "
                f"{event['location']} starting {event['start_utc']} — derived as "
                f"{includes_night} from the supplied times and offset (§6)."
            )
        if not includes_night:
            break  # §7.4(b)(iii)(C)

        count += 1

    return count


# ═══════════════════════════════════════════════════════════════════════
# §6 — local night derivation
# ═══════════════════════════════════════════════════════════════════════

def _derive_local_night(event: dict) -> bool:
    """
    Derive whether an off-duty period included a local night.

    §6: a local night is a period of 8 consecutive hours which includes 2200 to
    0500 local time. So the period must both span at least 8 hours and fully
    contain a 2200-0500 local window.
    """
    offset = float(event["utc_offset_hours"])
    start_local = _parse(event["start_utc"]) + timedelta(hours=offset)
    end_local = _parse(event["end_utc"]) + timedelta(hours=offset)

    if _hours_between(start_local, end_local) < _LOCAL_NIGHT_MIN_HOURS:
        return False

    # Walk each calendar night that could fall inside the period.
    night = start_local.replace(
        hour=_LOCAL_NIGHT_START_HOUR, minute=0, second=0, microsecond=0,
    ) - timedelta(days=1)
    while night <= end_local:
        night_end = night.replace(
            hour=_LOCAL_NIGHT_END_HOUR, minute=0, second=0, microsecond=0,
        ) + timedelta(days=1)
        if start_local <= night and night_end <= end_local:
            return True
        night += timedelta(days=1)

    return False


# ═══════════════════════════════════════════════════════════════════════
# History completeness
# ═══════════════════════════════════════════════════════════════════════

def _largest_unrecorded_gap(
    events: list[dict],
    duty_commenced: datetime,
    as_of: datetime,
) -> dict | None:
    """
    Find the largest stretch of time not covered by any supplied event.

    A gap matters because it could have contained an adaptation period the API
    cannot see. Rather than assume the FCM stayed put, the caller is told the
    history is insufficient.
    """
    largest: dict | None = None
    cursor = duty_commenced

    for event in events:
        start = _parse(event["start_utc"])
        end = _parse(event["end_utc"])
        gap_hours = _hours_between(cursor, start)
        if gap_hours > 0 and (largest is None or gap_hours > largest["hours"]):
            largest = {"hours": gap_hours, "start": cursor, "end": start}
        if end > cursor:
            cursor = end

    trailing = _hours_between(cursor, as_of)
    if trailing > 0 and (largest is None or trailing > largest["hours"]):
        largest = {"hours": trailing, "start": cursor, "end": as_of}

    return largest


# ═══════════════════════════════════════════════════════════════════════
# Result assembly
# ═══════════════════════════════════════════════════════════════════════

def _result(
    state: str,
    acclimatised_to: dict | None,
    origin: dict,
    determination: str,
    clause: str,
    hours_since: float,
    displacement: dict,
    adaptation: dict,
    notes: list[str],
) -> dict:
    """Assemble the response dict, converting internal datetimes to ISO."""
    completed = adaptation.get("acclimatised_at_utc_dt")
    return {
        "state": state,
        "acclimatised_to": acclimatised_to,
        "last_acclimatised_to": origin,
        "determination": determination,
        "clause": clause,
        "hours_since_original_duty_commenced": round(hours_since, 4),
        "greatest_displacement": {
            "hours": displacement["hours"],
            "time_zones": displacement["time_zones"],
            "direction": displacement["direction"],
            "location": displacement["location"],
        },
        "adaptation": {
            "required_hours": adaptation.get("required_hours"),
            "table_row": adaptation.get("table_row"),
            "reduction_hours": adaptation.get("reduction_hours", 0.0),
            "effective_required_hours": adaptation.get("effective_required_hours"),
            "longest_continuous_off_duty_hours": adaptation.get(
                "longest_continuous_off_duty_hours", 0.0
            ),
            "adaptation_location": adaptation.get("adaptation_location"),
            "acclimatised_at_utc": _iso(completed) if completed else None,
        },
        "calculation_notes": notes,
        "disclaimer": DISCLAIMER,
    }


def _indeterminate(
    origin: dict,
    hours_since: float,
    displacement: dict,
    adaptation: dict,
    notes: list[str],
) -> dict:
    """
    Build an 'insufficient history' result.

    Deliberately distinct from §7.3 'unknown': that is a determination with its
    own limit tables, this is the absence of one.
    """
    notes = notes + [
        "State reported as 'indeterminate'. This is NOT the §7.3 'unknown' "
        "state — do not use it for an FDP table lookup. Supply a more complete "
        "history, or treat the FCM's state as established by other means."
    ]
    return _result(
        state="indeterminate",
        acclimatised_to=None,
        origin=origin,
        determination="insufficient_history",
        clause="§7",
        hours_since=hours_since,
        displacement=displacement,
        adaptation=adaptation,
        notes=notes,
    )


def _empty_adaptation(longest: float = 0.0) -> dict:
    """An adaptation block for cases where Table 7.1 never came into play."""
    return {
        "required_hours": None,
        "table_row": None,
        "reduction_hours": 0.0,
        "effective_required_hours": None,
        "longest_continuous_off_duty_hours": round(longest, 4),
        "adaptation_location": None,
        "adaptation_offset_hours": None,
        "acclimatised_at_utc_dt": None,
    }


# ═══════════════════════════════════════════════════════════════════════
# Small helpers
# ═══════════════════════════════════════════════════════════════════════

def _parse(value: str | datetime) -> datetime:
    """Parse an ISO 8601 UTC string (Z-suffixed or offset-suffixed)."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo is None else value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _iso(dt: datetime) -> str:
    """Format a datetime as an ISO 8601 Z-suffix string."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _hours_between(start: datetime, end: datetime) -> float:
    """Hours from start to end. Negative if end precedes start."""
    return (end - start).total_seconds() / 3600.0


def _fmt_offset(offset_hours: float) -> str:
    """Render a UTC offset as +8 / +9:30 / -5:45 for the notes."""
    sign = "+" if offset_hours >= 0 else "-"
    magnitude = abs(offset_hours)
    hours = int(magnitude)
    minutes = round((magnitude - hours) * 60)
    return f"{sign}{hours}" if minutes == 0 else f"{sign}{hours}:{minutes:02d}"
