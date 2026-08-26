"""
Pydantic request and response models for the /validate/* endpoints.

POST /validate/fdp        — FDP validation
POST /validate/off-duty   — Off-duty period validation
POST /validate/cumulative — Rolling-window cumulative limit checks
POST /validate/sequence   — Ordered FDP/ODP sequence validation
POST /validate/roster     — Full roster validation
"""

from datetime import datetime
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models._validators import (
    require_duration_agrees,
    require_end_after_start,
    require_events_ordered,
    validate_utc_offset,
)

from app.models.calculation import (
    AcclimState,
    AcclimatisationInput,
    AppendixId,
    AugmentedCrewInput,
    Location,
    PrecedingFdpInput,
    PrecedingOffDutyInput,
    SplitDutyInput,
)


# ─── Common enumerations ──────────────────────────────────────────────

Severity = Literal["hard_limit", "soft_limit", "warning"]
ExtensionType = Literal["unforeseen", "urgent", "final_sector"]


# ─── Shared response sub-models ───────────────────────────────────────

class CheckResult(BaseModel):
    """Result of a single compliance check."""

    check: str = Field(description="Check identifier.")
    passed: Optional[bool] = Field(
        default=None,
        description=(
            "True if the check passed, False if it failed, null if it could "
            "not be evaluated. **null is not true** — see `status`. The field "
            "remains present so existing consumers do not break, but a null "
            "must never be read as compliance."
        ),
    )
    status: Literal["passed", "failed", "data_unavailable"] = Field(
        default="passed",
        description=(
            "'data_unavailable' means the API could not evaluate this "
            "condition from the data supplied. It is neither a pass nor a "
            "fail, and does not count toward a compliant verdict."
        ),
    )
    clause: str = Field(description="CAO 48.1 clause reference for this check.")
    actual: Optional[float] = Field(
        default=None,
        description="Actual value measured (hours).",
    )
    limit: Optional[float] = Field(
        default=None,
        description="Applicable limit (hours).",
    )
    detail: Optional[str] = Field(
        default=None,
        description="Human-readable explanation of the check result.",
    )


class Violation(BaseModel):
    """A compliance violation found during validation."""

    check: str = Field(description="Check identifier.")
    clause: str = Field(description="CAO 48.1 clause reference.")
    severity: Severity = Field(
        description="Severity: 'hard_limit' is a regulatory breach, 'soft_limit' is an exceedance of a soft cap, 'warning' is advisory.",
    )
    actual: Optional[float] = Field(
        default=None,
        description="Actual value (hours).",
    )
    limit: Optional[float] = Field(
        default=None,
        description="Applicable limit (hours).",
    )
    detail: str = Field(description="Human-readable description of the violation.")
    remediation: str = Field(description="Suggested corrective action.")


class ValidationResponse(BaseModel):
    """
    Validation result showing all checks run and any violations found.

    `valid` reports whether anything was BREACHED: it is True when no check
    failed. It does not report whether the assessment was complete — read
    `checks_skipped` for that. The two are deliberately separate, because
    validating without full prior history is an ordinary thing to do and a
    verdict that failed every such request would stop carrying information.

    A caller who needs a complete assessment must check both:
    `valid and checks_skipped == 0`.

    All checks evaluated — including those that passed — are included in the
    `checks` list for full auditability.
    """

    valid: bool = Field(
        description=(
            "True if no check failed. This is a statement about breaches, not "
            "about completeness — a check that could not be evaluated does not "
            "make this False. For a complete assessment, require "
            "`valid and checks_skipped == 0`."
        ),
    )
    checks_run: int = Field(
        default=0, description="Number of checks actually evaluated.",
    )
    checks_skipped: int = Field(
        default=0,
        description=(
            "Number of checks that could not be evaluated from the supplied "
            "data. Non-zero means this response is not a complete assessment: "
            "nothing in those checks was found to breach, but nothing was "
            "established either. Not reflected in `valid`."
        ),
    )
    appendix: str = Field(description="Appendix used for validation.")
    violations: list[Violation] = Field(
        default_factory=list,
        description="All violations found. Empty list if valid.",
    )
    checks: list[CheckResult] = Field(
        default_factory=list,
        description="All checks evaluated, including those that passed.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-violating advisory notes.",
    )
    calculation_notes: list[str] = Field(
        default_factory=list,
        description="Clause-referenced calculation breakdown from the limit engine.",
    )


