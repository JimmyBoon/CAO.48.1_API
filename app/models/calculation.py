"""
Pydantic request and response models for the /calculate/* endpoints.

POST /calculate/max-fdp — Maximum FDP calculator
POST /calculate/min-off-duty — Minimum off-duty period calculator
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models._validators import (
    require_duration_agrees,
    require_end_after_start,
    validate_utc_offset,
)


# ─── Common enumerations ──────────────────────────────────────────────

AppendixId = Literal["1", "2", "3", "4", "4A", "4B", "5", "5A", "6"]
AcclimState = Literal["acclimatised", "unknown", "not_applicable"]
Accommodation = Literal["sleeping", "resting", "none"]
Location = Literal["home_base", "away"]
CrewRestClass = Literal["class_1", "class_2", "class_3"]


# ═══════════════════════════════════════════════════════════════════════
# POST /calculate/max-fdp
# ═══════════════════════════════════════════════════════════════════════

# ─── Request models ───────────────────────────────────────────────────

class AcclimatisationInput(BaseModel):
    """Acclimatisation state and offset for Appendix 2."""
    state: AcclimState = Field(description="Acclimatisation state of the FCM.")
    acclimatised_time_offset_hours: Optional[float] = Field(
        default=None,
        description="UTC offset of the acclimatised time zone (hours). Required when state='acclimatised' under Appendix 2.",
    )

    @field_validator("acclimatised_time_offset_hours")
    @classmethod
    def _check_offset(cls, v):
        return validate_utc_offset(v, "acclimatised_time_offset_hours")


class InFlightRestEntry(BaseModel):
    """In-flight rest record for one FCM in an augmented crew."""
    fcm_id: str = Field(description="Identifier for the flight crew member.")
    rest_hours: float = Field(
        ge=0,
        description=(
            "Consecutive hours of in-flight rest. §5.3(d) and §5.3(g)(ii) both "
            "require the rest to be *consecutive*, so a total accumulated "
            "across several short breaks does not satisfy them."
        ),
    )
    at_controls_final_landing: bool = Field(
        description="Whether this FCM will be at the controls for the final landing.",
    )
    rest_within_8h_before_landing: Optional[bool] = Field(
        default=None,
        description=(
            "For §5.3(f)(ii)(A): whether this FCM's 2 consecutive hours of "
            "in-flight rest fell within the 8-hour period ending at the "
            "scheduled time of the landing at the end of the second sector. "
            "Only relevant on a 2-sector FDP exceeding 14 hours."
        ),
    )


class AugmentedCrewInput(BaseModel):
    """Augmented crew configuration (Appendix 2 only)."""
    additional_fcms: int = Field(
        ge=1, le=2,
        description="Number of additional flight crew members (1 or 2).",
    )
    rest_facility_class: CrewRestClass = Field(
        description="Rest facility classification: class_1, class_2, or class_3.",
    )
    in_flight_rest_hours_per_fcm: Optional[list[InFlightRestEntry]] = Field(
        default=None,
        description=(
            "In-flight rest details per FCM. Required to evaluate §5.3(d) and "
            "§5.3(g)(ii). Where omitted, those conditions are reported as "
            "data_unavailable — they are not treated as satisfied."
        ),
    )
    second_sector_scheduled_flight_time_hours: Optional[float] = Field(
        default=None,
        ge=0,
        description=(
            "For §5.3(f)(ii)(B): scheduled flight time of the second sector. "
            "On a 2-sector FDP exceeding 14 hours, §5.3(f)(ii) is satisfied by "
            "either this being at least 9 hours, or by the rest timing in "
            "§5.3(f)(ii)(A)."
        ),
    )


class SplitDutyInput(BaseModel):
    """Split duty rest details."""
    rest_start_utc: str = Field(description="Rest period start time (ISO 8601 UTC).")
    rest_end_utc: str = Field(description="Rest period end time (ISO 8601 UTC).")
    accommodation: Accommodation = Field(description="Type of accommodation during rest.")
    duration_hours: float = Field(
        gt=0,
        description="Duration of the rest period in hours.",
    )
    overlaps_2300_0529: Optional[bool] = Field(
        default=None,
        description="Whether the rest period overlaps the 2300-0529 local time window.",
    )

    @model_validator(mode="after")
    def _check_times(self) -> "SplitDutyInput":
        require_end_after_start(
            self.rest_start_utc, self.rest_end_utc,
            "rest_start_utc", "rest_end_utc",
        )
        require_duration_agrees(
            self.rest_start_utc, self.rest_end_utc, self.duration_hours,
            "duration_hours", "rest_start_utc", "rest_end_utc",
        )
        return self


class MaxFdpRequest(BaseModel):
    """Request body for POST /calculate/max-fdp."""

    appendix: AppendixId = Field(description="Which appendix rules apply.")
    fdp_start_utc: str = Field(description="FDP start time (ISO 8601 UTC).")
    local_time_offset_hours: float = Field(
        description="UTC offset of the local time zone at the departure point (hours).",
    )
    sectors: int = Field(
        ge=1,
        description="Number of sectors (flights) in the FDP.",
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
        description="Split duty rest details, if a split duty rest is planned.",
    )
    consecutive_early_starts: int = Field(
        default=0, ge=0,
        description="Number of consecutive early starts (0500-0659 local) preceding this FDP.",
    )
    consecutive_wocl_infringements: int = Field(
        default=0, ge=0,
        description="Number of consecutive WOCL infringements preceding this FDP.",
    )
    single_pilot: bool = Field(
        default=False,
        description="Whether this is a single-pilot operation (for Appendices 4B, 5).",
    )
    preceding_off_duty_hours: Optional[float] = Field(
        default=None,
        description="Duration of preceding off-duty period in hours. Required for Appendix 2 unknown acclimatisation table lookup.",
    )

    @field_validator("local_time_offset_hours")
    @classmethod
    def _check_offset(cls, v):
        return validate_utc_offset(v, "local_time_offset_hours")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "appendix": "3",
                    "fdp_start_utc": "2026-03-28T22:00:00Z",
                    "local_time_offset_hours": 8,
                    "sectors": 3,
                    "split_duty": {
                        "rest_start_utc": "2026-03-29T04:00:00Z",
                        "rest_end_utc": "2026-03-29T08:00:00Z",
                        "accommodation": "sleeping",
                        "duration_hours": 4,
                    },
                    "consecutive_early_starts": 2,
                    "consecutive_wocl_infringements": 1,
                }
            ]
        }
    }


# ─── Response models ──────────────────────────────────────────────────

class ConditionResult(BaseModel):
    """
    One condition attached to a provision — a reduction, or an extension.

    Used wherever the API must distinguish a condition it checked from one the
    caller has to establish for themselves.
    """
    clause: str = Field(description="Clause reference for this specific condition.")
    description: str = Field(description="What the condition requires.")


class CalculationViolation(BaseModel):
    """A hard violation detected during limit calculation."""
    check: str = Field(description="Check identifier.")
    clause: str = Field(description="CAO 48.1 clause reference.")
    severity: str = Field(default="hard_limit", description="Violation severity.")
    actual: Optional[float] = Field(default=None, description="Observed value.")
    limit: Optional[float] = Field(default=None, description="Permitted value.")
    detail: str = Field(description="Human-readable description.")
    remediation: str = Field(default="", description="Suggested corrective action.")


class ExtensionProvision(BaseModel):
    """One extension provision available under an appendix."""
    type: str = Field(description="'unforeseen' or 'urgent'.")
    clause: str = Field(description="Clause granting this extension.")
    max_hours: float = Field(description="Maximum hours this provision allows.")
    extended_fdp_ceiling_hours: Optional[float] = Field(
        default=None,
        description=(
            "Ceiling on the extended FDP where the clause states one. Null "
            "where the clause states no explicit ceiling — App 4B §3.1(a) is "
            "the case in point; its 16h proviso attaches to §3.1(b) only."
        ),
    )


class ExtensionOptions(BaseModel):
    """Extension provisions and the conditions gating them."""
    available: bool = Field(description="Whether this appendix permits any extension.")
    provisions: list[ExtensionProvision] = Field(default_factory=list)
    conditions_caller_must_verify: list[ConditionResult] = Field(
        default_factory=list,
        description=(
            "Facts gating the extension that this API cannot check — "
            "operations manual procedures, urgency determinations, and the "
            "PIC's consultation and fitness assessment."
        ),
    )
    clause_cumulative_crosscheck: str = Field(
        default="",
        description=(
            "Clause requiring that an extension not breach cumulative flight "
            "time limits (App 4B §3.6). Not evaluated by /validate/fdp."
        ),
    )


class Adjustment(BaseModel):
    """A single adjustment step in the FDP calculation."""
    clause: str = Field(description="CAO 48.1 clause reference, e.g. '§3.1'.")
    description: str = Field(description="Human-readable description of the adjustment.")
    adjustment_hours: float = Field(description="Hours added or removed by this step.")
    running_total_hours: float = Field(description="Cumulative FDP limit after this step.")


class MaxFdpResponse(BaseModel):
    """Response for POST /calculate/max-fdp."""

    appendix: str = Field(description="Appendix used for calculation.")
    base_max_fdp_hours: float = Field(description="Base FDP limit from table lookup.")
    adjustments: list[Adjustment] = Field(
        default_factory=list,
        description="Ordered list of adjustments applied to the base limit.",
    )
    wocl_early_start_reduction_hours: float = Field(
        default=0,
        description="FDP reduction due to consecutive WOCL infringements or early starts.",
    )
    final_max_fdp_hours: float = Field(description="Final maximum FDP after all adjustments.")
    max_extension_hours: float = Field(
        default=0,
        description="Maximum unforeseen/urgent extension allowance (hours).",
    )
    absolute_max_with_extension_hours: float = Field(
        description="Absolute ceiling: final_max_fdp + max_extension.",
    )
    post_split_max_hours: Optional[float] = Field(
        default=None,
        description="Maximum FDP permitted after split duty rest ends (hours). Null if no split duty.",
    )
    flight_time_limit_hours: Optional[float] = Field(
        default=None,
        description="Maximum flight time per FDP (hours). Null if no per-FDP limit.",
    )
    violations: list[CalculationViolation] = Field(
        default_factory=list,
        description=(
            "Hard violations detected while calculating the limit — a duty the "
            "instrument prohibits outright rather than merely constrains. A "
            "6th consecutive early start is the main case: no maximum FDP "
            "figure makes that assignment lawful."
        ),
    )
    extension_options: Optional[ExtensionOptions] = Field(
        default=None,
        description="Every extension provision available under this appendix.",
    )
    calculation_notes: list[str] = Field(
        default_factory=list,
        description="Human-readable calculation breakdown with clause references.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "appendix": "3",
                    "base_max_fdp_hours": 13.0,
                    "adjustments": [
                        {
                            "clause": "§3.1",
                            "description": "Split-duty rest >=4h with sleeping accommodation: +4h (capped at 16h)",
                            "adjustment_hours": 3.0,
                            "running_total_hours": 16.0,
                        }
                    ],
                    "wocl_early_start_reduction_hours": 0,
                    "final_max_fdp_hours": 16.0,
                    "max_extension_hours": 1.0,
                    "absolute_max_with_extension_hours": 17.0,
                    "post_split_max_hours": 6.0,
                    "flight_time_limit_hours": 10.5,
                    "calculation_notes": [
                        "FDP start local time: 0600 -> Table 2.1 band 0600-0659, 1-3 sectors = 12h",
                        "Split duty: 4h sleeping accommodation -> +4h, capped at 16h (§3.1)",
                        "Post-split FDP must not exceed 6h (§3.5)",
                    ],
                }
            ]
        }
    }


# ═══════════════════════════════════════════════════════════════════════
# POST /calculate/min-off-duty
# ═══════════════════════════════════════════════════════════════════════

# ─── Request models ───────────────────────────────────────────────────

class PrecedingSplitDutyInput(BaseModel):
    """Split duty rest taken during the preceding FDP."""
    duration_hours: float = Field(gt=0, description="Duration of the split duty rest (hours).")
    accommodation: Accommodation = Field(description="Accommodation type during rest.")
    overlaps_2300_0529: bool = Field(
        default=False,
        description="Whether rest overlapped the 2300-0529 local time window.",
    )


class PrecedingFdpInput(BaseModel):
    """Details of the FDP preceding the off-duty period."""
    start_utc: str = Field(description="FDP start time (ISO 8601 UTC).")
    end_utc: str = Field(description="FDP end time (ISO 8601 UTC).")
    duration_hours: float = Field(gt=0, description="FDP duration in hours.")
    post_fdp_duty_hours: float = Field(
        default=0, ge=0,
        description="Additional duty time after FDP end (e.g. post-flight duties).",
    )
    location: Location = Field(
        description=(
            "Where the off-duty period following this FDP will be taken. "
            "Describes the same fact as the request's "
            "`following_off_duty_location`; supply both only if they agree."
        ),
    )
    split_duty: Optional[PrecedingSplitDutyInput] = Field(
        default=None,
        description="Split duty rest details, if taken during this FDP.",
    )
    was_extended: bool = Field(
        default=False,
        description="Whether the FDP was extended beyond the normal limit.",
    )
    extension_hours: float = Field(
        default=0, ge=0,
        description="Hours of extension applied.",
    )

    @model_validator(mode="after")
    def _check_times(self) -> "PrecedingFdpInput":
        require_end_after_start(
            self.start_utc, self.end_utc, "start_utc", "end_utc",
        )
        require_duration_agrees(
            self.start_utc, self.end_utc, self.duration_hours,
            "duration_hours", "start_utc", "end_utc",
        )
        return self


class PrecedingOffDutyInput(BaseModel):
    """Details of the off-duty period preceding the FDP."""
    duration_hours: float = Field(gt=0, description="Duration of the preceding off-duty period (hours).")
    included_local_night: bool = Field(description="Whether the preceding ODP included a local night.")


class MinOffDutyRequest(BaseModel):
    """Request body for POST /calculate/min-off-duty."""

    appendix: AppendixId = Field(description="Which appendix rules apply.")
    preceding_fdp: PrecedingFdpInput = Field(description="Details of the preceding FDP.")
    preceding_off_duty: Optional[PrecedingOffDutyInput] = Field(
        default=None,
        description="Details of the off-duty period before the preceding FDP. Required for reduction eligibility checks.",
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
        description="Whether the following off-duty period will include a local night.",
    )
    acclimatisation_state: AcclimState = Field(
        default="not_applicable",
        description=(
            "Acclimatisation state. Under Appendix 2 an unknown state selects "
            "§10.1(c) / §10.2(b), which ignore home base / away, and blocks the "
            "§10.4 reduction via §10.4(c)."
        ),
    )
    fdp_start_offset_hours: Optional[float] = Field(
        default=None,
        description=(
            "UTC offset at the location where the preceding FDP started. "
            "Supply with odp_start_offset_hours to compute displacement time "
            "(Appendices 2, 4, 4B)."
        ),
    )
    odp_start_offset_hours: Optional[float] = Field(
        default=None,
        description=(
            "UTC offset at the location where the off-duty period starts. "
            "Supply with fdp_start_offset_hours to compute displacement time."
        ),
    )

    @model_validator(mode="after")
    def _check_location_agreement(self) -> "MinOffDutyRequest":
        """
        `following_off_duty_location` and `preceding_fdp.location` describe the
        same fact: where the following off-duty period is taken. Only the
        latter drove the §8.1/§10.1 branch, so a caller who set the former
        alone got the default silently applied. Rather than change which field
        wins — which would move every existing caller's answer — a
        disagreement is now rejected. Agreement is unambiguous either way.
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

    @field_validator("fdp_start_offset_hours")
    @classmethod
    def _check_fdp_offset(cls, v):
        return validate_utc_offset(v, "fdp_start_offset_hours")

    @field_validator("odp_start_offset_hours")
    @classmethod
    def _check_odp_offset(cls, v):
        return validate_utc_offset(v, "odp_start_offset_hours")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "appendix": "3",
                    "preceding_fdp": {
                        "start_utc": "2026-03-28T22:00:00Z",
                        "end_utc": "2026-03-29T08:30:00Z",
                        "duration_hours": 10.5,
                        "post_fdp_duty_hours": 0.5,
                        "location": "away",
                        "was_extended": False,
                    },
                    "preceding_off_duty": {
                        "duration_hours": 13,
                        "included_local_night": True,
                    },
                    "following_off_duty_location": "away",
                    "following_off_duty_includes_local_night": True,
                }
            ]
        }
    }


