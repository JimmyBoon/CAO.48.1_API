"""
Pydantic request and response models for the /validate/* endpoints.

POST /validate/fdp       — FDP validation
POST /validate/off-duty  — Off-duty period validation
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

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