# ═══════════════════════════════════════════════════════════════════════
# POST /validate/fdp
# ═══════════════════════════════════════════════════════════════════════

class ExtensionInput(BaseModel):
    """Details of an FDP extension applied beyond the normal limit."""

    type: ExtensionType = Field(
        description=(
            "Extension type: 'unforeseen' (unexpected delay), "
            "'urgent' (emergency service op — Appendix 4B only), "
            "or 'final_sector' (last sector of a multi-sector FDP)."
        ),
    )
    hours_used: float = Field(
        gt=0,
        description="Hours of extension applied beyond the normal FDP limit.",
    )
    captains_authority: Optional[bool] = Field(
        default=None,
        description=(
            "Whether the extension was exercised at the discretion of the pilot "
            "in command (the FCM under Appendices 4B and 5). Omit if unknown — "
            "an explicit False is read as an assertion that the discretion was "
            "NOT exercised, which makes the extension unavailable. The default "
            "was False, which meant every caller who left it out was silently "
            "asserting the opposite of what they meant."
        ),
    )
    pre_planned: Optional[bool] = Field(
        default=None,
        description=(
            "Whether the extension was pre-planned. §5.3 / §3.1 grant an "
            "extension only 'in unforeseen operational circumstances', so an "
            "explicit True makes the 'unforeseen' provision unavailable. It "
            "does not affect Appendix 4B's 'urgent' provision (§3.2), which "
            "turns on the operations manual rather than on foreseeability. "
            "Omit if unknown."
        ),
    )


class ValidateFdpRequest(BaseModel):
    """Request body for POST /validate/fdp."""

    appendix: AppendixId = Field(description="Which appendix rules apply.")
    fdp_start_utc: str = Field(description="FDP start time (ISO 8601 UTC).")
    fdp_end_utc: str = Field(description="FDP end time (ISO 8601 UTC).")
    local_time_offset_hours: float = Field(
        description="UTC offset of the local time zone at the departure point (hours).",
    )
    sectors: int = Field(ge=1, description="Number of sectors (flights) in the FDP.")
    actual_flight_time_hours: Optional[float] = Field(
        default=None,
        description=(
            "Total flight time within this FDP (hours). "
            "When provided, checked against the per-FDP flight time limit "
            "for appendices that have one (e.g. Appendices 2, 3, 6)."
        ),
    )
    extension: Optional[ExtensionInput] = Field(
        default=None,
        description="Extension applied to this FDP, if any.",
    )
    acclimatisation: Optional[AcclimatisationInput] = Field(
        default=None,
        description="Acclimatisation state. Required for Appendix 2.",
    )
    augmented_crew: Optional[AugmentedCrewInput] = Field(
        default=None,
        description="Augmented crew configuration. Only applicable to Appendix 2.",
    )
    split_duty: Optional[SplitDutyInput] = Field(
        default=None,
        description="Split duty rest details, if a split duty rest was taken during this FDP.",
    )
    consecutive_early_starts: int = Field(
        default=0, ge=0,
        description="Number of consecutive early starts (0500–0659 local) preceding this FDP.",
    )
    consecutive_wocl_infringements: int = Field(
        default=0, ge=0,
        description="Number of consecutive WOCL infringements preceding this FDP.",
    )
    single_pilot: bool = Field(
        default=False,
        description="Whether this is a single-pilot operation (Appendices 4B, 5).",
    )
    preceding_off_duty_hours: Optional[float] = Field(
        default=None,
        description=(
            "Duration of preceding off-duty period (hours). "
            "Required for Appendix 2 unknown acclimatisation table lookup."
        ),
    )

    @field_validator("local_time_offset_hours")
    @classmethod
    def _check_offset(cls, v):
        return validate_utc_offset(v, "local_time_offset_hours")

    @model_validator(mode="after")
    def _check_times(self) -> "ValidateFdpRequest":
        require_end_after_start(
            self.fdp_start_utc, self.fdp_end_utc,
            "fdp_start_utc", "fdp_end_utc",
        )
        return self

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "appendix": "3",
                    "fdp_start_utc": "2026-03-28T22:00:00Z",
                    "fdp_end_utc": "2026-03-29T10:00:00Z",
                    "local_time_offset_hours": 8,
                    "sectors": 3,
                    "actual_flight_time_hours": 9.5,
                }
            ]
        }
    }


