"""
Pydantic request and response models for the /validate/* endpoints.

POST /validate/fdp        — FDP validation
POST /validate/off-duty   — Off-duty period validation
POST /validate/cumulative — Rolling-window cumulative limit checks
POST /validate/sequence   — Ordered FDP/ODP sequence validation
"""

from datetime import datetime
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

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
    passed: bool = Field(description="Whether the check passed.")
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

    The top-level `valid` flag is False if any violations were detected.
    All checks evaluated — including those that passed — are included in
    the `checks` list for full auditability.
    """

    valid: bool = Field(
        description="True if no violations were found; False otherwise.",
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
    captains_authority: bool = Field(
        default=False,
        description="Whether the extension was invoked under captain's authority.",
    )
    pre_planned: bool = Field(
        default=False,
        description="Whether the extension was pre-planned (operator-approved).",
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
    following_off_duty_location: Location = Field(
        default="away",
        description="Where the off-duty period is being taken.",
    )
    following_off_duty_includes_local_night: bool = Field(
        default=True,
        description="Whether the off-duty period includes a local night.",
    )
    acclimatisation_state: AcclimState = Field(
        default="not_applicable",
        description="Acclimatisation state (for displacement time calculation under Appendix 2).",
    )

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
    crosses_wocl: bool = Field(
        default=False,
        description=(
            "True if this FDP includes any operation during the WOCL "
            "(0200–0559 local time). Used to track consecutive WOCL infringements."
        ),
    )


class SequenceOdpEvent(BaseModel):
    """An off-duty period within a duty sequence."""

    event_type: Literal["off_duty"] = "off_duty"
    start_utc: datetime = Field(description="Start of off-duty period (ISO 8601 UTC).")
    end_utc: datetime = Field(description="End of off-duty period (ISO 8601 UTC).")
    duration_hours: float = Field(
        ge=0, description="Duration of the off-duty period (hours)."
    )
    includes_local_night: bool = Field(
        default=False,
        description=(
            "True if this off-duty period includes a local night "
            "(a period of 8 consecutive hours including 0100–0559 local time). "
            "Used for recovery block and WOCL-infringement reset checks."
        ),
    )
    location: Location = Field(
        default="away",
        description="Whether the off-duty period is at home base or away.",
    )


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
                            "crosses_wocl": False,
                        },
                        {
                            "event_type": "off_duty",
                            "start_utc": "2026-03-25T08:00:00Z",
                            "end_utc": "2026-03-25T22:00:00Z",
                            "duration_hours": 14.0,
                            "includes_local_night": True,
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
                            "crosses_wocl": False,
                        },
                    ],
                }
            ]
        }
    }
