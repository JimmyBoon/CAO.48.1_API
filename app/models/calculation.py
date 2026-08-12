"""
Pydantic request and response models for the /calculate/* endpoints.

POST /calculate/max-fdp — Maximum FDP calculator
POST /calculate/min-off-duty — Minimum off-duty period calculator
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.models.base import StrictModel


# ─── Common enumerations ──────────────────────────────────────────────

AppendixId = Literal["1", "2", "3", "4", "4A", "4B", "5", "5A", "6"]
AcclimState = Literal["acclimatised", "unknown", "not_applicable"]
Accommodation = Literal["sleeping", "resting", "none"]
Location = Literal["home_base", "away"]
CrewRestClass = Literal["class_1", "class_2", "class_3"]


# ─── Shared cross-field validation ────────────────────────────────────

def require_acclimatisation_for_augmented_crew(
    appendix: str,
    augmented_crew: object | None,
    acclimatisation: object | None,
) -> None:
    """
    Enforce that Appendix 2 augmented-crew requests carry a usable state.

    Shared by MaxFdpRequest and ValidateFdpRequest so the two endpoints
    cannot drift apart. Raises ValueError, which Pydantic converts into a
    422 naming the field.
    """
    if appendix != "2" or augmented_crew is None:
        return

    state = getattr(acclimatisation, "state", None)
    if state not in ("acclimatised", "unknown"):
        raise ValueError(
            "acclimatisation.state is required when augmented_crew is supplied "
            "under Appendix 2, and must be 'acclimatised' or 'unknown'. "
            "The augmented FDP limits (Tables 5.1 and 5.2) are selected by "
            "acclimatisation state; there is no acclimatisation-independent "
            "augmented table. Received: "
            f"{state!r}."
        )


# ═══════════════════════════════════════════════════════════════════════
# POST /calculate/max-fdp
# ═══════════════════════════════════════════════════════════════════════

# ─── Request models ───────────────────────────────────────────────────

class AcclimatisationInput(StrictModel):
    """Acclimatisation state and offset for Appendix 2."""
    state: AcclimState = Field(description="Acclimatisation state of the FCM.")
    acclimatised_time_offset_hours: Optional[float] = Field(
        default=None,
        description=(
            "UTC offset (hours) of the location the FCM is acclimatised to — or, "
            "where state='unknown', the location they were LAST acclimatised to. "
            "Under Appendix 2 this clock governs the FDP table band, the "
            "early-start test and the WOCL determination (CAO 48.1 §6, "
            "'acclimatised time'). Supply it whenever the FCM signs on somewhere "
            "other than the location they are acclimatised to — the everyday case "
            "of a Perth-acclimatised crew member signing on in Singapore. "
            "If omitted, the departure point's local_time_offset_hours is used, "
            "which is correct only when the two locations share a clock. "
            "Ignored for every appendix other than 2, where the instrument "
            "specifies the local time at the point the FDP commences."
        ),
    )


class InFlightRestEntry(StrictModel):
    """In-flight rest record for one FCM in an augmented crew."""
    fcm_id: str = Field(description="Identifier for the flight crew member.")
    rest_hours: float = Field(description="Hours of in-flight rest taken.")
    at_controls_final_landing: bool = Field(
        description="Whether this FCM will be at the controls for the final landing.",
    )


class AugmentedCrewInput(StrictModel):
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
        description="In-flight rest details per additional FCM.",
    )


class SplitDutyInput(StrictModel):
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


class MaxFdpRequest(StrictModel):
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

    @model_validator(mode="after")
    def require_acclimatisation_for_augmented(self) -> "MaxFdpRequest":
        """
        Appendix 2 augmented-crew limits are keyed to acclimatisation state.

        Tables 5.1 and 5.2 are selected by acclimatisation, and there is no
        acclimatisation-independent augmented table to fall back on. Without
        this check the engine used to reach a table that has no augmented
        sector columns and raise a KeyError, surfacing as a 500.
        """
        require_acclimatisation_for_augmented_crew(
            self.appendix, self.augmented_crew, self.acclimatisation,
        )
        return self

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

class PrecedingSplitDutyInput(StrictModel):
    """Split duty rest taken during the preceding FDP."""
    duration_hours: float = Field(gt=0, description="Duration of the split duty rest (hours).")
    accommodation: Accommodation = Field(description="Accommodation type during rest.")
    overlaps_2300_0529: bool = Field(
        default=False,
        description="Whether rest overlapped the 2300-0529 local time window.",
    )


class PrecedingFdpInput(StrictModel):
    """Details of the FDP preceding the off-duty period."""
    start_utc: str = Field(description="FDP start time (ISO 8601 UTC).")
    end_utc: str = Field(description="FDP end time (ISO 8601 UTC).")
    duration_hours: float = Field(gt=0, description="FDP duration in hours.")
    post_fdp_duty_hours: float = Field(
        default=0, ge=0,
        description="Additional duty time after FDP end (e.g. post-flight duties).",
    )
    location: Location = Field(description="Where the off-duty period will be taken.")
    commencement_utc_offset_hours: Optional[float] = Field(
        default=None,
        description=(
            "UTC offset (hours) of local time at the place the FDP COMMENCED. "
            "Supply together with following_off_duty_utc_offset_hours and the API "
            "derives displacement time per §6 — the difference in local time "
            "between where the FDP commenced and where the following off-duty "
            "period is taken — including the direction of travel. Displacement is "
            "an addend in §10.1, §10.2, §8.1, §8.2 and Appendix 4B §5.1, so "
            "without these two offsets the returned figure is a floor rather "
            "than a total, and the response says so."
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


class PrecedingOffDutyInput(StrictModel):
    """Details of the off-duty period preceding the FDP."""
    duration_hours: float = Field(gt=0, description="Duration of the preceding off-duty period (hours).")
    included_local_night: bool = Field(description="Whether the preceding ODP included a local night.")


class MinOffDutyRequest(StrictModel):
    """Request body for POST /calculate/min-off-duty."""

    appendix: AppendixId = Field(description="Which appendix rules apply.")
    preceding_fdp: PrecedingFdpInput = Field(description="Details of the preceding FDP.")
    preceding_off_duty: Optional[PrecedingOffDutyInput] = Field(
        default=None,
        description="Details of the off-duty period before the preceding FDP. Required for reduction eligibility checks.",
    )
    following_off_duty_location: Location = Field(
        default="away",
        description="Where the following off-duty period will be taken.",
    )
    following_off_duty_includes_local_night: bool = Field(
        default=True,
        description="Whether the following off-duty period will include a local night.",
    )
    following_off_duty_utc_offset_hours: Optional[float] = Field(
        default=None,
        description=(
            "UTC offset (hours) of local time at the place the following off-duty "
            "period is TAKEN. Pairs with preceding_fdp.commencement_utc_offset_hours "
            "to derive displacement time (§6)."
        ),
    )
    acclimatisation_state: AcclimState = Field(
        default="not_applicable",
        description=(
            "Acclimatisation state of the FCM. **Materially changes the answer "
            "under Appendix 2**, where §10.1(c) and §10.2(b) are separate "
            "branches for an unknown state: the base is 14 hours rather than 10 "
            "or 12, the home base / away distinction does not apply, and the FULL "
            "displacement time is added rather than only the excess over 3 hours "
            "west / 2 hours east. An unknown-state FCM is also ineligible for the "
            "§10.3 and §10.4 reductions, which require an acclimatised state. "
            "Appendices 3 and 4 have no unknown-state branch, so the value does "
            "not affect their result. Use POST /calculate/acclimatisation to "
            "determine the state rather than declaring it by hand."
        ),
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
                        "post_fdp_duty_hours": 0.5,
                        "location": "away",
                        "commencement_utc_offset_hours": 8.0,
                        "was_extended": False,
                    },
                    "preceding_off_duty": {
                        "duration_hours": 13,
                        "included_local_night": True,
                    },
                    "following_off_duty_location": "away",
                    "following_off_duty_utc_offset_hours": 8.0,
                    "following_off_duty_includes_local_night": True,
                }
            ]
        }
    }


# ─── Response models ──────────────────────────────────────────────────

class ReductionApplicable(BaseModel):
    """Whether an ODP reduction is eligible and its details."""
    eligible: bool = Field(description="Whether conditions for reduction are met.")
    clause: Optional[str] = Field(default=None, description="Clause reference for the reduction.")
    conditions_met: list[str] = Field(
        default_factory=list,
        description="Conditions that were evaluated for reduction eligibility.",
    )
    reduced_min_odp_hours: Optional[float] = Field(
        default=None,
        description="Reduced minimum ODP if eligible (hours).",
    )


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
    reduction_applicable: Optional[ReductionApplicable] = Field(
        default=None,
        description="Reduction eligibility details, if checked.",
    )
    final_min_odp_hours: float = Field(
        description="Final minimum off-duty period after all adjustments.",
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