# ═══════════════════════════════════════════════════════════════════════
# POST /validate/off-duty
# ═══════════════════════════════════════════════════════════════════════

class ValidateOffDutyRequest(BaseModel):
    """Request body for POST /validate/off-duty."""

    appendix: AppendixId = Field(description="Which appendix rules apply.")
    preceding_fdp: PrecedingFdpInput = Field(description="Details of the preceding FDP.")
    actual_off_duty_hours: float = Field(
        gt=0,
        description="Actual off-duty period duration (hours).",
    )
    reduction_claimed: bool = Field(
        default=False,
        description=(
            "Set to True if a reduced ODP has been claimed under the applicable "
            "reduction provision. When True, the API validates that all eligibility "
            "conditions for the reduction are satisfied."
        ),
    )
    preceding_off_duty: Optional[PrecedingOffDutyInput] = Field(
        default=None,
        description=(
            "Details of the off-duty period before the preceding FDP. "
            "Required to evaluate reduction eligibility (Appendices 2, 3, 4)."
        ),
    )
    following_off_duty_location: Optional[Location] = Field(
        default=None,
        description=(
            "Where the following off-duty period will be taken. Optional: this "
            "describes the same fact as `preceding_fdp.location`, which is "
            "what the §8.1 / §10.1 branch reads. Supply it only to be "
            "explicit — if it disagrees with preceding_fdp.location the "
            "request is rejected rather than one silently winning."
        ),
    )
    following_off_duty_includes_local_night: bool = Field(
        default=True,
        description="Whether the off-duty period includes a local night.",
    )
    fdp_start_offset_hours: Optional[float] = Field(
        default=None,
        description=(
            "UTC offset where the preceding FDP started. Supply with "
            "odp_start_offset_hours to compute displacement time (App 2, 4, 4B)."
        ),
    )
    odp_start_offset_hours: Optional[float] = Field(
        default=None,
        description=(
            "UTC offset where the off-duty period starts. Supply with "
            "fdp_start_offset_hours to compute displacement time."
        ),
    )
    acclimatisation_state: AcclimState = Field(
        default="not_applicable",
        description=(
            "Acclimatisation state. Under Appendix 2 an unknown state selects "
            "§10.1(c) / §10.2(b) and blocks the §10.4 reduction via §10.4(c)."
        ),
    )

    @model_validator(mode="after")
    def _check_location_agreement(self) -> "ValidateOffDutyRequest":
        """
        Same fact, two fields — see MinOffDutyRequest. Only
        preceding_fdp.location drove the location branch, so a caller setting
        following_off_duty_location alone had it silently ignored. A
        disagreement is now rejected rather than resolved arbitrarily.
        """
        if (
            self.following_off_duty_location is not None
            and self.following_off_duty_location != self.preceding_fdp.location
        ):
            raise ValueError(
                "following_off_duty_location "
                f"({self.following_off_duty_location!r}) and "
                f"preceding_fdp.location ({self.preceding_fdp.location!r}) "
                "describe the same thing — where the off-duty period is taken "
                "— and must agree. Omit one of them."
            )
        return self

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "appendix": "3",
                    "preceding_fdp": {
                        "start_utc": "2026-03-28T22:00:00Z",
                        "end_utc": "2026-03-29T08:30:00Z",
                        "duration_hours": 10.5,
                        "post_fdp_duty_hours": 0.0,
                        "location": "away",
                        "was_extended": False,
                    },
                    "actual_off_duty_hours": 10.5,
                }
            ]
        }
    }


# ═══════════════════════════════════════════════════════════════════════
# POST /validate/cumulative
# ═══════════════════════════════════════════════════════════════════════

