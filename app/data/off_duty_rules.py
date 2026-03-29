"""
Off-duty period (ODP) rules for all CAO 48.1 appendices.

Encodes the per-appendix branching logic for calculating minimum off-duty periods,
including home/away distinctions, displacement time, and reduction eligibility.

Data hardcoded from CAO 48.1 Instrument 2019 (Compilation No. 3, F2021C01239).
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class OdpReductionRules:
    """Conditions under which ODP may be reduced below the base minimum."""
    reduction_to_9h: bool = False
    reduction_to_9h_clause: str = ""
    reduction_to_9h_conditions: tuple[str, ...] = ()

    reduction_to_14h: bool = False
    reduction_to_14h_clause: str = ""
    reduction_to_14h_conditions: tuple[str, ...] = ()

    reduction_to_12h: bool = False   # Appendix 4B
    reduction_to_12h_clause: str = ""
    reduction_to_12h_conditions: tuple[str, ...] = ()


@dataclass(frozen=True)
class OffDutyConfig:
    """Complete off-duty rules for one appendix."""
    appendix: str
    clause: str  # primary clause reference

    # Calculation type: "simple_fixed", "home_away", "home_away_displacement",
    # "night_branching", "formula", "simple_10h"
    calc_type: str

    # Base minimums (used by home_away and home_away_displacement types)
    base_away_hours: float = 10.0
    base_home_hours: float = 12.0

    # For <=12h / >12h branching (applies to most appendices)
    threshold_hours: float = 12.0  # FDP + post-duty threshold
    over_threshold_base_hours: float = 12.0
    over_threshold_multiplier: float = 1.5  # applied to excess over threshold

    # Displacement time (Appendices 2, 4, 4B)
    displacement_time: bool = False
    displacement_west_threshold: float = 3.0  # hours west
    displacement_east_threshold: float = 2.0  # hours east

    # Night window branching (Appendices 4B, 5)
    night_window_start: int = 0    # minutes from midnight
    night_window_end: int = 0      # minutes from midnight
    base_with_night_hours: float = 0.0   # base when FDP includes night window
    base_without_night_hours: float = 0.0  # base when FDP doesn't include night window

    # Extension penalty (Appendices 4B, 5)
    extension_penalty_hours_per_30min: float = 0.0

    # Reduction eligibility
    reductions: OdpReductionRules = OdpReductionRules()

    # Simple fixed (Appendix 1, 4A, 5A)
    fixed_min_hours: float = 0.0


# ═══════════════════════════════════════════════════════════════════════
# Per-appendix configurations
# ═══════════════════════════════════════════════════════════════════════

_STANDARD_9H_CONDITIONS = (
    "Previous ODP >=12h including local night",
    "FCM acclimatised (if applicable)",
    "ODP over a local night",
    "Away from home base",
    "Next ODP >=12h including local night",
)

_STANDARD_14H_CONDITIONS = (
    "Away from home base",
    "FDP not extended beyond limit",
    "FCM acclimatised for next FDP (if applicable)",
    "Subsequent ODP >=36h with 2 local nights",
)

OFF_DUTY_CONFIGS: dict[str, OffDutyConfig] = {
    # Appendix 1: Simple 12h in any 24h period
    "1": OffDutyConfig(
        appendix="1",
        clause="§4",
        calc_type="simple_fixed",
        fixed_min_hours=12.0,
    ),

    # Appendix 2: Home/away with displacement time, acclimatisation branching
    "2": OffDutyConfig(
        appendix="2",
        clause="§10",
        calc_type="home_away_displacement",
        base_away_hours=10.0,
        base_home_hours=12.0,
        threshold_hours=12.0,
        over_threshold_base_hours=12.0,
        over_threshold_multiplier=1.5,
        displacement_time=True,
        reductions=OdpReductionRules(
            reduction_to_9h=True,
            reduction_to_9h_clause="§10.4",
            reduction_to_9h_conditions=_STANDARD_9H_CONDITIONS,
            reduction_to_14h=True,
            reduction_to_14h_clause="§10.5",
            reduction_to_14h_conditions=_STANDARD_14H_CONDITIONS,
        ),
    ),

    # Appendix 3: Home/away without displacement time
    "3": OffDutyConfig(
        appendix="3",
        clause="§8",
        calc_type="home_away",
        base_away_hours=10.0,
        base_home_hours=12.0,
        threshold_hours=12.0,
        over_threshold_base_hours=12.0,
        over_threshold_multiplier=1.5,
        reductions=OdpReductionRules(
            reduction_to_9h=True,
            reduction_to_9h_clause="§8.3",
            reduction_to_9h_conditions=_STANDARD_9H_CONDITIONS,
            reduction_to_14h=True,
            reduction_to_14h_clause="§8.4",
            reduction_to_14h_conditions=_STANDARD_14H_CONDITIONS,
        ),
    ),

    # Appendix 4: Home/away with displacement time
    "4": OffDutyConfig(
        appendix="4",
        clause="§8",
        calc_type="home_away_displacement",
        base_away_hours=10.0,
        base_home_hours=12.0,
        threshold_hours=12.0,
        over_threshold_base_hours=12.0,
        over_threshold_multiplier=1.5,
        displacement_time=True,
        reductions=OdpReductionRules(
            reduction_to_9h=True,
            reduction_to_9h_clause="§8.3",
            reduction_to_9h_conditions=_STANDARD_9H_CONDITIONS,
            reduction_to_14h=True,
            reduction_to_14h_clause="§8.4",
            reduction_to_14h_conditions=_STANDARD_14H_CONDITIONS,
        ),
    ),

    # Appendix 4A: Simple 10h following FDP
    "4A": OffDutyConfig(
        appendix="4A",
        clause="§5",
        calc_type="simple_fixed",
        fixed_min_hours=10.0,
    ),

    # Appendix 4B: Night window branching with extension penalty
    "4B": OffDutyConfig(
        appendix="4B",
        clause="§5",
        calc_type="night_branching",
        night_window_start=23 * 60,       # 2300 local
        night_window_end=5 * 60 + 59,     # 0559 local
        base_with_night_hours=8.0,
        base_without_night_hours=10.0,
        threshold_hours=12.0,
        over_threshold_multiplier=1.0,     # +excess (not 1.5x)
        displacement_time=True,
        extension_penalty_hours_per_30min=1.0,
        reductions=OdpReductionRules(
            reduction_to_12h=True,
            reduction_to_12h_clause="§5.2",
            reduction_to_12h_conditions=(
                "Calculated ODP >12 hours",
                "Next FDP under Appendix 4B",
                "Following ODP >=24 hours",
            ),
        ),
    ),

    # Appendix 5: Night window branching with extension penalty
    "5": OffDutyConfig(
        appendix="5",
        clause="§5",
        calc_type="night_branching",
        night_window_start=23 * 60,       # 2300 local
        night_window_end=5 * 60 + 59,     # 0559 local
        base_with_night_hours=8.0,
        base_without_night_hours=10.0,
        extension_penalty_hours_per_30min=1.0,
        reductions=OdpReductionRules(
            reduction_to_12h=True,
            reduction_to_12h_clause="§5.2",
            reduction_to_12h_conditions=(
                "Calculated ODP >12 hours",
                "Next FDP under Appendix 5",
                "Following ODP >=36h with 2 local nights",
            ),
        ),
    ),

    # Appendix 5A: Simple 10h
    "5A": OffDutyConfig(
        appendix="5A",
        clause="§4",
        calc_type="simple_fixed",
        fixed_min_hours=10.0,
    ),

    # Appendix 6: Formula-based — 12h + 1.5 x excess over 12h
    "6": OffDutyConfig(
        appendix="6",
        clause="§7",
        calc_type="formula",
        threshold_hours=12.0,
        over_threshold_base_hours=12.0,
        over_threshold_multiplier=1.5,
        fixed_min_hours=12.0,  # minimum when <=12h
    ),
}


def get_off_duty_config(appendix: str) -> OffDutyConfig | None:
    """Return off-duty rules for a given appendix, or None if invalid."""
    return OFF_DUTY_CONFIGS.get(appendix.upper())
