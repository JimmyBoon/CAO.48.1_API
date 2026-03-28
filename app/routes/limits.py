"""
Route handlers for the /limits/* endpoints.

GET /limits/fdp-table/{appendix} — FDP lookup table
GET /limits/cumulative/{appendix} — Cumulative limit thresholds
"""

from fastapi import APIRouter, Path
from fastapi.responses import JSONResponse

from app.data.fdp_tables import FDP_CONFIGS, VALID_APPENDICES
from app.data.cumulative_limits import CUMULATIVE_CONFIGS
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
