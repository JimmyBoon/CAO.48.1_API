"""
Route handlers for the /validate/* endpoints.

POST /validate/fdp       — FDP validation
POST /validate/off-duty  — Off-duty period validation
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.engines.fdp_validator import validate_fdp
from app.engines.off_duty_validator import validate_off_duty
from app.models.validation import (
    CheckResult,
    ValidationResponse,
    ValidateFdpRequest,
    ValidateOffDutyRequest,
    Violation,
)

router = APIRouter(tags=["Validation"])


@router.post(
    "/validate/fdp",
    response_model=ValidationResponse,
    summary="Validate a single FDP",
    description=(
        "Validates a single Flight Duty Period against all applicable rules "
        "for the specified appendix. Returns every check run (passed and "
        "failed) plus a top-level `valid` flag. Each violation includes a "
        "CAO 48.1 clause reference and a remediation suggestion.\n\n"
        "Optionally validates extension type and hours if an extension is "
        "supplied, and checks the per-FDP flight time limit when "
        "`actual_flight_time_hours` is provided."
    ),
    responses={
        200: {
            "description": (
                "Validation completed successfully. "
                "Inspect the `valid` field for the pass/fail outcome."
            ),
        },
        422: {"description": "Invalid request body."},
    },
)
async def validate_fdp_endpoint(request: ValidateFdpRequest) -> ValidationResponse:
    try:
        result = validate_fdp(
            appendix=request.appendix,
            fdp_start_utc=request.fdp_start_utc,
            fdp_end_utc=request.fdp_end_utc,
            local_time_offset_hours=request.local_time_offset_hours,
            sectors=request.sectors,
            actual_flight_time_hours=request.actual_flight_time_hours,
            extension=(
                request.extension.model_dump()
                if request.extension else None
            ),
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
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={"error": "validation_error", "message": str(exc)},
        )

    return ValidationResponse(
        valid=result["valid"],
        appendix=result["appendix"],
        violations=[Violation(**v) for v in result["violations"]],
        checks=[CheckResult(**c) for c in result["checks"]],
        warnings=result["warnings"],
        calculation_notes=result["calculation_notes"],
    )


@router.post(
    "/validate/off-duty",
    response_model=ValidationResponse,
    summary="Validate an off-duty period",
    description=(
        "Validates an off-duty period between two FDPs against the minimum "
        "required ODP for the specified appendix. Optionally verifies that "
        "reduction eligibility conditions are satisfied if `reduction_claimed` "
        "is True. Returns all checks run with clause references and, where "
        "relevant, remediation guidance."
    ),
    responses={
        200: {
            "description": (
                "Validation completed successfully. "
                "Inspect the `valid` field for the pass/fail outcome."
            ),
        },
        422: {"description": "Invalid request body."},
    },
)
async def validate_off_duty_endpoint(
    request: ValidateOffDutyRequest,
) -> ValidationResponse:
    try:
        result = validate_off_duty(
            appendix=request.appendix,
            preceding_fdp_duration_hours=request.preceding_fdp.duration_hours,
            actual_off_duty_hours=request.actual_off_duty_hours,
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
            reduction_claimed=request.reduction_claimed,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={"error": "validation_error", "message": str(exc)},
        )

    return ValidationResponse(
        valid=result["valid"],
        appendix=result["appendix"],
        violations=[Violation(**v) for v in result["violations"]],
        checks=[CheckResult(**c) for c in result["checks"]],
        warnings=result["warnings"],
        calculation_notes=result["calculation_notes"],
    )
