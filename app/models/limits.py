"""
Pydantic response models for the /limits/* endpoints.

GET /limits/fdp-table/{appendix} — FDP lookup table
GET /limits/cumulative/{appendix} — Cumulative limit thresholds
"""

from typing import Optional

from pydantic import BaseModel, Field


# ─── FDP Table Response ───────────────────────────────────────────────

class TimeBandRow(BaseModel):
    """One row of the FDP table: a time band with limits per sector grouping."""

    time_band: str = Field(
        description="Time band label, e.g. '0700-1259' or '<30h off-duty'.",
    )
    sectors: dict[str, float] = Field(
        description=(
            "Maximum FDP hours keyed by sector grouping. "
            "Keys vary by appendix: '1-3', '4', '5', '6', '7', '8+' for "
            "multi-pilot; 'single_pilot', 'multi_1_2', 'multi_3+' for "
            "aerial work; 'all' for single-value tables."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "time_band": "0700-1259",
                    "sectors": {"1-3": 13, "4": 12.5, "5": 12, "6": 11.5, "7": 11, "8+": 10.5},
                }
            ]
        }
    }


class FdpTableResponse(BaseModel):
    """FDP lookup table for a given appendix."""

    appendix: str = Field(description="Appendix identifier.")
    table_id: str = Field(description="Table reference within the legislation, e.g. 'Table 2.1'.")
    lookup_key: str = Field(
        description="What the rows represent: 'local_time_and_sectors', 'acclimatised_time_and_sectors', etc.",
    )
    flight_time_limit_hours: Optional[float] = Field(
        default=None,
        description="Maximum flight time per FDP (hours), or null if no per-FDP limit.",
    )
    rows: list[TimeBandRow] = Field(description="Table rows, one per time band.")
    split_duty_cap_hours: Optional[float] = Field(
        default=None,
        description="Absolute FDP cap when split duty rest is taken (hours).",
    )
    post_split_max_hours: Optional[float] = Field(
        default=None,
        description="Maximum FDP permitted after split duty rest ends (hours).",
    )
    notes: str = Field(default="", description="Human-readable notes about this table.")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "appendix": "3",
                    "table_id": "Table 2.1",
                    "lookup_key": "local_time_and_sectors",
                    "flight_time_limit_hours": 10.5,
                    "rows": [
                        {"time_band": "0000-0459", "sectors": {"1-3": 10, "4": 9.5, "5": 9, "6": 8.5, "7": 8, "8+": 7.5}},
                    ],
                    "split_duty_cap_hours": 16,
                    "post_split_max_hours": 6,
                    "notes": "Uses local time (not acclimatised time). No augmented crew provisions.",
                }
            ]
        }
    }


# ─── Cumulative Limits Response ───────────────────────────────────────

class FlightTimeLimitsResponse(BaseModel):
    """Flight time limits over rolling windows."""
    period_28d_hours: Optional[float] = Field(default=None, description="Max flight time in 28 consecutive days.")
    period_365d_hours: Optional[float] = Field(default=None, description="Max flight time in 365 consecutive days.")
    period_168h_hours: Optional[float] = Field(default=None, description="Max flight time in 168-hour period.")
    period_90d_hours: Optional[float] = Field(default=None, description="Max flight time in 90 consecutive days.")
    period_384h_hours: Optional[float] = Field(default=None, description="Max flight time in 384-hour period.")
    reset_after_days_off: Optional[int] = Field(default=None, description="Consecutive days off to reset counter.")


class DutyTimeLimitsResponse(BaseModel):
    """Duty time limits over rolling windows."""
    period_168h_hours: Optional[float] = Field(default=None, description="Max duty time in 168-hour period.")
    period_336h_hours: Optional[float] = Field(default=None, description="Max duty time in 336-hour period.")


class RecoveryRequirementsResponse(BaseModel):
    """Recovery period requirements."""
    period_168h_block: Optional[dict] = Field(
        default=None,
        description="Min consecutive hours off with local nights required per 168-hour block.",
    )
    period_28d_days_off: Optional[int] = Field(
        default=None,
        description="Min days off in 28 consecutive days.",
    )
    period_336h_block: Optional[dict] = Field(default=None, description="Alternative 336h recovery block.")
    period_504h_block: Optional[dict] = Field(default=None, description="Alternative 504h recovery block.")
    period_384h_days_off: Optional[int] = Field(default=None, description="Min days off in 384h (Appendix 4A/5A).")


class CumulativeLimitsResponse(BaseModel):
    """Cumulative limit thresholds for a given appendix."""

    appendix: str = Field(description="Appendix identifier.")
    flight_time: FlightTimeLimitsResponse = Field(description="Flight time limits.")
    duty_time: DutyTimeLimitsResponse = Field(description="Duty time limits.")
    recovery: RecoveryRequirementsResponse = Field(description="Recovery period requirements.")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "appendix": "3",
                    "flight_time": {"period_28d_hours": 100, "period_365d_hours": 1000},
                    "duty_time": {"period_168h_hours": 60, "period_336h_hours": 100},
                    "recovery": {
                        "period_168h_block": {"min_hours": 36, "local_nights": 2},
                        "period_28d_days_off": 6,
                    },
                }
            ]
        }
    }
