"""
Pydantic request and response models for POST /calculate/acclimatisation.

Determines an FCM's state of acclimatisation under CAO 48.1 §7 from a supplied
duty and off-duty history. The endpoint is stateless: the caller supplies the
whole history on every call, and supplies UTC offsets directly so the API never
performs a time zone database lookup. That keeps daylight saving out of the
API entirely and honours §6's provision allowing an AOC holder to nominate an
adjoining time zone in its operations manual.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.models.base import StrictModel

# ─── Enumerations ─────────────────────────────────────────────────────

# 'indeterminate' is deliberately distinct from 'unknown'. §7.3 'unknown' is a
# DETERMINATION with its own limit tables (Tables 3.1 and 5.2). 'indeterminate'
# means the supplied history was not sufficient to reach any determination —
# an absence of an answer, not a conservative one. Callers must not feed
# 'indeterminate' into an FDP lookup.
AcclimatisationState = Literal["acclimatised", "unknown", "indeterminate"]

Determination = Literal[
    "acclimatised_at_location",          # §7.1
    "remains_acclimatised_to_original",  # §7.2
    "unknown_state",                     # §7.3
    "reacclimatised_by_adaptation",      # §7.4
    "insufficient_history",              # no determination possible
]

Direction = Literal["west", "east"]
AcclimEventType = Literal["fdp", "off_duty"]


# ─── Request models ───────────────────────────────────────────────────

class LastAcclimatisedInput(StrictModel):
    """Where and when the FCM was last known to be acclimatised."""

    location: str = Field(
        description=(
            "Free-text identifier for the location — an ICAO code, IATA code or "
            "any label meaningful to the caller. The API performs no geocoding "
            "and no time zone lookup; it is echoed back for traceability only."
        ),
    )
    utc_offset_hours: float = Field(
        description=(
            "UTC offset of local time at that location, in hours. Authoritative: "
            "the API does not derive it. Half-hour and quarter-hour offsets are "
            "supported (e.g. 9.5 for ACST, 5.75 for NPT)."
        ),
    )
    duty_commenced_utc: str = Field(
        description=(
            "When the FCM commenced a duty period at this location (ISO 8601 UTC). "
            "This starts the §7.2 / §7.3 36-hour clock. Note the asymmetry: the "
            "36 hours runs from commencement of duty at the ORIGINAL location, "
            "not from arrival at the new one."
        ),
    )


class AcclimatisationEvent(StrictModel):
    """One FDP or off-duty period commenced since the FCM was last acclimatised."""

    event_type: AcclimEventType = Field(
        description="Whether this period is an FDP or an off-duty period.",
    )
    location: str = Field(description="Free-text identifier for where the period commenced.")
    utc_offset_hours: float = Field(
        description="UTC offset of local time at that location, in hours.",
    )
    start_utc: str = Field(description="Start of the period (ISO 8601 UTC).")
    end_utc: str = Field(description="End of the period (ISO 8601 UTC).")
    includes_local_night: Optional[bool] = Field(
        default=None,
        description=(
            "Whether an off-duty period included a local night at the off-duty "
            "location — §6 defines that as a period of 8 consecutive hours which "
            "includes 2200 to 0500 local time. Needed for the §7.4(b) 12-hour "
            "reduction. If omitted, the API derives it from the start, end and "
            "offset already supplied, and says so in calculation_notes. Ignored "
            "for FDP events."
        ),
    )


class AcclimatisationRequest(StrictModel):
    """Request body for POST /calculate/acclimatisation."""

    last_acclimatised: LastAcclimatisedInput = Field(
        description="The FCM's last known acclimatised location and duty commencement.",
    )
    as_of_utc: str = Field(
        description=(
            "The moment the question is being asked about (ISO 8601 UTC) — "
            "normally the commencement of the FDP being planned."
        ),
    )
    events: list[AcclimatisationEvent] = Field(
        default_factory=list,
        description=(
            "Every FDP and off-duty period commenced since the FCM was last "
            "acclimatised, in chronological order. Used for the §7.5 greatest-"
            "displacement selection and the §7.4 adaptation assessment. An empty "
            "list means nothing has displaced the FCM since."
        ),
    )
    home_base: Optional[str] = Field(
        default=None,
        description=(
            "The FCM's home base identifier. Only needed for the §7.4(b) "
            "reduction, which applies exclusively to adaptation periods taken "
            "somewhere other than home base. Matched case-insensitively against "
            "event locations."
        ),
    )

    @model_validator(mode="after")
    def events_must_be_chronological(self) -> "AcclimatisationRequest":
        """
        Reject out-of-order events rather than silently sorting them.

        §7.4(b) counts off-duty periods that IMMEDIATELY PRECEDED the adaptation
        period, so ordering is load-bearing. Quietly reordering a caller's list
        would change the answer without telling them.
        """
        starts = [e.start_utc for e in self.events]
        if starts != sorted(starts):
            raise ValueError(
                "events must be supplied in chronological order by start_utc. "
                "The §7.4(b) reduction counts immediately preceding off-duty "
                "periods, so the order affects the result."
            )
        return self

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "home_base": "YPPH",
                    "last_acclimatised": {
                        "location": "YPPH",
                        "utc_offset_hours": 8.0,
                        "duty_commenced_utc": "2026-07-20T22:00:00Z",
                    },
                    "as_of_utc": "2026-07-26T09:00:00Z",
                    "events": [
                        {
                            "event_type": "fdp",
                            "location": "EGLL",
                            "utc_offset_hours": 1.0,
                            "start_utc": "2026-07-21T02:00:00Z",
                            "end_utc": "2026-07-21T14:00:00Z",
                        },
                        {
                            "event_type": "off_duty",
                            "location": "EGLL",
                            "utc_offset_hours": 1.0,
                            "start_utc": "2026-07-21T14:00:00Z",
                            "end_utc": "2026-07-25T14:00:00Z",
                            "includes_local_night": True,
                        },
                    ],
                }
            ]
        }
    }


# ─── Response models ──────────────────────────────────────────────────

class AcclimatisedLocation(BaseModel):
    """The location an FCM is acclimatised to, and its clock."""

    location: str = Field(description="Location identifier, as supplied by the caller.")
    utc_offset_hours: float = Field(
        description=(
            "UTC offset of local time at that location. This is the value to pass "
            "as acclimatisation.acclimatised_time_offset_hours on /calculate/max-fdp "
            "and /validate/fdp — under Appendix 2 the FDP table band, the "
            "early-start test and the WOCL determination are all defined against "
            "local time at THIS location, not the departure point."
        ),
    )


class GreatestDisplacement(BaseModel):
    """The §7.5(b) greatest time zone displacement since last acclimatised."""

    hours: float = Field(description="Raw displacement in hours from the original location.")
    time_zones: Optional[int] = Field(
        default=None,
        description=(
            "Whole time zones used for the Table 7.1 row, rounding up. Null when "
            "the displacement is below the §7.1 2-hour threshold."
        ),
    )
    direction: Optional[Direction] = Field(
        default=None,
        description="Direction of travel for that greatest displacement. Null if undisplaced.",
    )
    location: Optional[str] = Field(
        default=None,
        description="Which later location produced the greatest displacement.",
    )


class AdaptationDetail(BaseModel):
    """Table 7.1 adaptation assessment under §7.4."""

    required_hours: Optional[float] = Field(
        default=None,
        description="Table 7.1 adaptation period before any §7.4(b) reduction.",
    )
    table_row: Optional[str] = Field(
        default=None,
        description="Which Table 7.1 row was used, e.g. '3' or '10 or more'.",
    )
    reduction_hours: float = Field(
        default=0.0,
        description="§7.4(b) reduction: 12 hours per qualifying preceding off-duty period.",
    )
    effective_required_hours: Optional[float] = Field(
        default=None,
        description="required_hours less reduction_hours, floored at zero.",
    )
    longest_continuous_off_duty_hours: float = Field(
        default=0.0,
        description="Longest continuous off-duty period in the supplied history.",
    )
    adaptation_location: Optional[str] = Field(
        default=None,
        description="Where the longest continuous off-duty period was taken.",
    )
    acclimatised_at_utc: Optional[str] = Field(
        default=None,
        description=(
            "When the FCM becomes — or became — acclimatised, if determinable "
            "from the supplied history. Null where it cannot be determined; the "
            "API does not guess."
        ),
    )


class AcclimatisationResponse(BaseModel):
    """Response for POST /calculate/acclimatisation."""

    state: AcclimatisationState = Field(
        description=(
            "The FCM's state at as_of_utc. 'indeterminate' means the supplied "
            "history was insufficient to reach a determination — it is NOT a "
            "synonym for the §7.3 'unknown' state and must not be used as one."
        ),
    )
    acclimatised_to: Optional[AcclimatisedLocation] = Field(
        default=None,
        description=(
            "The location the FCM is acclimatised to. Null in an unknown or "
            "indeterminate state."
        ),
    )
    last_acclimatised_to: AcclimatisedLocation = Field(
        description=(
            "The original location, echoed back. In an unknown state this is the "
            "clock that Appendix 2's early-start and WOCL definitions fall back to."
        ),
    )
    determination: Determination = Field(
        description="Stable enum identifying which §7 branch produced the result.",
    )
    clause: str = Field(description="The CAO 48.1 clause that produced the determination.")
    hours_since_original_duty_commenced: float = Field(
        description="Hours from last_acclimatised.duty_commenced_utc to as_of_utc.",
    )
    greatest_displacement: GreatestDisplacement = Field(
        description="§7.5 greatest displacement across all later locations.",
    )
    adaptation: AdaptationDetail = Field(
        description="Table 7.1 assessment and the §7.4(b) reduction.",
    )
    calculation_notes: list[str] = Field(
        default_factory=list,
        description="Human-readable breakdown with clause references.",
    )
    disclaimer: str = Field(description="Standard API disclaimer.")


# ─── GET /limits/adaptation-table ─────────────────────────────────────

class AdaptationTableRow(BaseModel):
    """One row of Table 7.1."""

    time_zone_change: str = Field(description="Time zone change label, e.g. '4' or '10 or more'.")
    time_zones: int = Field(description="Numeric time zone change (10 represents '10 or more').")
    west_hours: float = Field(description="Adaptation period for westward travel (hours).")
    east_hours: float = Field(description="Adaptation period for eastward travel (hours).")


class AdaptationTableResponse(BaseModel):
    """Response for GET /limits/adaptation-table."""

    table_id: str = Field(description="Table identifier within CAO 48.1.")
    title: str = Field(description="Table title.")
    clause: str = Field(description="Clause the table sits under.")
    rows: list[AdaptationTableRow] = Field(description="Table 7.1 rows, ascending.")
    notes: list[str] = Field(
        default_factory=list,
        description="Interpretation notes, including the fractional-zone reading.",
    )
