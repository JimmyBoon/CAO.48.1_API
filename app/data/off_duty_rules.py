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
    # §10.3 / §8.3 open with "if the sum of an FCM's FDP, and his or her duty
    # time ... does not exceed 10 hours". The reduction is unavailable above
    # this, regardless of the other conditions.
    reduction_to_9h_max_duty_hours: float = 10.0
    # §10.3(b) — Appendix 2 only — "the FCM is acclimatised at the
    # commencement of the ODP 2". Appendices 3 and 4 have no such condition.
    reduction_to_9h_requires_acclimatised: bool = False

    reduction_to_14h: bool = False
    reduction_to_14h_clause: str = ""
    reduction_to_14h_conditions: tuple[str, ...] = ()
    # §10.4(c) — Appendix 2 only — "the FCM commences the second FDP in an
    # acclimatised state".
    reduction_to_14h_requires_acclimatised: bool = False

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

    # ─── Unknown state of acclimatisation (Appendix 2 only) ───────────
    # §10.1(c) and §10.2(b) are SEPARATE BRANCHES, not modifiers on the
    # acclimatised ones: the base is 14 hours with no home base / away
    # distinction, and the FULL displacement time applies rather than only the
    # excess. Left as None where the appendix has no unknown-state branch.
    unknown_state_base_hours: Optional[float] = None
    unknown_state_over_threshold_base_hours: Optional[float] = None

    # Displacement time (Appendices 2, 4, 4B)
    displacement_time: bool = False
    displacement_west_threshold: float = 3.0  # hours west
    displacement_east_threshold: float = 2.0  # hours east
    # Appendix 4B §5.1(a)(iii)/(b)(iii) take "the amount of displacement time of
    # the FDP" — the full amount, with no west/east threshold at all.
    displacement_full_always: bool = False

    # ─── Clause citations ─────────────────────────────────────────────
    # Spelled out per branch rather than assembled from a prefix. The clause is
    # the one part of the response a crew member can take to their operator, so
    # a citation that points at the wrong subclause is worse than none: it looks
    # checkable and fails when checked. Note that the >12h branches live in a
    # DIFFERENT subclause (§10.2 / §8.2) from the <=12h ones (§10.1 / §8.1).
    clause_le_threshold_away: str = ""
    clause_le_threshold_home: str = ""
    clause_le_threshold_unknown: str = ""
    clause_over_threshold: str = ""
    clause_over_threshold_unknown: str = ""

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

# Appendices 3 and 4 (§8.3): no acclimatisation condition in the instrument.
_STANDARD_9H_CONDITIONS = (
    "FDP + other duty time does not exceed 10 hours",
    "Previous ODP >=12h including local night",
    "ODP over a local night",
    "Away from home base",
    "Next ODP >=12h including local night",
)

# Appendix 2 (§10.3) adds paragraph (b), the acclimatisation condition.
_APPENDIX_2_9H_CONDITIONS = (
    "FDP + other duty time does not exceed 10 hours",
    "Previous ODP >=12h including local night",
    "FCM acclimatised at commencement of ODP 2",
    "ODP over a local night",
    "Away from home base",
    "Next ODP >=12h including local night",
)

# Appendices 3 and 4 (§8.4): no acclimatisation condition.
_STANDARD_14H_CONDITIONS = (
    "Calculated ODP exceeds 14 hours",
    "Away from home base",
    "FDP not extended beyond limit",
    "Subsequent ODP >=36h with 2 local nights",
)