class FdpHistoryRecord(BaseModel):
    """A single FDP entry in a pilot's history log."""

    fdp_start_utc: datetime = Field(description="FDP start time (ISO 8601 UTC).")
    fdp_end_utc: datetime = Field(description="FDP end time (ISO 8601 UTC).")
    actual_flight_time_hours: float = Field(
        ge=0,
        description="Actual flight time within this FDP (hours).",
    )
    actual_duty_time_hours: float = Field(
        ge=0,
        description="Total duty time for this FDP including pre/post-flight duties (hours).",
    )
    local_time_offset_hours: Optional[float] = Field(
        default=None,
        description=(
            "UTC offset of the local time zone at the crew base for this FDP. "
            "Required for recovery block local-night detection. "
            "If omitted, local-night checks are skipped with a data_unavailable note."
        ),
    )

    @field_validator("local_time_offset_hours")
    @classmethod
    def _check_offset(cls, v):
        return validate_utc_offset(v, "local_time_offset_hours")

    @model_validator(mode="after")
    def _check_times(self) -> "FdpHistoryRecord":
        require_end_after_start(
            self.fdp_start_utc, self.fdp_end_utc,
            "fdp_start_utc", "fdp_end_utc",
        )
        return self


class CumulativeSummaryInput(BaseModel):
    """
    Pre-aggregated cumulative totals — accepted as a fallback when
    a full FDP history log is not available.

    Provide whichever totals are relevant to your appendix.
    Window definitions:
      168h = rolling 7-day window
      336h = rolling 14-day window
      28d  = rolling 28-day window
      90d  = rolling 90-day window
      365d = rolling 365-day window
      384h = rolling 16-day window (Appendix 4A, 5A)
    """

    flight_time_168h_hours: Optional[float] = Field(
        default=None, ge=0, description="Flight time in the previous 168h (Appendix 5)."
    )
    flight_time_28d_hours: Optional[float] = Field(
        default=None, ge=0, description="Flight time in the previous 28 days."
    )
    flight_time_90d_hours: Optional[float] = Field(
        default=None, ge=0, description="Flight time in the previous 90 days (Appendix 5)."
    )
    flight_time_365d_hours: Optional[float] = Field(
        default=None, ge=0, description="Flight time in the previous 365 days."
    )
    flight_time_384h_hours: Optional[float] = Field(
        default=None, ge=0, description="Flight time in the previous 384h (Appendix 5A)."
    )
    duty_time_168h_hours: Optional[float] = Field(
        default=None, ge=0, description="Duty time in the previous 168h."
    )
    duty_time_336h_hours: Optional[float] = Field(
        default=None, ge=0, description="Duty time in the previous 336h."
    )
    recovery_36h_block_in_168h: Optional[bool] = Field(
        default=None,
        description=(
            "True if a 36h+ off-duty block including 2 local nights has occurred "
            "in the previous 168h. Required for Appendices 1–4, 4B, 6."
        ),
    )
    recovery_36h_block_in_336h: Optional[bool] = Field(
        default=None,
        description=(
            "True if a 36h+ off-duty block including 2 local nights has occurred "
            "in the previous 336h. Required for Appendices 4B, 5."
        ),
    )
    recovery_72h_block_in_504h: Optional[bool] = Field(
        default=None,
        description=(
            "True if a 72h+ off-duty block including 3 local nights has occurred "
            "in the previous 504h. Required for Appendices 4B, 5."
        ),
    )
    days_off_in_28d: Optional[int] = Field(
        default=None, ge=0,
        description="Number of full days off in the previous 28 days. Required for Appendices 1–4, 6.",
    )
    days_off_in_384h: Optional[int] = Field(
        default=None, ge=0,
        description="Number of full days off in the previous 384h. Required for Appendices 4A, 5A.",
    )


