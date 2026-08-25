"""
Off-duty period (ODP) rules for all CAO 48.1 appendices.

Encodes the per-appendix branching logic for calculating minimum off-duty periods,
including home/away distinctions, acclimatisation branching, displacement time,
and reduction eligibility.

Two things are deliberate here:

1. **Clause references live beside the limits they annotate.** A citation that is
   built at the emission site drifts from the rule it describes; Appendix 3
   recovery was emitted as Appendix 2's §10.5a for exactly that reason.

2. **Reduction conditions are data, not prose, and each appendix owns its own
   set.** Appendix 2 §10.3 has five conditions and §10.4 has four, because both
   require an acclimatised state. The Appendix 3 and Appendix 4 equivalents have
   four and three. Sharing one list across appendices is what dropped §10.4(c).

Data hardcoded from CAO 48.1 Instrument 2019 (Compilation No. 3, F2021C01239),
verified against the text served by GET /sections/{id}.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class OdpCondition:
    """
    One condition attached to a reduction provision.

    ``key`` names the check the calculator runs against supplied data. An empty
    key means the API cannot verify this condition — it concerns a period that
    has not happened yet, or a fact held outside this API. Such a condition is
    reported for the caller's attention and never counts toward eligibility.
    """
    clause: str
    description: str
    key: str = ""

    @property
    def verifiable(self) -> bool:
        return bool(self.key)


@dataclass(frozen=True)
class OdpReductionRules:
    """Conditions under which ODP may be reduced below the base minimum."""

    # ─── Reduction to 9h (App 2 §10.3, App 3 §8.3, App 4 §8.3) ───────
    reduction_to_9h: bool = False
    reduction_to_9h_clause: str = ""
    reduction_to_9h_conditions: tuple[OdpCondition, ...] = ()
    # "Despite subclause X.1, if the sum of FDP and other duty time does not
    # exceed 10 hours..." — a gate on the provision, not one of the conditions.
    reduction_to_9h_max_duty_hours: float = 10.0

    # ─── Reduction to 14h (App 2 §10.4, App 3 §8.4, App 4 §8.4) ──────
    reduction_to_14h: bool = False
    reduction_to_14h_clause: str = ""
    reduction_to_14h_conditions: tuple[OdpCondition, ...] = ()

    # ─── Reduction to 12h (App 4B, App 5) ────────────────────────────
    reduction_to_12h: bool = False
    reduction_to_12h_clause: str = ""
    reduction_to_12h_conditions: tuple[OdpCondition, ...] = ()


@dataclass(frozen=True)
class OffDutyConfig:
    """Complete off-duty rules for one appendix."""
    appendix: str
    clause: str  # primary clause reference for the appendix's ODP rules

    # Calculation type: "simple_fixed", "home_away", "home_away_displacement",
    # "night_branching", "formula"
    calc_type: str

    # Base minimums (used by home_away and home_away_displacement types)
    base_away_hours: float = 10.0
    base_home_hours: float = 12.0

    # For <=12h / >12h branching (applies to most appendices)
    threshold_hours: float = 12.0  # FDP + post-duty threshold
    over_threshold_base_hours: float = 12.0
    over_threshold_multiplier: float = 1.5  # applied to excess over threshold

    # ─── Acclimatisation branching (Appendix 2 only) ─────────────────
    # App 2 §10.1(c): unknown state — 14h + the FULL displacement time,
    # irrespective of home base or away.
    # App 2 §10.2(b): unknown state — 14h + 1.5 x excess + full displacement.
    # Appendix 4 has displacement but NO acclimatisation branch (§8.1 is
    # away/home only), so this flag is what separates them.
    acclimatisation_branching: bool = False
    unknown_base_hours: float = 14.0
    unknown_over_threshold_base_hours: float = 14.0

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

    # ─── Clause references for the base calculation ──────────────────
    clause_under_threshold_away: str = ""
    clause_under_threshold_home: str = ""
    clause_under_threshold_unknown: Optional[str] = None
    clause_over_threshold: str = ""
    clause_over_threshold_unknown: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════
# Reduction condition sets — one per appendix, never shared
# ═══════════════════════════════════════════════════════════════════════

# ─── Appendix 2 §10.3 — five conditions, (b) requires acclimatisation ──
_APP2_9H_CONDITIONS = (
    OdpCondition(
        "§10.3(a)",
        "The off-duty period immediately before the last FDP was at least "
        "12 hours, including a local night",
        key="preceding_odp_12h_with_local_night",
    ),
    OdpCondition(
        "§10.3(b)",
        "The FCM is acclimatised at the commencement of ODP 2",
        key="acclimatised",
    ),
    OdpCondition(
        "§10.3(c)",
        "ODP 2 is undertaken over a local night",
        key="odp_over_local_night",
    ),
    OdpCondition(
        "§10.3(d)",
        "ODP 2 is not undertaken at home base",
        key="away_from_home_base",
    ),
    OdpCondition(
        "§10.3(e)",
        "The off-duty period following the FDP after ODP 2 is at least "
        "12 hours, including a local night",
    ),
)

# ─── Appendix 2 §10.4 — four conditions, (c) requires acclimatisation ──
_APP2_14H_CONDITIONS = (
    OdpCondition(
        "§10.4(a)",
        "The reduced off-duty period is undertaken away from home base",
        key="away_from_home_base",
    ),
    OdpCondition(
        "§10.4(b)",
        "The first FDP was not extended past the FDP limit provided for under "
        "the AOC holder's operations manual",
        key="fdp_not_extended",
    ),
    OdpCondition(
        "§10.4(c)",
        "The FCM commences the second FDP in an acclimatised state",
        key="acclimatised",
    ),
    OdpCondition(
        "§10.4(d)",
        "The off-duty period following the second FDP is of at least "
        "36 consecutive hours and includes 2 local nights",
    ),
)

# ─── Appendices 3 and 4 §8.3 — four conditions, no acclimatisation ────
def _9h_conditions(clause: str) -> tuple[OdpCondition, ...]:
    return (
        OdpCondition(
            f"{clause}(a)",
            "The off-duty period immediately before the last FDP was at least "
            "12 hours, including a local night",
            key="preceding_odp_12h_with_local_night",
        ),
        OdpCondition(
            f"{clause}(b)",
            "ODP 2 is undertaken over a local night",
            key="odp_over_local_night",
        ),
        OdpCondition(
            f"{clause}(c)",
            "ODP 2 is not undertaken at home base",
            key="away_from_home_base",
        ),
        OdpCondition(
            f"{clause}(d)",
            "The off-duty period following the FDP after ODP 2 is at least "
            "12 hours, including a local night",
        ),
    )


# ─── Appendices 3 and 4 §8.4 — three conditions, no acclimatisation ───
def _14h_conditions(clause: str) -> tuple[OdpCondition, ...]:
    return (
        OdpCondition(
            f"{clause}(a)",
            "The reduced off-duty period is undertaken away from home base",
            key="away_from_home_base",
        ),
        OdpCondition(
            f"{clause}(b)",
            "The first FDP was not extended past the FDP limit provided for "
            "under the AOC holder's operations manual",
            key="fdp_not_extended",
        ),
        OdpCondition(
            f"{clause}(c)",
            "The off-duty period following the second FDP is of at least "
            "36 consecutive hours and includes 2 local nights",
        ),
    )


# ═══════════════════════════════════════════════════════════════════════
# Per-appendix configurations
# ═══════════════════════════════════════════════════════════════════════

OFF_DUTY_CONFIGS: dict[str, OffDutyConfig] = {
    # Appendix 1: Simple 12h in any 24h period
    "1": OffDutyConfig(
        appendix="1",
        clause="§4",
        calc_type="simple_fixed",
        fixed_min_hours=12.0,
        clause_under_threshold_away="§4.1",
        clause_under_threshold_home="§4.1",
        clause_over_threshold="§4.1",
    ),

    # Appendix 2: acclimatisation branching + displacement time
    "2": OffDutyConfig(
        appendix="2",
        clause="§10",
        calc_type="home_away_displacement",
        base_away_hours=10.0,
        base_home_hours=12.0,
        threshold_hours=12.0,
        over_threshold_base_hours=12.0,
        over_threshold_multiplier=1.5,
        acclimatisation_branching=True,
        unknown_base_hours=14.0,
        unknown_over_threshold_base_hours=14.0,
        displacement_time=True,
        clause_under_threshold_away="§10.1(a)",
        clause_under_threshold_home="§10.1(b)",
        clause_under_threshold_unknown="§10.1(c)",
        clause_over_threshold="§10.2(a)",
        clause_over_threshold_unknown="§10.2(b)",
        reductions=OdpReductionRules(
            reduction_to_9h=True,
            reduction_to_9h_clause="§10.3",
            reduction_to_9h_conditions=_APP2_9H_CONDITIONS,
            reduction_to_14h=True,
            reduction_to_14h_clause="§10.4",
            reduction_to_14h_conditions=_APP2_14H_CONDITIONS,
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
        clause_under_threshold_away="§8.1(a)",
        clause_under_threshold_home="§8.1(b)",
        clause_over_threshold="§8.2",
        reductions=OdpReductionRules(
            reduction_to_9h=True,
            reduction_to_9h_clause="§8.3",
            reduction_to_9h_conditions=_9h_conditions("§8.3"),
            reduction_to_14h=True,
            reduction_to_14h_clause="§8.4",
            reduction_to_14h_conditions=_14h_conditions("§8.4"),
        ),
    ),

    # Appendix 4: displacement time, but NO acclimatisation branch (§8.1)
    "4": OffDutyConfig(
        appendix="4",
        clause="§8",
        calc_type="home_away_displacement",
        base_away_hours=10.0,
        base_home_hours=12.0,
        threshold_hours=12.0,
        over_threshold_base_hours=12.0,
        over_threshold_multiplier=1.5,
        acclimatisation_branching=False,
        displacement_time=True,
        clause_under_threshold_away="§8.1(a)",
        clause_under_threshold_home="§8.1(b)",
        clause_over_threshold="§8.2",
        reductions=OdpReductionRules(
            reduction_to_9h=True,
            reduction_to_9h_clause="§8.3",
            reduction_to_9h_conditions=_9h_conditions("§8.3"),
            reduction_to_14h=True,
            reduction_to_14h_clause="§8.4",
            reduction_to_14h_conditions=_14h_conditions("§8.4"),
        ),
    ),

    # Appendix 4A: Simple 10h following FDP
    "4A": OffDutyConfig(
        appendix="4A",
        clause="§5",
        calc_type="simple_fixed",
        fixed_min_hours=10.0,
        clause_under_threshold_away="§5.1",
        clause_under_threshold_home="§5.1",
        clause_over_threshold="§5.1",
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
        clause_under_threshold_away="§5.1",
        clause_under_threshold_home="§5.1",
        clause_over_threshold="§5.1",
        reductions=OdpReductionRules(
            reduction_to_12h=True,
            reduction_to_12h_clause="§5.2",
            reduction_to_12h_conditions=(
                OdpCondition("§5.2(a)", "Calculated ODP is more than 12 hours",
                             key="calculated_over_12h"),
                OdpCondition("§5.2(b)", "The next FDP is under Appendix 4B"),
                OdpCondition("§5.2(c)", "The following off-duty period is at "
                                        "least 24 hours"),
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
        clause_under_threshold_away="§5.1",
        clause_under_threshold_home="§5.1",
        clause_over_threshold="§5.1",
        reductions=OdpReductionRules(
            reduction_to_12h=True,
            reduction_to_12h_clause="§5.2",
            reduction_to_12h_conditions=(
                OdpCondition("§5.2(a)", "Calculated ODP is more than 12 hours",
                             key="calculated_over_12h"),
                OdpCondition("§5.2(b)", "The next FDP is under Appendix 5"),
                OdpCondition("§5.2(c)", "The following off-duty period is at "
                                        "least 36 hours with 2 local nights"),
            ),
        ),
    ),

    # Appendix 5A: Simple 10h
    "5A": OffDutyConfig(
        appendix="5A",
        clause="§4",
        calc_type="simple_fixed",
        fixed_min_hours=10.0,
        clause_under_threshold_away="§4.1",
        clause_under_threshold_home="§4.1",
        clause_over_threshold="§4.1",
    ),

    # Appendix 6: Formula-based — 12h + 1.5 x excess over 12h (§7.1)
    "6": OffDutyConfig(
        appendix="6",
        clause="§7",
        calc_type="formula",
        threshold_hours=12.0,
        over_threshold_base_hours=12.0,
        over_threshold_multiplier=1.5,
        fixed_min_hours=12.0,  # minimum when <=12h
        clause_under_threshold_away="§7.1",
        clause_under_threshold_home="§7.1",
        clause_over_threshold="§7.1",
    ),
}


def get_off_duty_config(appendix: str) -> OffDutyConfig | None:
    """Return off-duty rules for a given appendix, or None if invalid."""
    return OFF_DUTY_CONFIGS.get(appendix.upper())
