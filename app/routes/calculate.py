"""
Route handlers for the /calculate/* endpoints.

POST /calculate/max-fdp — Maximum FDP calculator
POST /calculate/min-off-duty — Minimum off-duty period calculator
"""

from fastapi import APIRouter

from app.engines.acclimatisation_calculator import determine_acclimatisation
from app.engines.fdp_calculator import calculate_max_fdp
from app.engines.off_duty_calculator import calculate_min_off_duty
from app.models.acclimatisation import (
    AcclimatisationRequest,
    AcclimatisationResponse,
)
from app.models.calculation import (
    Adjustment,
    MaxFdpRequest,
    MaxFdpResponse,
    MinOffDutyRequest,
    MinOffDutyResponse,
    ReductionApplicable,
)

router = APIRouter(tags=["Calculation"])


@router.post(
    "/calculate/max-fdp",
    response_model=MaxFdpResponse,
    summary="Calculate maximum permissible FDP",
    description=(
        "Given operational parameters (appendix, start time, sectors, crew "
        "configuration, split duty), calculates the maximum permissible Flight "
        "Duty Period with a clause-referenced breakdown of all adjustments."
    ),
)
async def calc_max_fdp(request: MaxFdpRequest) -> MaxFdpResponse:
    result = calculate_max_fdp(
        appendix=request.appendix,
        fdp_start_utc=request.fdp_start_utc,
        local_time_offset_hours=request.local_time_offset_hours,
        sectors=request.sectors,
        acclimatisation_state=(
            request.acclimatisation.state
            if request.acclimatisation else "not_applicable"
        ),
        acclimatised_time_offset_hours=(
            request.acclimatisation.acclimatised_time_offset_hours
            if request.acclimatisation else None
        ),
        augmented_crew=(
            request.augmented_crew.model_dump()
            if request.augmented_crew else None
        ),
        split_duty=(
            request.split_duty.model_dump()
            if request.split_duty else None
        ),
        consecutive_early_starts=request.consecutive_early_starts,
        consecutive_wocl_infringements=request.consecutive_wocl_infringements,
        single_pilot=request.single_pilot,
        preceding_off_duty_hours=request.preceding_off_duty_hours,
    )

    return MaxFdpResponse(
        appendix=result["appendix"],
        base_max_fdp_hours=result["base_max_fdp_hours"],
        adjustments=[Adjustment(**adj) for adj in result["adjustments"]],
        wocl_early_start_reduction_hours=result["wocl_early_start_reduction_hours"],
        final_max_fdp_hours=result["final_max_fdp_hours"],
        max_extension_hours=result["max_extension_hours"],
        absolute_max_with_extension_hours=result["absolute_max_with_extension_hours"],
        post_split_max_hours=result["post_split_max_hours"],
        flight_time_limit_hours=result["flight_time_limit_hours"],
        calculation_notes=result["calculation_notes"],
    )


@router.post(
    "/calculate/acclimatisation",
    response_model=AcclimatisationResponse,
    summary="Determine an FCM's state of acclimatisation",
    description=(
        "Determines a flight crew member's state of acclimatisation at a "
        "nominated moment under CAO 48.1 §7, from where they were last "
        "acclimatised and every FDP or off-duty period commenced since.\n\n"
        "Returns the state, the location they are acclimatised **to**, and the "
        "clause that produced the determination. The returned "
        "`acclimatised_to.utc_offset_hours` is the value to pass as "
        "`acclimatisation.acclimatised_time_offset_hours` on "
        "`/calculate/max-fdp` and `/validate/fdp` — under Appendix 2 the FDP "
        "table band, the early-start test and the WOCL determination are all "
        "defined against local time at that location rather than at the "
        "departure point.\n\n"
        "**States:** `acclimatised`, `unknown` (the §7.3 determination, which "
        "has its own FDP tables), and `indeterminate` — meaning the supplied "
        "history was not sufficient to reach any determination. "
        "`indeterminate` is not a conservative substitute for `unknown` and "
        "must not be used for a table lookup.\n\n"
        "Stateless: supply the full history on every call. UTC offsets are "
        "taken as authoritative and no time zone database is consulted, which "
        "keeps daylight saving out of the calculation and honours §6's "
        "provision allowing an AOC holder to nominate an adjoining zone."
    ),
)
async def calc_acclimatisation(
    request: AcclimatisationRequest,
) -> AcclimatisationResponse:
    result = determine_acclimatisation(
        last_acclimatised=request.last_acclimatised.model_dump(),
        as_of_utc=request.as_of_utc,
        events=[event.model_dump() for event in request.events],
        home_base=request.home_base,
    )
    return AcclimatisationResponse(**result)


@router.post(
    "/calculate/min-off-duty",
    response_model=MinOffDutyResponse,
    summary="Calculate minimum required off-duty period",
    description=(
        "Given the preceding FDP details and operational context, calculates "
        "the minimum required off-duty period with clause references and "
        "reduction eligibility assessment."
    ),
)
async def calc_min_off_duty(request: MinOffDutyRequest) -> MinOffDutyResponse:
    result = calculate_min_off_duty(
        appendix=request.appendix,
        preceding_fdp_duration_hours=request.preceding_fdp.duration_hours,
        post_fdp_duty_hours=request.preceding_fdp.post_fdp_duty_hours,
        location=request.preceding_fdp.location,
        split_duty_duration_hours=(
            request.preceding_fdp.split_duty.duration_hours
            if request.preceding_fdp.split_duty else None
        ),
        split_duty_accommodation=(
            request.preceding_fdp.split_duty.accommodation
            if request.preceding_fdp.split_duty else None
        ),
        split_duty_overlaps_night=(
            request.preceding_fdp.split_duty.overlaps_2300_0529
            if request.preceding_fdp.split_duty else False
        ),
        was_extended=request.preceding_fdp.was_extended,
        extension_hours=request.preceding_fdp.extension_hours,
        preceding_odp_duration_hours=(
            request.preceding_off_duty.duration_hours
            if request.preceding_off_duty else None
        ),
        preceding_odp_included_night=(
            request.preceding_off_duty.included_local_night
            if request.preceding_off_duty else False
        ),
        following_includes_local_night=request.following_off_duty_includes_local_night,
        acclimatisation_state=request.acclimatisation_state,
        fdp_commencement_utc_offset_hours=request.preceding_fdp.commencement_utc_offset_hours,
        following_off_duty_utc_offset_hours=request.following_off_duty_utc_offset_hours,
    )

    reduction = None
    if result["reduction_applicable"]:
        reduction = ReductionApplicable(**result["reduction_applicable"])

    return MinOffDutyResponse(
        appendix=result["appendix"],
        fdp_plus_post_duty_hours=result["fdp_plus_post_duty_hours"],
        exceeds_12h=result["exceeds_12h"],
        base_min_odp_hours=result["base_min_odp_hours"],
        clause=result["clause"],
        split_duty_credit_hours=result["split_duty_credit_hours"],
        split_duty_credit_clause=result["split_duty_credit_clause"],
        effective_duration_for_calc_hours=result["effective_duration_for_calc_hours"],
        reduction_applicable=reduction,
        final_min_odp_hours=result["final_min_odp_hours"],
        calculation_notes=result["calculation_notes"],
    )