class ValidateCumulativeRequest(BaseModel):
    """Request body for POST /validate/cumulative."""

    appendix: AppendixId = Field(description="Which appendix rules apply.")
    as_of_utc: datetime = Field(
        description=(
            "The point in time to evaluate cumulative limits against — "
            "normally the start of the next FDP. Rolling windows are "
            "computed backwards from this timestamp."
        )
    )
    fdp_log: Optional[list[FdpHistoryRecord]] = Field(
        default=None,
        description=(
            "Ordered list of recent FDPs (chronological). "
            "The API computes all rolling windows from this data. "
            "Preferred over `summary` — provide at least 365 days of history "
            "for full coverage."
        ),
    )
    summary: Optional[CumulativeSummaryInput] = Field(
        default=None,
        description=(
            "Pre-aggregated totals for each rolling window. "
            "Used as a fallback when a full FDP log is not available. "
            "Only fields relevant to your appendix need to be provided."
        ),
    )

    @model_validator(mode="after")
    def require_log_or_summary(self) -> "ValidateCumulativeRequest":
        if self.fdp_log is None and self.summary is None:
            raise ValueError(
                "At least one of 'fdp_log' or 'summary' must be provided."
            )
        return self

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "appendix": "3",
                    "as_of_utc": "2026-03-29T22:00:00Z",
                    "fdp_log": [
                        {
                            "fdp_start_utc": "2026-03-05T22:00:00Z",
                            "fdp_end_utc": "2026-03-06T08:00:00Z",
                            "actual_flight_time_hours": 8.0,
                            "actual_duty_time_hours": 10.0,
                            "local_time_offset_hours": 8.0,
                        },
                        {
                            "fdp_start_utc": "2026-03-07T22:00:00Z",
                            "fdp_end_utc": "2026-03-08T08:00:00Z",
                            "actual_flight_time_hours": 7.5,
                            "actual_duty_time_hours": 9.5,
                            "local_time_offset_hours": 8.0,
                        },
                    ],
                }
            ]
        }
    }


# ═══════════════════════════════════════════════════════════════════════
# POST /validate/sequence
# ═══════════════════════════════════════════════════════════════════════

class SequenceFdpEvent(BaseModel):
    """A single FDP within a duty sequence."""

    event_type: Literal["fdp"] = "fdp"
    fdp_start_utc: datetime = Field(description="FDP start time (ISO 8601 UTC).")
    fdp_end_utc: datetime = Field(description="FDP end time (ISO 8601 UTC).")
    actual_flight_time_hours: float = Field(
        ge=0, description="Flight time within this FDP (hours)."
    )
    actual_duty_time_hours: float = Field(
        ge=0, description="Total duty time including pre/post-flight (hours)."
    )
    local_time_offset_hours: float = Field(
        description="UTC offset at the departure point (hours). Used to determine early-start status."
    )
    sectors: int = Field(ge=1, description="Number of sectors (flights) in this FDP.")

    @field_validator("local_time_offset_hours")
    @classmethod
    def _check_offset(cls, v):
        return validate_utc_offset(v, "local_time_offset_hours")

    @model_validator(mode="after")
    def _check_times(self) -> "SequenceFdpEvent":
        require_end_after_start(
            self.fdp_start_utc, self.fdp_end_utc,
            "fdp_start_utc", "fdp_end_utc",
        )
        return self


class SequenceOdpEvent(BaseModel):
    """An off-duty period within a duty sequence."""

    event_type: Literal["off_duty"] = "off_duty"
    start_utc: datetime = Field(description="Start of off-duty period (ISO 8601 UTC).")
    end_utc: datetime = Field(description="End of off-duty period (ISO 8601 UTC).")
    duration_hours: float = Field(
        ge=0, description="Duration of the off-duty period (hours)."
    )
    location: Location = Field(
        default="away",
        description="Whether the off-duty period is at home base or away.",
    )

    @model_validator(mode="after")
    def _check_times(self) -> "SequenceOdpEvent":
        require_end_after_start(
            self.start_utc, self.end_utc, "start_utc", "end_utc",
        )
        require_duration_agrees(
            self.start_utc, self.end_utc, self.duration_hours,
            "duration_hours", "start_utc", "end_utc",
        )
        return self


SequenceEvent = Annotated[
    Union[SequenceFdpEvent, SequenceOdpEvent],
    Field(discriminator="event_type"),
]