# ─── Response models ──────────────────────────────────────────────────

class ReductionApplicable(BaseModel):
    """
    Whether an ODP reduction is available, and on what basis.

    Conditions are split by whether the API can check them. Only
    `conditions_verified` decides `eligible`: a concession is never granted on
    the strength of a fact the API cannot see. `conditions_caller_must_verify`
    lists what the caller must still establish before relying on the reduction.
    """
    eligible: bool = Field(
        description=(
            "True when every condition the API can check is satisfied. This is "
            "not on its own authority to apply the reduction — any entry in "
            "conditions_caller_must_verify must also hold."
        ),
    )
    clause: Optional[str] = Field(default=None, description="Clause reference for the reduction.")
    reduced_min_odp_hours: Optional[float] = Field(
        default=None,
        description="Reduced minimum ODP if eligible (hours). Null when not eligible.",
    )
    conditions_verified: list[ConditionResult] = Field(
        default_factory=list,
        description="Conditions the API checked against supplied data and found satisfied.",
    )
    conditions_failed: list[ConditionResult] = Field(
        default_factory=list,
        description="Conditions the API checked and found not satisfied.",
    )
    conditions_caller_must_verify: list[ConditionResult] = Field(
        default_factory=list,
        description=(
            "Conditions the API cannot check from supplied data. Never counted "
            "toward eligibility."
        ),
    )
    reason: str = Field(
        default="",
        description="Human-readable summary of the eligibility outcome.",
    )
    conditions_met: list[str] = Field(
        default_factory=list,
        description=(
            "DEPRECATED — use conditions_verified. Contains verified conditions "
            "only; a condition the caller must verify never appears here."
        ),
    )


