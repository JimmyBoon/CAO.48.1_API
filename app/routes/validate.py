"""
Route handlers for the /validate/* endpoints.

POST /validate/fdp        — FDP validation
POST /validate/off-duty   — Off-duty period validation
POST /validate/cumulative — Rolling-window cumulative limit checks
POST /validate/sequence   — Ordered FDP/ODP sequence validation
POST /validate/roster     — Full roster validation
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.engines.cumulative_validator import validate_cumulative
from app.engines.fdp_validator import validate_fdp
from app.engines.off_duty_validator import validate_off_duty
from app.engines.sequence_validator import validate_sequence
from app.engines.roster_validator import validate_roster
from app.models.validation import (
    CheckResult,
    ValidationResponse,
    ValidateCumulativeRequest,
    ValidateFdpRequest,
    ValidateOffDutyRequest,
    ValidateSequenceRequest,
    ValidateRosterRequest,
    RosterValidationResponse,
    RosterSummary,
    FdpValidationItem,
    OdpValidationItem,
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
            fdp_commencement_utc_offset_hours=request.preceding_fdp.commencement_utc_offset_hours,
            following_off_duty_utc_offset_hours=request.following_off_duty_utc_offset_hours,
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
    "/validate/cumulative",
    response_model=ValidationResponse,
    summary="Validate cumulative flight time and recovery limits",
    description=(
        "Validates rolling-window cumulative limits (flight time, duty time, "
        "recovery blocks, minimum days off) for the specified appendix.\n\n"
        "Accepts either a full FDP history log (preferred — the API computes "
        "all windows) or pre-aggregated summary totals (accepted when a full "
        "log is unavailable).\n\n"
        "For Appendices 5 and 5A, a 5+ consecutive-day gap in the FDP log is "
        "automatically detected and used to reset the flight time accumulation "
        "counter."
    ),
    responses={
        200: {
            "description": (
                "Validation completed. Inspect `valid` for pass/fail outcome."
            ),
        },
        422: {"description": "Invalid request body."},
    },
)
async def validate_cumulative_endpoint(
    request: ValidateCumulativeRequest,
) -> ValidationResponse:
    try:
        result = validate_cumulative(
            appendix=request.appendix,
            as_of_utc=request.as_of_utc,
            fdp_log=request.fdp_log,
            summary=request.summary,
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
    "/validate/sequence",
    response_model=ValidationResponse,
    summary="Validate an ordered sequence of FDPs and off-duty periods",
    description=(
        "Validates a chronologically ordered sequence of FDP and off-duty "
        "events as a complete roster window.\n\n"
        "Checks performed:\n"
        "- Each individual FDP (duration, flight time limits)\n"
        "- Each off-duty period between FDPs (minimum ODP requirements)\n"
        "- Consecutive WOCL infringement rule (§13.2): after 3 consecutive "
        "WOCL infringements, the next WOCL-infringing FDP must be preceded "
        "by an off-duty period that includes a local night\n"
        "- Rolling cumulative limits (flight time, duty time, recovery) "
        "evaluated over the full sequence\n\n"
        "Each check result is prefixed with its event context "
        "(e.g. `fdp1_fdp_within_limit`, `odp1_minimum_odp`, "
        "`cumulative_flight_time_28d`)."
    ),
    responses={
        200: {
            "description": (
                "Validation completed. Inspect `valid` for pass/fail outcome."
            ),
        },
        422: {"description": "Invalid request body."},
    },
)
async def validate_sequence_endpoint(
    request: ValidateSequenceRequest,
) -> ValidationResponse:
    try:
        result = validate_sequence(
            appendix=request.appendix,
            events=request.events,
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
    "/validate/roster",
    response_model=RosterValidationResponse,
    summary="Validate a full crew roster",
    description=(
        "Validates a complete ordered roster of FDP, off-duty, and rest-day events "
        "against all applicable CAO 48.1 rules for the specified appendix.\n\n"
        "Checks performed:\n"
        "- Each individual FDP (duration, flight time, extension validity)\n"
        "- Each off-duty period between FDPs (minimum ODP requirements)\n"
        "- Sequence-level checks: consecutive WOCL infringement rule (\u00a713.2) and "
        "consecutive early-start reductions\n"
        "- Rolling cumulative limits (flight time, duty time, recovery blocks, days off) "
        "evaluated across roster FDPs combined with any supplied prior history\n\n"
        "Returns a structured per-event breakdown (fdp_results, odp_results), "
        "sequence-level checks, cumulative result, and a flat all_violations list "
        "for quick scanning."
    ),
    responses={
        200: {
            "description": (
                "Validation completed. Inspect `valid` for pass/fail outcome."
            ),
        },
        422: {"description": "Invalid request body."},
    },
)
async def validate_roster_endpoint(
    request: ValidateRosterRequest,
) -> RosterValidationResponse:
    try:
        result = validate_roster(
            appendix=request.appendix,
            roster_start_utc=request.roster_start_utc,
            roster_end_utc=request.roster_end_utc,
            events=request.events,
            prior_fdp_log=request.prior_fdp_log,
            prior_summary=request.prior_summary,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={"error": "validation_error", "message": str(exc)},
        )

    return RosterValidationResponse(
        valid=result["valid"],
        appendix=result["appendix"],
        roster_start_utc=result["roster_start_utc"],
        roster_end_utc=result["roster_end_utc"],
        summary=RosterSummary(**result["summary"]),
        fdp_results=[
            FdpValidationItem(
                fdp_number=r["fdp_number"],
                fdp_start_utc=r["fdp_start_utc"],
                fdp_end_utc=r["fdp_end_utc"],
                duration_hours=r["duration_hours"],
                valid=r["valid"],
                violations=[Violation(**v) for v in r["violations"]],
                checks=[CheckResult(**c) for c in r["checks"]],
                warnings=r["warnings"],
                calculation_notes=r["calculation_notes"],
            )
            for r in result["fdp_results"]
        ],
        odp_results=[
            OdpValidationItem(
                odp_number=r["odp_number"],
                start_utc=r["start_utc"],
                end_utc=r["end_utc"],
                duration_hours=r["duration_hours"],
                valid=r["valid"],
                violations=[Violation(**v) for v in r["violations"]],
                checks=[CheckResult(**c) for c in r["checks"]],
                warnings=r["warnings"],
                calculation_notes=r.get("calculation_notes", []),
            )
            for r in result["odp_results"]
        ],
        sequence_checks=[CheckResult(**c) for c in result["sequence_checks"]],
        sequence_violations=[Violation(**v) for v in result["sequence_violations"]],
        cumulative_result=result["cumulative_result"],
        all_violations=[Violation(**v) for v in result["all_violations"]],
        warnings=result["warnings"],
    )