class ValidateSequenceRequest(BaseModel):
    """Request body for POST /validate/sequence."""

    appendix: AppendixId = Field(description="Which appendix rules apply.")
    events: list[SequenceEvent] = Field(
        min_length=1,
        description=(
            "Ordered sequence of FDP and off-duty events (chronological). "
            "Each event must have `event_type` set to either 'fdp' or 'off_duty'. "
            "The sequence should cover the full roster window being validated."
        ),
    )

    @field_validator("events")
    @classmethod
    def _check_ordered(cls, v):
        return require_events_ordered(v)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "appendix": "3",
                    "events": [
                        {
                            "event_type": "fdp",
                            "fdp_start_utc": "2026-03-24T22:00:00Z",
                            "fdp_end_utc": "2026-03-25T08:00:00Z",
                            "actual_flight_time_hours": 7.5,
                            "actual_duty_time_hours": 10.0,
                            "local_time_offset_hours": 8.0,
                            "sectors": 3,
                        },
                        {
                            "event_type": "off_duty",
                            "start_utc": "2026-03-25T08:00:00Z",
                            "end_utc": "2026-03-25T22:00:00Z",
                            "duration_hours": 14.0,
                            "location": "away",
                        },
                        {
                            "event_type": "fdp",
                            "fdp_start_utc": "2026-03-25T22:00:00Z",
                            "fdp_end_utc": "2026-03-26T08:00:00Z",
                            "actual_flight_time_hours": 8.0,
                            "actual_duty_time_hours": 10.0,
                            "local_time_offset_hours": 8.0,
                            "sectors": 3,
                        },
                    ],
                }
            ]
        }
    }


# ═══════════════════════════════════════════════════════════════════════
# POST /validate/roster
# ═══════════════════════════════════════════════════════════════════════

class RosterFdpEvent(BaseModel):
    """A single FDP within a roster — full detail version of SequenceFdpEvent."""

    event_type: Literal["fdp"] = "fdp"
    fdp_start_utc: datetime = Field(description="FDP start time (ISO 8601 UTC).")
    fdp_end_utc: datetime = Field(description="FDP end time (ISO 8601 UTC).")
    actual_flight_time_hours: float = Field(
        ge=0, description="Flight time within this FDP (hours)."
    )
    actual_duty_time_hours: float = Field(
        ge=0, description="Total duty time including pre/post-flight duties (hours)."
    )
    local_time_offset_hours: float = Field(
        description="UTC offset at the departure point (hours)."
    )
    sectors: int = Field(ge=1, description="Number of sectors (flights) in this FDP.")
    extension: Optional[ExtensionInput] = Field(
        default=None,
        description="Extension applied to this FDP, if any.",
    )
    acclimatisation: Optional[AcclimatisationInput] = Field(
        default=None,
        description="Acclimatisation state (Appendix 2).",
    )
    augmented_crew: Optional[AugmentedCrewInput] = Field(
        default=None,
        description="Augmented crew configuration (Appendix 2).",
    )
    split_duty: Optional[SplitDutyInput] = Field(
        default=None,
        description="Split duty rest details, if applicable.",
    )
    single_pilot: bool = Field(
        default=False,
        description="Whether this is a single-pilot operation.",
    )

    @field_validator("local_time_offset_hours")
    @classmethod
    def _check_offset(cls, v):
        return validate_utc_offset(v, "local_time_offset_hours")

    @model_validator(mode="after")
    def _check_times(self) -> "RosterFdpEvent":
        require_end_after_start(
            self.fdp_start_utc, self.fdp_end_utc,
            "fdp_start_utc", "fdp_end_utc",
        )
        return self


class RosterOdpEvent(BaseModel):
    """An off-duty period within a roster."""

    event_type: Literal["off_duty"] = "off_duty"
    start_utc: datetime = Field(description="Start of off-duty period (ISO 8601 UTC).")
    end_utc: datetime = Field(description="End of off-duty period (ISO 8601 UTC).")
    duration_hours: float = Field(
        ge=0, description="Duration of the off-duty period (hours)."
    )
    following_includes_local_night: bool = Field(
        default=True,
        description="True if the next following off-duty period includes a local night.",
    )
    location: Location = Field(
        default="away",
        description="Whether the off-duty period is at home base or away.",
    )

    @model_validator(mode="after")
    def _check_times(self) -> "RosterOdpEvent":
        require_end_after_start(
            self.start_utc, self.end_utc, "start_utc", "end_utc",
        )
        require_duration_agrees(
            self.start_utc, self.end_utc, self.duration_hours,
            "duration_hours", "start_utc", "end_utc",
        )
        return self


