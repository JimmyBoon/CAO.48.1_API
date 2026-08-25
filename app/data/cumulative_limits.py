"""
Cumulative limit thresholds for all CAO 48.1 appendices.

Covers flight time limits, duty time limits, and recovery period requirements.

**Every limit carries its own clause reference.** Before this, citations were
literals at the emission site in cumulative_validator.py, half of them
hardcoded to Appendix 2's numbering and emitted unchanged for every appendix —
which is why Appendix 3 recovery came out as "§10.5a", Appendix 2's clause
number for the same rule. A citation that cannot be constructed without being
appendix-scoped cannot drift that way.

Clause numbers verified against the text served by GET /sections/{id}.

Data hardcoded from CAO 48.1 Instrument 2019 (Compilation No. 3, F2021C01239).
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class FlightTimeLimits:
    """Maximum flight time over rolling windows, each with its own clause."""
    period_28d_hours: Optional[float] = None
    period_28d_clause: str = ""
    period_365d_hours: Optional[float] = None
    period_365d_clause: str = ""
    period_168h_hours: Optional[float] = None    # Appendix 5
    period_168h_clause: str = ""
    period_90d_hours: Optional[float] = None     # Appendix 5
    period_90d_clause: str = ""
    period_384h_hours: Optional[float] = None    # Appendix 5A
    period_384h_clause: str = ""
    reset_after_days_off: Optional[int] = None   # days off to reset counter


@dataclass(frozen=True)
class DutyTimeLimits:
    """Maximum duty time over rolling windows, each with its own clause."""
    period_168h_hours: Optional[float] = None
    period_168h_clause: str = ""
    period_336h_hours: Optional[float] = None
    period_336h_clause: str = ""


@dataclass(frozen=True)
class RecoveryRequirements:
    """
    Minimum recovery periods required before the next FDP.

    Appendices 4B (§5.4) and 5 (§5.2) phrase the 336-hour and 504-hour blocks
    as "at least 1 of the following" — they are ALTERNATIVES, and satisfying
    either discharges the requirement. `alternative_336h_504h` marks that, so
    the two are not both demanded.
    """
    period_168h_min_hours: float = 36.0
    period_168h_local_nights: int = 2
    period_168h_clause: str = ""
    period_28d_days_off: Optional[int] = None
    period_28d_days_off_clause: str = ""
    # Alternative recovery windows (Appendices 4B, 5)
    period_336h_min_hours: Optional[float] = None
    period_336h_local_nights: Optional[int] = None
    period_336h_clause: str = ""
    period_504h_min_hours: Optional[float] = None
    period_504h_local_nights: Optional[int] = None
    period_504h_clause: str = ""
    alternative_336h_504h: bool = False
    # App 4B §5.3 and App 5 §5.3 make the 168-hour recovery block CONDITIONAL
    # on a trigger this API is not told about (3+ late-night FDPs, or an
    # increased FDP under §1.2/§1.3). Asserting it unconditionally raises
    # violations the legislation would not. Where set, the requirement is
    # surfaced as a condition the caller must verify rather than run as a
    # check — §8.4: a condition the API cannot evaluate belongs in
    # conditions_caller_must_verify, not in the checks list.
    period_168h_trigger: str = ""
    period_384h_days_off: Optional[int] = None   # Appendix 5A
    period_384h_days_off_clause: str = ""


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
        flight_time=FlightTimeLimits(period_28d_hours=100, period_28d_clause="§5.1", period_365d_hours=1000, period_365d_clause="§5.2"),
        duty_time=DutyTimeLimits(),  # not specified
        recovery=RecoveryRequirements(
            period_168h_min_hours=36, period_168h_clause="§4.2(a)", period_168h_local_nights=2,
            period_28d_days_off=6, period_28d_days_off_clause="§4.2(b)",
        ),
    ),
    "2": CumulativeLimitsConfig(
        appendix="2",
        flight_time=FlightTimeLimits(period_28d_hours=100, period_28d_clause="§11.1", period_365d_hours=1000, period_365d_clause="§11.2"),
        duty_time=DutyTimeLimits(period_168h_hours=60, period_168h_clause="§12.1", period_336h_hours=100, period_336h_clause="§12.2"),
        recovery=RecoveryRequirements(
            period_168h_min_hours=36, period_168h_clause="§10.5", period_168h_local_nights=2,
            period_28d_days_off=6, period_28d_days_off_clause="§10.6",
        ),
    ),
    "3": CumulativeLimitsConfig(
        appendix="3",
        flight_time=FlightTimeLimits(period_28d_hours=100, period_28d_clause="§9.1", period_365d_hours=1000, period_365d_clause="§9.2"),
        duty_time=DutyTimeLimits(period_168h_hours=60, period_168h_clause="§10.1", period_336h_hours=100, period_336h_clause="§10.2"),
        recovery=RecoveryRequirements(
            period_168h_min_hours=36, period_168h_clause="§8.5", period_168h_local_nights=2,
            period_28d_days_off=6, period_28d_days_off_clause="§8.6",
        ),
    ),
    "4": CumulativeLimitsConfig(
        appendix="4",
        flight_time=FlightTimeLimits(period_28d_hours=100, period_28d_clause="§9.1", period_365d_hours=1000, period_365d_clause="§9.2"),
        duty_time=DutyTimeLimits(period_168h_hours=60, period_168h_clause="§10.1", period_336h_hours=100, period_336h_clause="§10.2"),
        recovery=RecoveryRequirements(
            period_168h_min_hours=36, period_168h_clause="§8.5", period_168h_local_nights=2,
            period_28d_days_off=6, period_28d_days_off_clause="§8.6",
        ),
    ),
    "4A": CumulativeLimitsConfig(
        appendix="4A",
        flight_time=FlightTimeLimits(period_28d_hours=50, period_28d_clause="§6"),
        duty_time=DutyTimeLimits(period_168h_hours=45, period_168h_clause="§7.1", period_336h_hours=84, period_336h_clause="§7.2"),
        recovery=RecoveryRequirements(
            period_168h_min_hours=0, period_168h_local_nights=0,
            period_28d_days_off=None,
            period_384h_days_off=2, period_384h_days_off_clause="§5.3",  # 2 full days off in 14 consecutive days
        ),
    ),
    "4B": CumulativeLimitsConfig(
        appendix="4B",
        flight_time=FlightTimeLimits(period_28d_hours=100, period_28d_clause="§6.1", period_365d_hours=1000, period_365d_clause="§6.2"),
        duty_time=DutyTimeLimits(period_168h_hours=60, period_168h_clause="§7.1", period_336h_hours=100, period_336h_clause="§7.2"),
        recovery=RecoveryRequirements(
            alternative_336h_504h=True,
            period_168h_min_hours=36, period_168h_clause="§5.3", period_168h_local_nights=2,
            period_168h_trigger=(
                "the FCM conducted 3 or more FDPs involving a late-night "
                "operation, or an increased FDP under §1.2, in the 168-hour period"
            ),
            period_336h_min_hours=36, period_336h_clause="§5.4(a)", period_336h_local_nights=2,
            period_504h_min_hours=72, period_504h_clause="§5.4(b)", period_504h_local_nights=3,
        ),
    ),
    "5": CumulativeLimitsConfig(
        appendix="5",
        flight_time=FlightTimeLimits(
            period_168h_hours=50, period_168h_clause="§6.1",
            period_28d_hours=170, period_28d_clause="§6.2",
            period_90d_hours=450, period_90d_clause="§6.3",
            period_365d_hours=1200, period_365d_clause="§6.5",
            reset_after_days_off=5,
        ),
        duty_time=DutyTimeLimits(),  # not specified
        recovery=RecoveryRequirements(
            alternative_336h_504h=True,
            period_168h_min_hours=36, period_168h_clause="§5.3",
            period_168h_local_nights=2,
            period_168h_trigger=(
                "the FCM conducted 1 or 2 increased FDPs under §1.3 in the "
                "168-hour period"
            ),
            period_336h_min_hours=36, period_336h_clause="§5.2(a)", period_336h_local_nights=2,
            period_504h_min_hours=72, period_504h_clause="§5.2(b)", period_504h_local_nights=3,
        ),
    ),
    "5A": CumulativeLimitsConfig(
        appendix="5A",
        flight_time=FlightTimeLimits(
            period_384h_hours=100, period_384h_clause="§5.1",
            period_365d_hours=1200, period_365d_clause="§5.4",
            reset_after_days_off=5,
        ),
        duty_time=DutyTimeLimits(),  # not specified
        recovery=RecoveryRequirements(
            # Appendix 5A has no 168-hour recovery-block requirement. §4.1 is
            # the 10h off-duty period and §4.2 is 2 consecutive days off in
            # any 384 hours — that is the whole of it. The inherited 36h/2LN
            # default was emitting a check with no clause behind it.
            period_168h_min_hours=0, period_168h_local_nights=0,
            period_384h_days_off=2, period_384h_days_off_clause="§4.2",
        ),
    ),
    "6": CumulativeLimitsConfig(
        appendix="6",
        flight_time=FlightTimeLimits(period_28d_hours=100, period_28d_clause="§8.1", period_365d_hours=1000, period_365d_clause="§8.2"),
        duty_time=DutyTimeLimits(period_168h_hours=60, period_168h_clause="§9.1", period_336h_hours=100, period_336h_clause="§9.2"),
        recovery=RecoveryRequirements(
            period_168h_min_hours=36, period_168h_clause="§7.2", period_168h_local_nights=2,
            period_28d_days_off=6, period_28d_days_off_clause="§7.3",
        ),
    ),
}


def get_cumulative_config(appendix: str) -> CumulativeLimitsConfig | None:
    """Return cumulative limits for a given appendix, or None if invalid."""
    return CUMULATIVE_CONFIGS.get(appendix.upper())
