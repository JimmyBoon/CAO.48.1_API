"""
Cumulative limit thresholds for all CAO 48.1 appendices.

Covers flight time limits, duty time limits, and recovery period requirements.
Data hardcoded from CAO 48.1 Instrument 2019 (Compilation No. 3, F2021C01239).
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class FlightTimeLimits:
    """Maximum flight time over rolling windows."""
    period_28d_hours: Optional[float] = None
    period_365d_hours: Optional[float] = None
    period_168h_hours: Optional[float] = None    # Appendix 5
    period_90d_hours: Optional[float] = None     # Appendix 5
    period_384h_hours: Optional[float] = None    # Appendix 5A
    reset_after_days_off: Optional[int] = None   # days off to reset counter


@dataclass(frozen=True)
class DutyTimeLimits:
    """Maximum duty time over rolling windows."""
    period_168h_hours: Optional[float] = None
    period_336h_hours: Optional[float] = None


@dataclass(frozen=True)
class RecoveryRequirements:
    """Minimum recovery periods required before next FDP."""
    period_168h_min_hours: float = 36.0
    period_168h_local_nights: int = 2
    period_28d_days_off: Optional[int] = None
    # Alternative recovery windows (Appendices 4B, 5)
    period_336h_min_hours: Optional[float] = None
    period_336h_local_nights: Optional[int] = None
    period_504h_min_hours: Optional[float] = None
    period_504h_local_nights: Optional[int] = None
    period_384h_days_off: Optional[int] = None   # Appendix 5A


@dataclass(frozen=True)
class CumulativeLimitsConfig:
    """Complete cumulative limits configuration for one appendix."""
    appendix: str
    flight_time: FlightTimeLimits
    duty_time: DutyTimeLimits
    recovery: RecoveryRequirements


# ═══════════════════════════════════════════════════════════════════════
# Per-appendix configurations
# ═══════════════════════════════════════════════════════════════════════

CUMULATIVE_CONFIGS: dict[str, CumulativeLimitsConfig] = {
    "1": CumulativeLimitsConfig(
        appendix="1",
        flight_time=FlightTimeLimits(period_28d_hours=100, period_365d_hours=1000),
        duty_time=DutyTimeLimits(),  # not specified
        recovery=RecoveryRequirements(
            period_168h_min_hours=36, period_168h_local_nights=2,
            period_28d_days_off=6,
        ),
    ),
    "2": CumulativeLimitsConfig(
        appendix="2",
        flight_time=FlightTimeLimits(period_28d_hours=100, period_365d_hours=1000),
        duty_time=DutyTimeLimits(period_168h_hours=60, period_336h_hours=100),
        recovery=RecoveryRequirements(
            period_168h_min_hours=36, period_168h_local_nights=2,
            period_28d_days_off=6,
        ),
    ),
    "3": CumulativeLimitsConfig(
        appendix="3",
        flight_time=FlightTimeLimits(period_28d_hours=100, period_365d_hours=1000),
        duty_time=DutyTimeLimits(period_168h_hours=60, period_336h_hours=100),
        recovery=RecoveryRequirements(
            period_168h_min_hours=36, period_168h_local_nights=2,
            period_28d_days_off=6,
        ),
    ),
    "4": CumulativeLimitsConfig(
        appendix="4",
        flight_time=FlightTimeLimits(period_28d_hours=100, period_365d_hours=1000),
        duty_time=DutyTimeLimits(period_168h_hours=60, period_336h_hours=100),
        recovery=RecoveryRequirements(
            period_168h_min_hours=36, period_168h_local_nights=2,
            period_28d_days_off=6,
        ),
    ),
    "4A": CumulativeLimitsConfig(
        appendix="4A",
        flight_time=FlightTimeLimits(period_28d_hours=50),
        duty_time=DutyTimeLimits(period_168h_hours=45, period_336h_hours=84),
        recovery=RecoveryRequirements(
            period_168h_min_hours=0, period_168h_local_nights=0,
            period_28d_days_off=None,
            period_384h_days_off=2,  # 2 full days off in 14 consecutive days
        ),
    ),
    "4B": CumulativeLimitsConfig(
        appendix="4B",
        flight_time=FlightTimeLimits(period_28d_hours=100, period_365d_hours=1000),
        duty_time=DutyTimeLimits(period_168h_hours=60, period_336h_hours=100),
        recovery=RecoveryRequirements(
            period_168h_min_hours=36, period_168h_local_nights=2,
            period_336h_min_hours=36, period_336h_local_nights=2,
            period_504h_min_hours=72, period_504h_local_nights=3,
        ),
    ),
    "5": CumulativeLimitsConfig(
        appendix="5",
        flight_time=FlightTimeLimits(
            period_168h_hours=50,
            period_28d_hours=170,
            period_90d_hours=450,
            period_365d_hours=1200,
            reset_after_days_off=5,
        ),
        duty_time=DutyTimeLimits(),  # not specified
        recovery=RecoveryRequirements(
            period_336h_min_hours=36, period_336h_local_nights=2,
            period_504h_min_hours=72, period_504h_local_nights=3,
        ),
    ),
    "5A": CumulativeLimitsConfig(
        appendix="5A",
        flight_time=FlightTimeLimits(
            period_384h_hours=100,
            period_365d_hours=1200,
            reset_after_days_off=5,
        ),
        duty_time=DutyTimeLimits(),  # not specified
        recovery=RecoveryRequirements(
            period_384h_days_off=2,
        ),
    ),
    "6": CumulativeLimitsConfig(
        appendix="6",
        flight_time=FlightTimeLimits(period_28d_hours=100, period_365d_hours=1000),
        duty_time=DutyTimeLimits(period_168h_hours=60, period_336h_hours=100),
        recovery=RecoveryRequirements(
            period_168h_min_hours=36, period_168h_local_nights=2,
            period_28d_days_off=6,
        ),
    ),
}


def get_cumulative_config(appendix: str) -> CumulativeLimitsConfig | None:
    """Return cumulative limits for a given appendix, or None if invalid."""
    return CUMULATIVE_CONFIGS.get(appendix.upper())