class RosterRestDayEvent(BaseModel):
    """An explicit planned rest day (free day) within a roster."""

    event_type: Literal["rest_day"] = "rest_day"
    start_utc: datetime = Field(description="Start of the rest day / rest period (ISO 8601 UTC).")
    end_utc: datetime = Field(description="End of the rest day / rest period (ISO 8601 UTC).")
    count: int = Field(
        default=1, ge=1,
        description="Number of full calendar days off. Defaults to 1.",
    )
    includes_local_night: bool = Field(
        default=True,
        description="True if the rest period includes a local night.",
    )

    @model_validator(mode="after")
    def _check_times(self) -> "RosterRestDayEvent":
        require_end_after_start(
            self.start_utc, self.end_utc, "start_utc", "end_utc",
        )
        return self


RosterEvent = Annotated[
    Union[RosterFdpEvent, RosterOdpEvent, RosterRestDayEvent],
    Field(discriminator="event_type"),
]


class FdpValidationItem(BaseModel):
    """Validation result for a single FDP within a roster."""

    fdp_number: int = Field(description="Sequential FDP number within the roster (1-based).")
    fdp_start_utc: datetime = Field(description="FDP start time.")
    fdp_end_utc: datetime = Field(description="FDP end time.")
    duration_hours: float = Field(description="FDP duration (hours).")
    crosses_wocl: bool = Field(
        description=(
            "Computed, not caller-supplied. True if this FDP infringes the WOCL "
            "(§6.1/§6.2: any operation during 0200–0559 local time), derived from "
            "fdp_start_utc, fdp_end_utc, local_time_offset_hours and "
            "acclimatisation. Used for consecutive-WOCL tracking (§13.2)."
        ),
    )
    valid: bool = Field(description="True if no violations were found for this FDP.")
    violations: list[Violation] = Field(default_factory=list)
    checks: list[CheckResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    calculation_notes: list[str] = Field(default_factory=list)


class OdpValidationItem(BaseModel):
    """Validation result for a single off-duty period within a roster."""

    odp_number: int = Field(description="Sequential ODP number within the roster (1-based).")
    start_utc: datetime = Field(description="Off-duty period start time.")
    end_utc: datetime = Field(description="Off-duty period end time.")
    duration_hours: float = Field(description="Off-duty period duration (hours).")
    includes_local_night: bool = Field(
        description=(
            "Computed, not caller-supplied. True if this off-duty period includes "
            "a local night (§6.1: 8 consecutive hours including 2200–0500 local "
            "time), derived from start_utc, end_utc and the surrounding FDPs' "
            "local_time_offset_hours. Used for recovery-block and "
            "WOCL-infringement-reset checks (§13.2)."
        ),
    )
    valid: bool = Field(description="True if no violations were found for this ODP.")
    violations: list[Violation] = Field(default_factory=list)
    checks: list[CheckResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RosterSummary(BaseModel):
    """Aggregate counts and totals for the validated roster."""

    total_fdps: int = Field(description="Total number of FDPs in the roster.")
    total_off_duty_periods: int = Field(description="Total number of off-duty periods in the roster.")
    total_rest_days: int = Field(description="Total number of explicit rest day events in the roster.")
    total_flight_time_hours: float = Field(description="Sum of actual flight time across all FDPs (hours).")
    total_duty_time_hours: float = Field(description="Sum of actual duty time across all FDPs (hours).")
    fdp_violations: int = Field(description="Number of FDPs with at least one violation.")
    odp_violations: int = Field(description="Number of ODPs with at least one violation.")
    sequence_violations: int = Field(description="Number of sequence-level violations (§13.2, consecutive starts).")
    cumulative_violations: int = Field(description="Number of cumulative limit violations.")
    total_violations: int = Field(description="Total number of distinct violations across all checks.")
    checks_run: int = Field(
        default=0,
        description="Cumulative checks actually evaluated against supplied data.",
    )
    checks_skipped: int = Field(
        default=0,
        description=(
            "Cumulative checks that could not be established because the "
            "lookback window reaches back further than the supplied history. "
            "Non-zero means this roster has not been shown to be compliant, "
            "only shown not to breach the checks that could run — which is "
            "the normal outcome when no prior history is supplied. Not "
            "reflected in `valid`. Supply a prior_fdp_log or prior_summary to "
            "resolve them."
        ),
    )


class ValidateRosterRequest(BaseModel):
    """Request body for POST /validate/roster."""

    appendix: AppendixId = Field(description="Which appendix rules apply.")
    roster_start_utc: datetime = Field(description="Start of the roster period (ISO 8601 UTC).")
    roster_end_utc: datetime = Field(description="End of the roster period (ISO 8601 UTC).")
    events: list[RosterEvent] = Field(
        min_length=1,
        description=(
            "Ordered roster events (chronological). Each event must have "
            "`event_type` set to 'fdp', 'off_duty', or 'rest_day'."
        ),
    )
    prior_fdp_log: Optional[list[FdpHistoryRecord]] = Field(
        default=None,
        description=(
            "FDP history before the roster period, used for cumulative limit checks. "
            "Provide at least 365 days of history for full coverage. "
            "Preferred over `prior_summary`."
        ),
    )
    prior_summary: Optional[CumulativeSummaryInput] = Field(
        default=None,
        description=(
            "Pre-aggregated cumulative totals from before the roster period. "
            "Used as a fallback when a full prior FDP log is unavailable."
        ),
    )

    @field_validator("events")
    @classmethod
    def _check_ordered(cls, v):
        return require_events_ordered(v)

    @model_validator(mode="after")
    def _check_window(self) -> "ValidateRosterRequest":
        require_end_after_start(
            self.roster_start_utc, self.roster_end_utc,
            "roster_start_utc", "roster_end_utc",
        )
        return self

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "appendix": "3",
                    "roster_start_utc": "2026-03-24T00:00:00Z",
                    "roster_end_utc": "2026-03-27T00:00:00Z",
                    "events": [
                        {
                            "event_type": "fdp",
                            "fdp_start_utc": "2026-03-24T22:00:00Z",
                            "fdp_end_utc": "2026-03-25T08:00:00Z",
                            "actual_flight_time_hours": 7.5,
                            "actual_duty_time_hours": 10.0,
                            "local_time_offset_hours": 8.0,
                            "sectors": 3,
                        },
                        {
                            "event_type": "off_duty",
                            "start_utc": "2026-03-25T08:00:00Z",
                            "end_utc": "2026-03-25T22:00:00Z",
                            "duration_hours": 14.0,
                            "location": "away",
                        },
                        {
                            "event_type": "fdp",
                            "fdp_start_utc": "2026-03-25T22:00:00Z",
                            "fdp_end_utc": "2026-03-26T08:00:00Z",
                            "actual_flight_time_hours": 8.0,
                            "actual_duty_time_hours": 10.0,
                            "local_time_offset_hours": 8.0,
                            "sectors": 3,
                        },
                        {
                            "event_type": "rest_day",
                            "start_utc": "2026-03-26T08:00:00Z",
                            "end_utc": "2026-03-27T00:00:00Z",
                            "count": 1,
                            "includes_local_night": True,
                        },
                    ],
                }
            ]
        }
    }


