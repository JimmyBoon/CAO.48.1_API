"""
Route handlers for the /limits/* endpoints.

GET /limits/fdp-table/{appendix} — FDP lookup table
GET /limits/cumulative/{appendix} — Cumulative limit thresholds
"""

from fastapi import APIRouter, Path
from fastapi.responses import JSONResponse

from app.data.adaptation import adaptation_table_rows
from app.data.fdp_tables import FDP_CONFIGS, VALID_APPENDICES
from app.data.cumulative_limits import CUMULATIVE_CONFIGS
from app.models.acclimatisation import (
    AdaptationTableResponse,
    AdaptationTableRow,
)
from app.models.limits import (
    CumulativeLimitsResponse,
    DutyTimeLimitsResponse,
    FdpTableResponse,
    FlightTimeLimitsResponse,
    RecoveryRequirementsResponse,
    TimeBandRow,
)

router = APIRouter(tags=["Limits"])


def _validate_appendix(appendix: str) -> str | None:
    """Normalise and validate an appendix ID. Returns normalised ID or None."""
    normalised = appendix.upper()
    if normalised in VALID_APPENDICES:
        return normalised
    return None


@router.get(
    "/limits/fdp-table/{appendix}",
    response_model=FdpTableResponse,
    summary="FDP lookup table for an appendix",
    description=(
        "Returns the Flight Duty Period lookup table for a given appendix, "
        "including time bands, sector-based limits, split duty caps, and "
        "flight time limits. Appendix 2 returns the primary acclimatised table; "
        "use the /calculate/max-fdp endpoint for augmented crew or unknown "
        "acclimatisation sub-tables."
    ),
    responses={
        404: {
            "description": "Appendix not found.",
            "content": {
                "application/json": {
                    "example": {
                        "error": "not_found",
                        "message": "Appendix '99' is not a valid appendix identifier.",
                        "valid_appendices": ["1", "2", "3", "4", "4A", "4B", "5", "5A", "6"],
                    }
                }
            },
        },
    },
)
async def get_fdp_table(
    appendix: str = Path(
        description="Appendix identifier: 1, 2, 3, 4, 4A, 4B, 5, 5A, or 6.",
        examples=["3", "4B"],
    ),
) -> FdpTableResponse | JSONResponse:
    normalised = _validate_appendix(appendix)
    if normalised is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": "not_found",
                "message": f"Appendix '{appendix}' is not a valid appendix identifier.",
                "valid_appendices": sorted(VALID_APPENDICES),
            },
        )

    config = FDP_CONFIGS[normalised]
    # Return the primary/default table
    table_key = "acclimatised" if normalised == "2" else "default"
    table = config.tables[table_key]

    rows = [
        TimeBandRow(
            time_band=row.time_band.label,
            sectors={k: float(v) for k, v in row.sectors.items()},
        )
        for row in table.rows
    ]

    split_cap = config.split_duty.sleeping_cap_hours if config.split_duty.available else None
    post_split = (
        config.split_duty.post_split_max_hours
        if config.split_duty.available and config.split_duty.post_split_max_hours < 99
        else None
    )

    return FdpTableResponse(
        appendix=normalised,
        table_id=table.table_id,
        lookup_key=table.lookup_key,
        flight_time_limit_hours=table.flight_time_limit_hours,
        rows=rows,
        split_duty_cap_hours=split_cap,
        post_split_max_hours=post_split,
        notes=table.notes,
    )