class DisplacementResult(BaseModel):
    """Displacement time contribution to the minimum ODP (Appendices 2, 4, 4B)."""
    applicable: bool = Field(description="Whether this appendix applies displacement time.")
    status: Literal["computed", "data_unavailable", "not_applicable"] = Field(
        description=(
            "'computed' when derived from supplied offsets; 'data_unavailable' "
            "when the offsets were not supplied, in which case the returned "
            "minimum is a lower bound and may be understated."
        ),
    )
    displacement_hours: Optional[float] = Field(
        default=None, description="Magnitude of the time-zone shift (hours).",
    )
    direction: Optional[str] = Field(
        default=None, description="'east', 'west', or 'none'.",
    )
    added_hours: float = Field(
        default=0.0, description="Hours added to the base minimum ODP.",
    )
    detail: str = Field(default="", description="Human-readable explanation.")


class MinOffDutyResponse(BaseModel):
    """Response for POST /calculate/min-off-duty."""

    appendix: str = Field(description="Appendix used for calculation.")
    fdp_plus_post_duty_hours: float = Field(
        description="Total of FDP duration + post-FDP duty hours.",
    )
    exceeds_12h: bool = Field(
        description="Whether the FDP + post-duty total exceeds 12 hours.",
    )
    base_min_odp_hours: float = Field(
        description="Base minimum off-duty period from primary rule.",
    )
    clause: str = Field(description="Primary clause reference for the base calculation.")
    split_duty_credit_hours: float = Field(
        default=0,
        description="Hours credited (reduced) from split duty rest.",
    )
    split_duty_credit_clause: Optional[str] = Field(
        default=None,
        description="Clause reference for split duty credit.",
    )
    effective_duration_for_calc_hours: float = Field(
        description="Net FDP+duty duration used after split duty credit.",
    )
    displacement: Optional[DisplacementResult] = Field(
        default=None,
        description="Displacement time contribution (Appendices 2, 4, 4B only).",
    )
    reduction_applicable: Optional[ReductionApplicable] = Field(
        default=None,
        description="Reduction eligibility details, if a reduction provision applies.",
    )
    final_min_odp_hours: float = Field(
        description=(
            "The minimum off-duty period required. This is the UNREDUCED "
            "minimum: reduction provisions are permissions the caller claims, "
            "not defaults the API applies. Where a reduction is available it "
            "appears in reduction_applicable."
        ),
    )
    calculation_notes: list[str] = Field(
        default_factory=list,
        description="Human-readable calculation breakdown with clause references.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "appendix": "3",
                    "fdp_plus_post_duty_hours": 11.0,
                    "exceeds_12h": False,
                    "base_min_odp_hours": 10.0,
                    "clause": "§8.1a",
                    "split_duty_credit_hours": 2.0,
                    "split_duty_credit_clause": "§3.2",
                    "effective_duration_for_calc_hours": 9.0,
                    "reduction_applicable": {
                        "eligible": True,
                        "clause": "§8.3",
                        "conditions_met": [
                            "Previous ODP >=12h including local night",
                            "ODP over a local night",
                            "ODP away from home base",
                        ],
                        "reduced_min_odp_hours": 9.0,
                    },
                    "final_min_odp_hours": 9.0,
                    "calculation_notes": [
                        "FDP + post-FDP duty = 11.0h (<=12h -> §8.1 applies)",
                        "Away from home base -> base 10h (§8.1a)",
                        "Split duty credit: -2h from effective FDP for ODP calc (§3.2)",
                        "Reduction §8.3 eligible: may reduce to 9h subject to conditions",
                    ],
                }
            ]
        }
    }