# Appendix 2 (§10.4) adds paragraph (c), the acclimatisation condition.
_APPENDIX_2_14H_CONDITIONS = (
    "Calculated ODP exceeds 14 hours",
    "Away from home base",
    "FDP not extended beyond limit",
    "FCM commences the second FDP in an acclimatised state",
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

    # Appendix 2 §10: home/away, displacement time, and a separate
    # unknown-state branch.
    "2": OffDutyConfig(
        appendix="2",
        clause="§10",
        calc_type="home_away_displacement",
        base_away_hours=10.0,          # §10.1(a)(i)
        base_home_hours=12.0,          # §10.1(b)(i)
        threshold_hours=12.0,
        over_threshold_base_hours=12.0,  # §10.2(a)
        over_threshold_multiplier=1.5,
        unknown_state_base_hours=14.0,                  # §10.1(c)(i)
        unknown_state_over_threshold_base_hours=14.0,   # §10.2(b)
        displacement_time=True,
        clause_le_threshold_away="§10.1a",
        clause_le_threshold_home="§10.1b",
        clause_le_threshold_unknown="§10.1c",
        clause_over_threshold="§10.2a",
        clause_over_threshold_unknown="§10.2b",
        reductions=OdpReductionRules(
            reduction_to_9h=True,
            reduction_to_9h_clause="§10.3",
            reduction_to_9h_conditions=_APPENDIX_2_9H_CONDITIONS,
            reduction_to_9h_max_duty_hours=10.0,
            reduction_to_9h_requires_acclimatised=True,   # §10.3(b)
            reduction_to_14h=True,
            reduction_to_14h_clause="§10.4",
            reduction_to_14h_conditions=_APPENDIX_2_14H_CONDITIONS,
            reduction_to_14h_requires_acclimatised=True,  # §10.4(c)
        ),
    ),

    # Appendix 3 §8: home/away, no displacement time, no unknown-state branch.
    "3": OffDutyConfig(
        appendix="3",
        clause="§8",
        calc_type="home_away",
        base_away_hours=10.0,
        base_home_hours=12.0,
        threshold_hours=12.0,
        over_threshold_base_hours=12.0,
        over_threshold_multiplier=1.5,
        clause_le_threshold_away="§8.1a",
        clause_le_threshold_home="§8.1b",
        clause_over_threshold="§8.2",
        reductions=OdpReductionRules(
            reduction_to_9h=True,
            reduction_to_9h_clause="§8.3",
            reduction_to_9h_conditions=_STANDARD_9H_CONDITIONS,
            reduction_to_9h_max_duty_hours=10.0,
            reduction_to_14h=True,
            reduction_to_14h_clause="§8.4",
            reduction_to_14h_conditions=_STANDARD_14H_CONDITIONS,
        ),
    ),

    # Appendix 4 §8: home/away with displacement time, no unknown-state branch.
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
        clause_le_threshold_away="§8.1a",
        clause_le_threshold_home="§8.1b",
        clause_over_threshold="§8.2",
        reductions=OdpReductionRules(
            reduction_to_9h=True,
            reduction_to_9h_clause="§8.3",
            reduction_to_9h_conditions=_STANDARD_9H_CONDITIONS,
            reduction_to_9h_max_duty_hours=10.0,
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

    # Appendix 4B §5.1: night window branching, plus the excess over 12h, the
    # FULL displacement time of the FDP, and the extension penalty.
    "4B": OffDutyConfig(
        appendix="4B",
        clause="§5",
        calc_type="night_branching",
        night_window_start=23 * 60,       # 2300 local
        night_window_end=5 * 60 + 59,     # 0559 local
        base_with_night_hours=8.0,        # §5.1(a)(i)
        base_without_night_hours=10.0,    # §5.1(b)(i)
        threshold_hours=12.0,
        over_threshold_multiplier=1.0,     # §5.1(a)(ii) — +excess, not 1.5x
        displacement_time=True,
        # §5.1(a)(iii)/(b)(iii): "the amount of displacement time of the FDP" —
        # the full amount, with no west/east threshold.
        displacement_full_always=True,
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

    # Appendix 5 §5.1: a FLAT 8 or 10 hours, plus only the §3.2 extension
    # penalty. Unlike Appendix 4B, §5.1 contains no excess-over-12h addend and
    # no displacement term — the multiplier is therefore zero rather than the
    # inherited default, which was adding 1.5x the excess and over-reporting.
    "5": OffDutyConfig(
        appendix="5",
        clause="§5",
        calc_type="night_branching",
        night_window_start=23 * 60,       # 2300 local
        night_window_end=5 * 60 + 59,     # 0559 local
        base_with_night_hours=8.0,        # §5.1(a)
        base_without_night_hours=10.0,    # §5.1(b)
        over_threshold_multiplier=0.0,
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