@router.get(
    "/limits/adaptation-table",
    response_model=AdaptationTableResponse,
    summary="Table 7.1 — adaptation period to become acclimatised",
    description=(
        "Returns CAO 48.1 Table 7.1 as data: the continuous off-duty period "
        "required for a flight crew member to become acclimatised to a new "
        "location, by time zone change and direction of travel.\n\n"
        "Static reference data — safe to cache or prerender. To apply the table "
        "to a specific crew member's history, including the §7.5 "
        "greatest-displacement selection and the §7.4(b) reduction, use "
        "`POST /calculate/acclimatisation` instead of implementing the lookup "
        "yourself."
    ),
)
async def get_adaptation_table() -> AdaptationTableResponse:
    return AdaptationTableResponse(
        table_id="Table 7.1",
        title="Adaptation period to become acclimatised",
        clause="§7.4, applied per §7.5",
        rows=[AdaptationTableRow(**row) for row in adaptation_table_rows()],
        notes=[
            "An adaptation period is a continuous off-duty period (§6).",
            "Eastward travel requires a longer adaptation period than westward.",
            "Select the row using the GREATEST time zone displacement between "
            "the original location and any later location where an FDP or "
            "off-duty period commenced — not the current location's (§7.5(b)).",
            "Use the direction in which that greatest displacement occurred "
            "(§7.5(d)).",
            "An adaptation period taken away from home base is reduced by 12 "
            "hours for each immediately preceding off-duty period that was "
            "within 2 hours of the adaptation location and included an off-duty "
            "location local night (§7.4(b)).",
            "§6 defines a time zone as a region differing by 1 hour or part of "
            "1 hour, while this table is indexed in whole zones. This API reads "
            "that as: the §7.1 'less than 2 hours' test uses the raw hour "
            "difference, and row selection here rounds up to the next whole "
            "zone. Refer to CAAP 48-01 for guidance.",
            "An adaptation period may commence before the FCM comes to be in an "
            "unknown state of acclimatisation (Table 7.1, Note 2).",
        ],
    )


@router.get(
    "/limits/cumulative/{appendix}",
    response_model=CumulativeLimitsResponse,
    summary="Cumulative limit thresholds for an appendix",
    description=(
        "Returns the cumulative flight time, duty time, and recovery period "
        "thresholds for a given appendix. These are the rolling-window limits "
        "that operators must track."
    ),
    responses={
        404: {
            "description": "Appendix not found.",
            "content": {
                "application/json": {
                    "example": {
                        "error": "not_found",
                        "message": "Appendix '99' is not a valid appendix identifier.",
                        "valid_appendices": ["1", "2", "3", "4", "4A", "4B", "5", "5A", "6"],
                    }
                }
            },
        },
    },
)
async def get_cumulative_limits(
    appendix: str = Path(
        description="Appendix identifier: 1, 2, 3, 4, 4A, 4B, 5, 5A, or 6.",
        examples=["3", "5"],
    ),
) -> CumulativeLimitsResponse | JSONResponse:
    normalised = _validate_appendix(appendix)
    if normalised is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": "not_found",
                "message": f"Appendix '{appendix}' is not a valid appendix identifier.",
                "valid_appendices": sorted(VALID_APPENDICES),
            },
        )

    config = CUMULATIVE_CONFIGS[normalised]

    # Build recovery block
    recovery_168h = None
    if config.recovery.period_168h_min_hours > 0:
        recovery_168h = {
            "min_hours": config.recovery.period_168h_min_hours,
            "local_nights": config.recovery.period_168h_local_nights,
        }

    recovery_336h = None
    if config.recovery.period_336h_min_hours is not None:
        recovery_336h = {
            "min_hours": config.recovery.period_336h_min_hours,
            "local_nights": config.recovery.period_336h_local_nights,
        }

    recovery_504h = None
    if config.recovery.period_504h_min_hours is not None:
        recovery_504h = {
            "min_hours": config.recovery.period_504h_min_hours,
            "local_nights": config.recovery.period_504h_local_nights,
        }

    return CumulativeLimitsResponse(
        appendix=normalised,
        flight_time=FlightTimeLimitsResponse(
            period_28d_hours=config.flight_time.period_28d_hours,
            period_365d_hours=config.flight_time.period_365d_hours,
            period_168h_hours=config.flight_time.period_168h_hours,
            period_90d_hours=config.flight_time.period_90d_hours,
            period_384h_hours=config.flight_time.period_384h_hours,
            reset_after_days_off=config.flight_time.reset_after_days_off,
        ),
        duty_time=DutyTimeLimitsResponse(
            period_168h_hours=config.duty_time.period_168h_hours,
            period_336h_hours=config.duty_time.period_336h_hours,
        ),
        recovery=RecoveryRequirementsResponse(
            period_168h_block=recovery_168h,
            period_28d_days_off=config.recovery.period_28d_days_off,
            period_336h_block=recovery_336h,
            period_504h_block=recovery_504h,
            period_384h_days_off=config.recovery.period_384h_days_off,
        ),
    )