class RosterValidationResponse(BaseModel):
    """
    Full roster validation result with structured per-event breakdown.

    Each FDP and off-duty period is validated individually. Sequence-level
    checks (§13.2 WOCL, consecutive early starts) and cumulative rolling-window
    limits are evaluated across the full roster. A flat `all_violations` list
    aggregates every violation for quick scanning.
    """

    valid: bool = Field(description="True if no violations were found across the entire roster.")
    appendix: str = Field(description="Appendix used for validation.")
    roster_start_utc: datetime = Field(description="Start of the roster period.")
    roster_end_utc: datetime = Field(description="End of the roster period.")
    summary: RosterSummary = Field(description="Aggregate counts and totals.")
    fdp_results: list[FdpValidationItem] = Field(
        default_factory=list,
        description="Per-FDP validation results.",
    )
    odp_results: list[OdpValidationItem] = Field(
        default_factory=list,
        description="Per-ODP validation results.",
    )
    sequence_checks: list[CheckResult] = Field(
        default_factory=list,
        description="Sequence-level checks (§13.2 WOCL, consecutive early starts).",
    )
    sequence_violations: list[Violation] = Field(
        default_factory=list,
        description="Sequence-level violations.",
    )
    cumulative_result: dict = Field(
        default_factory=dict,
        description="Raw cumulative validation result (ValidationResponse shape).",
    )
    all_violations: list[Violation] = Field(
        default_factory=list,
        description="Flat list of all violations across FDP, ODP, sequence, and cumulative checks.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-violating advisory notes.",
    )
