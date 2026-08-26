"""
FDP (Flight Duty Period) lookup tables for all CAO 48.1 appendices.

Each appendix has one or more FDP tables that map operational parameters
(time of day, sector count, crew configuration) to maximum FDP hours.

Data is hardcoded from CAO 48.1 Instrument 2019 (Compilation No. 3, F2021C01239).
"""

from dataclasses import dataclass, field
from typing import Optional


# ─── Time band helper ─────────────────────────────────────────────────

@dataclass(frozen=True)
class TimeBand:
    """A time range expressed as minutes from midnight (inclusive both ends)."""
    start: int  # minutes from midnight
    end: int    # minutes from midnight
    label: str  # e.g. "0700-1259"


def _hm(h: int, m: int = 0) -> int:
    """Convert hours and minutes to minutes from midnight."""
    return h * 60 + m


# ─── Split duty rules ─────────────────────────────────────────────────

@dataclass(frozen=True)
class SplitDutyRules:
    """Appendix-specific split duty parameters."""
    sleeping_min_hours: float          # min rest for sleeping accommodation credit
    sleeping_extension_type: str       # "fixed" (e.g. +4h) or "duration" (+=rest hours)
    sleeping_fixed_extension: float    # hours added if type="fixed"
    sleeping_cap_hours: float          # absolute FDP cap after sleeping extension
    resting_min_hours: float           # min rest for resting accommodation credit
    resting_extension_pct: float       # fraction of rest added (e.g. 0.5 = 50%)
    resting_max_extension: float       # max hours added from resting
    post_split_max_hours: float        # max FDP after the rest ends
    night_overlap_window: tuple[int, int] = (_hm(23), _hm(5, 29))  # local time window
    night_overlap_min_sleeping: float = 7.0   # min sleeping hours if overlaps night window
    night_overlap_cap_hours: float = 16.0     # cap if night overlap sleeping met
    night_overlap_credit_reduction: bool = False  # True = no 2h ODP credit when night overlap
    # Whether this appendix HAS a night-overlap condition at all. App 2 §4.4,
    # App 3 §3.4, App 4 §3.4, App 4A §3.3 and App 6 §3.4 impose one; App 4B
    # clause 2 and App 5 clause 2 do not, and gating them would deny an
    # increase the instrument grants. Defaults False so a new appendix is not
    # silently gated by inherited window values.
    # App 4B §2.2: the remaining FDP after the rest ends must not exceed the
    # Table 1.1 limit that would apply to an FCM commencing a NEW FDP at the
    # resumption time. That is a lookup, not a constant, so post_split_max
    # cannot express it — and 99.0 meant no post-split limit was applied at
    # all on the appendix covering medical transport and emergency services.
    post_split_max_from_table: bool = False
    night_overlap_gate: bool = False
    # Whether satisfying the gate also grants an increase to a stated ceiling
    # (App 3 §3.4(b), App 4 §3.4(b)). Appendix 4A's §3.3 has no such limb —
    # its (b) is the ODP-credit exclusion — so a compliant night-overlapping
    # rest there takes the ordinary §3.1 treatment.
    night_overlap_grants_increase: bool = False
    split_duty_odp_credit_hours: float = 2.0  # hours deducted from effective FDP for ODP calc
    available: bool = True             # False for appendices with no split duty


# ─── FDP table row ────────────────────────────────────────────────────

@dataclass(frozen=True)
class FdpTableRow:
    """One row of an FDP table: a time band with FDP limits per sector group."""
    time_band: TimeBand
    sectors: dict[str, float]  # e.g. {"1-3": 13.0, "4": 12.5, ...} or {"all": 9.0}


# ─── FDP table ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FdpTable:
    """A complete FDP lookup table for one appendix/sub-table."""
    table_id: str
    lookup_key: str          # e.g. "local_time_and_sectors", "acclimatised_time_and_sectors"
    rows: list[FdpTableRow]
    flight_time_limit_hours: Optional[float] = None
    notes: str = ""


# ─── Extension rules ──────────────────────────────────────────────────

@dataclass(frozen=True)
class ExtensionRules:
    """
    FDP extension allowances for one appendix.

    Appendix 4B is the reason this is a structure rather than a single number.
    Its clause 3 is titled "Extensions" and grants two distinct provisions with
    different limits, different ceilings, and a single-pilot distinction:

      §3.1 unforeseen operational circumstances — 2h multi-pilot, 1h
           single-pilot, beyond (a) the Table 1.1 limit, or (b) that limit as
           increased by a split-duty rest, *provided the extended FDP does not
           exceed 16 hours*. Read the proviso carefully: it attaches to
           §3.1(b) only. §3.1(a) carries no explicit ceiling.

      §3.2 urgent operations — 4h, beyond (c) the Table 1.1 limit or (d) the
           split-duty-increased limit, both capped at 16 hours.

    Encoding this as `max_extension_hours = 0.0` produced a flat denial that
    this appendix permits no extension at all, which is the opposite of what
    clause 3 says.
    """
    available: bool = True

    # §3.1 / §5.3 — unforeseen operational circumstances
    unforeseen_hours_multi_pilot: float = 1.0
    unforeseen_hours_single_pilot: float = 1.0
    # A ceiling that applies only where the base limit was increased by a
    # split-duty rest period (App 4B §3.1(b)). None = no explicit ceiling.
    unforeseen_ceiling_after_split_duty_hours: Optional[float] = None
    # A ceiling that applies unconditionally. None = no explicit ceiling.
    unforeseen_ceiling_hours: Optional[float] = None
    clause_unforeseen: str = ""
    # App 2 §7.3(a)(ii): 2 hours for an augmented crew operation under clause 5.
    unforeseen_hours_augmented_crew: Optional[float] = None
    clause_unforeseen_augmented: str = ""

    # §3.2 — urgent operations (Appendix 4B only)
    urgent_available: bool = False
    urgent_hours: float = 0.0
    urgent_ceiling_hours: Optional[float] = None
    clause_urgent: str = ""

    # §3.6 — an FDP limit must not be extended if doing so would breach the
    # cumulative flight time limits.
    clause_cumulative_crosscheck: str = ""

    # Facts the API cannot verify but which gate the provision.
    caller_must_verify: tuple[tuple[str, str], ...] = ()


# ─── Early start rules ────────────────────────────────────────────────

@dataclass(frozen=True)
class EarlyStartRules:
    """
    Consecutive early start limits.

    §11.1 (App 3 and 4), §13.1 (App 2), §10.1 (App 6) all read "an FCM must
    not be assigned more than 3 consecutive early starts", relieved by §11.3 /
    §13.3 / §10.3 which permit "a 4th, or a 4th and a 5th" with a 2h and 4h
    reduction respectively.

    The relief enumerates a 4th and a 5th. There is no 6th. Clamping the
    reduction at 4 hours for every subsequent start, which is what "5th+" did,
    permits a duty the instrument prohibits outright.
    """
    available: bool = False
    max_consecutive: int = 3
    # Ordinal of the early start -> hours the maximum FDP is reduced by.
    reductions: tuple[tuple[int, float], ...] = ((4, 2.0), (5, 4.0))
    clause_limit: str = ""    # §11.1 — the prohibition
    clause_relief: str = ""   # §11.3 — the 4th/5th allowance
    # §11.2 / §13.2 / §10.2: an FCM whose duties have already infringed
    # 3 consecutive WOCLs must not be assigned an FDP that would again
    # infringe the WOCL without an intervening off-duty period including a
    # local night.
    clause_wocl_limit: str = ""
    max_consecutive_wocl: int = 3


# ─── Appendix FDP configuration ──────────────────────────────────────

@dataclass(frozen=True)
class AppendixFdpConfig:
    """Complete FDP configuration for one appendix."""
    appendix: str
    tables: dict[str, FdpTable]  # keyed by sub-table selector
    split_duty: SplitDutyRules
    wocl_early_start: bool = False
    max_extension_hours: float = 1.0
    increased_fdp: bool = False
    extensions: ExtensionRules = ExtensionRules()
    early_starts: EarlyStartRules = EarlyStartRules()
    # Clause references for the split-duty provisions (§3.1/§3.3/§3.4 in
    # App 3 and 4; §4.x in App 2). Kept beside the rules they cite.
    clause_split_sleeping: str = ""
    clause_split_resting: str = ""
    clause_split_night_overlap: str = ""

    # ─── Appendix 1 §2.1 — the FDP must fall inside a fixed daily window ──
    # (a) the earlier of morning civil twilight or 0700 local; and
    # (b) 0100 local, at the commencing location, on the following day.
    # Only (b) is computable here: civil twilight needs a position this API is
    # not given. Because the (a) boundary is the EARLIER of the two, a start at
    # or after 0700 satisfies it whatever twilight was — an earlier start
    # cannot be resolved either way and is reported as data_unavailable rather
    # than guessed in either direction.
    fdp_window_start_local_minutes: Optional[int] = None
    fdp_window_end_local_minutes: Optional[int] = None
    clause_fdp_window_start: str = ""
    clause_fdp_window_end: str = ""

    # ─── Appendix 1 §2.5 — late FDPs ──────────────────────────────────
    late_fdp_after_local_minutes: Optional[int] = None
    late_fdp_max_in_168h: Optional[int] = None
    clause_late_fdp: str = ""


# ─── Sector key resolution ────────────────────────────────────────────

SECTOR_KEYS_6COL = ["1-3", "4", "5", "6", "7", "8+"]
SECTOR_KEYS_3COL = ["single_pilot", "multi_1_2", "multi_3+"]


def resolve_sector_key_6col(sectors: int) -> str:
    if sectors <= 3:
        return "1-3"
    elif sectors <= 7:
        return str(sectors)
    else:
        return "8+"


def resolve_sector_key_3col(sectors: int, single_pilot: bool) -> str:
    if single_pilot:
        return "single_pilot"
    elif sectors <= 2:
        return "multi_1_2"
    else:
        return "multi_3+"


# ═══════════════════════════════════════════════════════════════════════
# APPENDIX 1 — Basic Limits
# ═══════════════════════════════════════════════════════════════════════

# Appendix 1 contains NO split-duty provision — the word "split" does not
# appear anywhere in the appendix, whose clauses are 1 Sleep opportunity,
# 2 FDP and flight time limits, 3 Extensions, 4 Off-duty period limits,
# 5 Cumulative flight time. Flagged in Phase 3 and disabled here, in the
# deliberate Appendix-1 pass Phase 3 deferred to: these rules were granting a
# +1h FDP increase with no clause behind it. The values are retained only so
# the shape of the dataclass is satisfied; `available=False` means they are
# never consulted.
_APP1_SPLIT = SplitDutyRules(
    available=False,
    sleeping_min_hours=4.0,
    sleeping_extension_type="fixed",
    sleeping_fixed_extension=1.0,
    sleeping_cap_hours=10.0,
    resting_min_hours=99.0,   # no resting provision
    resting_extension_pct=0.0,
    resting_max_extension=0.0,
    post_split_max_hours=9.0,  # no specific post-split limit stated
    split_duty_odp_credit_hours=2.0,
)

APP1 = AppendixFdpConfig(
    appendix="1",
    tables={
        "default": FdpTable(
            table_id="Table 2.1",
            lookup_key="local_time",
            rows=[
                FdpTableRow(TimeBand(_hm(0), _hm(5, 59), "0000-0559"), {"all": 8.0}),
                FdpTableRow(TimeBand(_hm(6), _hm(13, 59), "0600-1359"), {"all": 9.0}),
                FdpTableRow(TimeBand(_hm(14), _hm(23, 59), "1400-2359"), {"all": 8.0}),
            ],
            notes="Simple fixed limits. No sector variation.",
        ),
    },
    split_duty=_APP1_SPLIT,
    max_extension_hours=1.0,
    extensions=ExtensionRules(
        unforeseen_hours_multi_pilot=1.0,
        unforeseen_hours_single_pilot=1.0,
        clause_unforeseen="§3.1",
        caller_must_verify=(
            ("§3.1(c)", "An extension is operationally necessary to complete the duty"),
            ("§3.1(d)", "The FCM considers himself or herself fit for the extension"),
        ),
    ),
    fdp_window_start_local_minutes=_hm(7),      # §2.1(a)(ii)
    fdp_window_end_local_minutes=_hm(1),        # §2.1(b), following day
    clause_fdp_window_start="§2.1(a)",
    clause_fdp_window_end="§2.1(b)",
    late_fdp_after_local_minutes=_hm(22),       # §2.5
    late_fdp_max_in_168h=3,
    clause_late_fdp="§2.5",
    # Appendix 1 has no split-duty provision — the word does not appear
    # anywhere in the appendix. No clause reference is available because
    # there is no clause. See the note on _APP1_SPLIT.
)


# ═══════════════════════════════════════════════════════════════════════
# APPENDIX 2 — Multi-Pilot Operations
# ═══════════════════════════════════════════════════════════════════════

_APP2_TIME_BANDS_7 = [
    TimeBand(_hm(0), _hm(4, 59), "0000-0459"),
    TimeBand(_hm(5), _hm(5, 59), "0500-0559"),
    TimeBand(_hm(6), _hm(6, 59), "0600-0659"),
    TimeBand(_hm(7), _hm(12, 59), "0700-1259"),
    TimeBand(_hm(13), _hm(13, 59), "1300-1359"),
    TimeBand(_hm(14), _hm(14, 59), "1400-1459"),
    TimeBand(_hm(15), _hm(23, 59), "1500-2359"),
]

_APP2_TABLE_2_1_ROWS = [
    FdpTableRow(_APP2_TIME_BANDS_7[0], {"1-3": 10, "4": 9.5, "5": 9, "6": 8.5, "7": 8, "8+": 7.5}),
    FdpTableRow(_APP2_TIME_BANDS_7[1], {"1-3": 11, "4": 10.5, "5": 10, "6": 9.5, "7": 9, "8+": 8.5}),
    FdpTableRow(_APP2_TIME_BANDS_7[2], {"1-3": 12, "4": 11.5, "5": 11, "6": 10.5, "7": 10, "8+": 9.5}),
    FdpTableRow(_APP2_TIME_BANDS_7[3], {"1-3": 13, "4": 12.5, "5": 12, "6": 11.5, "7": 11, "8+": 10.5}),
    FdpTableRow(_APP2_TIME_BANDS_7[4], {"1-3": 12, "4": 11.5, "5": 11, "6": 10.5, "7": 10, "8+": 9.5}),
    FdpTableRow(_APP2_TIME_BANDS_7[5], {"1-3": 11, "4": 10.5, "5": 10, "6": 9.5, "7": 9, "8+": 8.5}),
    FdpTableRow(_APP2_TIME_BANDS_7[6], {"1-3": 10, "4": 9.5, "5": 9, "6": 8.5, "7": 8, "8+": 7.5}),
]

_APP2_TABLE_3_1_ROWS = [
    FdpTableRow(
        TimeBand(0, 0, "<30h off-duty"),
        {"1-3": 10, "4": 9.5, "5": 9, "6": 8.5, "7": 8, "8+": 7.5},
    ),
    FdpTableRow(
        TimeBand(0, 0, ">=30h off-duty"),
        {"1-3": 12, "4": 11.5, "5": 11, "6": 10.5, "7": 10, "8+": 9.5},
    ),
]

# Augmented crew time bands (4 bands)
_APP2_AUG_BANDS = [
    TimeBand(_hm(7), _hm(10, 59), "0700-1059"),
    TimeBand(_hm(11), _hm(15, 59), "1100-1559"),
    TimeBand(_hm(16), _hm(4, 59), "1600-0459"),
    TimeBand(_hm(5), _hm(6, 59), "0500-0659"),
]

_APP2_TABLE_5_1_ROWS = [
    FdpTableRow(_APP2_AUG_BANDS[0], {"c1_1fcm": 16, "c1_2fcm": 18, "c2_1fcm": 15, "c2_2fcm": 16.5, "c3_1fcm": 14, "c3_2fcm": 15}),
    FdpTableRow(_APP2_AUG_BANDS[1], {"c1_1fcm": 16, "c1_2fcm": 18, "c2_1fcm": 15, "c2_2fcm": 16.5, "c3_1fcm": 13, "c3_2fcm": 14}),
    FdpTableRow(_APP2_AUG_BANDS[2], {"c1_1fcm": 16, "c1_2fcm": 18, "c2_1fcm": 15, "c2_2fcm": 16.5, "c3_1fcm": 12, "c3_2fcm": 13}),
    FdpTableRow(_APP2_AUG_BANDS[3], {"c1_1fcm": 16, "c1_2fcm": 18, "c2_1fcm": 15, "c2_2fcm": 16.5, "c3_1fcm": 13, "c3_2fcm": 14}),
]

_APP2_TABLE_5_2_ROWS = [
    FdpTableRow(
        TimeBand(0, 0, "<30h off-duty"),
        {"c1_1fcm": 16, "c1_2fcm": 18, "c2_1fcm": 15, "c2_2fcm": 16.5, "c3_1fcm": 12, "c3_2fcm": 13},
    ),
    FdpTableRow(
        TimeBand(0, 0, ">=30h off-duty"),
        {"c1_1fcm": 16, "c1_2fcm": 18, "c2_1fcm": 15, "c2_2fcm": 16.5, "c3_1fcm": 14, "c3_2fcm": 15},
    ),
]

_APP2_SPLIT = SplitDutyRules(
    night_overlap_gate=True,
    night_overlap_grants_increase=True,
    sleeping_min_hours=4.0,
    sleeping_extension_type="fixed",
    sleeping_fixed_extension=4.0,
    sleeping_cap_hours=16.0,
    resting_min_hours=2.0,
    resting_extension_pct=0.5,
    resting_max_extension=2.0,
    post_split_max_hours=6.0,
    night_overlap_window=(_hm(23), _hm(5, 29)),
    night_overlap_min_sleeping=7.0,
    night_overlap_cap_hours=16.0,
    night_overlap_credit_reduction=True,
    split_duty_odp_credit_hours=2.0,
)

APP2 = AppendixFdpConfig(
    appendix="2",
    tables={
        "acclimatised": FdpTable(
            table_id="Table 2.1",
            lookup_key="acclimatised_time_and_sectors",
            rows=_APP2_TABLE_2_1_ROWS,
            flight_time_limit_hours=10.5,
            notes="Uses acclimatised time. Flight time limit 10.5h (except augmented crew).",
        ),
        "unknown": FdpTable(
            table_id="Table 3.1",
            lookup_key="off_duty_duration_and_sectors",
            rows=_APP2_TABLE_3_1_ROWS,
            flight_time_limit_hours=10.5,
            notes="Unknown acclimatisation. Lookup by prior off-duty duration and sectors.",
        ),
        "augmented_acclimatised": FdpTable(
            table_id="Table 5.1",
            lookup_key="acclimatised_time_and_crew_config",
            rows=_APP2_TABLE_5_1_ROWS,
            flight_time_limit_hours=None,
            notes="Augmented crew, acclimatised. No flight time limit.",
        ),
        "augmented_unknown": FdpTable(
            table_id="Table 5.2",
            lookup_key="off_duty_duration_and_crew_config",
            rows=_APP2_TABLE_5_2_ROWS,
            flight_time_limit_hours=None,
            notes="Augmented crew, unknown acclimatisation. No flight time limit.",
        ),
    },
    split_duty=_APP2_SPLIT,
    wocl_early_start=True,
    max_extension_hours=1.0,
    extensions=ExtensionRules(
        unforeseen_hours_multi_pilot=1.0,
        unforeseen_hours_single_pilot=1.0,
        clause_unforeseen="§7.3(a)(i)",
        unforeseen_hours_augmented_crew=2.0,
        clause_unforeseen_augmented="§7.3(a)(ii)",
        caller_must_verify=(
            ("§7.4", "The PIC consulted each FCM and is satisfied each considers "
                     "himself or herself fit for the extension"),
        ),
    ),
    early_starts=EarlyStartRules(
        available=True,
        max_consecutive=3,
        clause_limit="§13.1",
        clause_relief="§13.3",
        clause_wocl_limit="§13.2",
    ),
    clause_split_sleeping="§4.1",
    clause_split_resting="§4.3",
    clause_split_night_overlap="§4.4",
)


# ═══════════════════════════════════════════════════════════════════════
# APPENDIX 3 — Multi-Pilot Operations Except Complex
# ═══════════════════════════════════════════════════════════════════════

_APP3_SPLIT = SplitDutyRules(
    night_overlap_gate=True,
    night_overlap_grants_increase=True,
    sleeping_min_hours=4.0,
    sleeping_extension_type="fixed",
    sleeping_fixed_extension=4.0,
    sleeping_cap_hours=16.0,
    resting_min_hours=2.0,
    resting_extension_pct=0.5,
    resting_max_extension=2.0,
    post_split_max_hours=6.0,
    night_overlap_window=(_hm(23), _hm(5, 29)),
    night_overlap_min_sleeping=7.0,
    night_overlap_cap_hours=16.0,
    night_overlap_credit_reduction=True,
    split_duty_odp_credit_hours=2.0,
)

APP3 = AppendixFdpConfig(
    appendix="3",
    tables={
        "default": FdpTable(
            table_id="Table 2.1",
            lookup_key="local_time_and_sectors",
            rows=[
                FdpTableRow(_APP2_TIME_BANDS_7[0], {"1-3": 10, "4": 9.5, "5": 9, "6": 8.5, "7": 8, "8+": 7.5}),
                FdpTableRow(_APP2_TIME_BANDS_7[1], {"1-3": 11, "4": 10.5, "5": 10, "6": 9.5, "7": 9, "8+": 8.5}),
                FdpTableRow(_APP2_TIME_BANDS_7[2], {"1-3": 12, "4": 11.5, "5": 11, "6": 10.5, "7": 10, "8+": 9.5}),
                FdpTableRow(_APP2_TIME_BANDS_7[3], {"1-3": 13, "4": 12.5, "5": 12, "6": 11.5, "7": 11, "8+": 10.5}),
                FdpTableRow(_APP2_TIME_BANDS_7[4], {"1-3": 12, "4": 11.5, "5": 11, "6": 10.5, "7": 10, "8+": 9.5}),
                FdpTableRow(_APP2_TIME_BANDS_7[5], {"1-3": 11, "4": 10.5, "5": 10, "6": 9.5, "7": 9, "8+": 8.5}),
                FdpTableRow(_APP2_TIME_BANDS_7[6], {"1-3": 10, "4": 9.5, "5": 9, "6": 8.5, "7": 8, "8+": 7.5}),
            ],
            flight_time_limit_hours=10.5,
            notes="Uses local time (not acclimatised time). No augmented crew provisions.",
        ),
    },
    split_duty=_APP3_SPLIT,
    wocl_early_start=True,
    max_extension_hours=1.0,
    extensions=ExtensionRules(
        unforeseen_hours_multi_pilot=1.0,
        unforeseen_hours_single_pilot=1.0,
        clause_unforeseen="§5.3(a)",
        caller_must_verify=(
            ("§5.4", "The PIC consulted each FCM and is satisfied each considers "
                     "himself or herself fit for the extension"),
        ),
    ),
    early_starts=EarlyStartRules(
        available=True,
        max_consecutive=3,
        clause_limit="§11.1",
        clause_relief="§11.3",
        clause_wocl_limit="§11.2",
    ),
    clause_split_sleeping="§3.1",
    clause_split_resting="§3.3",
    clause_split_night_overlap="§3.4",
)


# ═══════════════════════════════════════════════════════════════════════
# APPENDIX 4 — Any Operations
# ═══════════════════════════════════════════════════════════════════════

_APP4_SPLIT = SplitDutyRules(
    night_overlap_gate=True,
    night_overlap_grants_increase=True,
    sleeping_min_hours=4.0,
    sleeping_extension_type="fixed",
    sleeping_fixed_extension=4.0,
    sleeping_cap_hours=15.0,
    resting_min_hours=2.0,
    resting_extension_pct=0.5,
    resting_max_extension=2.0,
    post_split_max_hours=5.0,
    night_overlap_window=(_hm(23), _hm(5, 29)),
    night_overlap_min_sleeping=7.0,
    night_overlap_cap_hours=15.0,
    night_overlap_credit_reduction=True,
    split_duty_odp_credit_hours=2.0,
)

APP4 = AppendixFdpConfig(
    appendix="4",
    tables={
        "default": FdpTable(
            table_id="Table 2.1",
            lookup_key="local_time",
            rows=[
                FdpTableRow(TimeBand(_hm(5), _hm(5, 59), "0500-0559"), {"all": 9.0}),
                FdpTableRow(TimeBand(_hm(6), _hm(7, 59), "0600-0759"), {"all": 10.0}),
                FdpTableRow(TimeBand(_hm(8), _hm(10, 59), "0800-1059"), {"all": 11.0}),
                FdpTableRow(TimeBand(_hm(11), _hm(13, 59), "1100-1359"), {"all": 10.0}),
                FdpTableRow(TimeBand(_hm(14), _hm(22, 59), "1400-2259"), {"all": 9.0}),
                FdpTableRow(TimeBand(_hm(23), _hm(4, 59), "2300-0459"), {"all": 8.0}),
            ],
            notes="Single FDP value per time band. No sector variation.",
        ),
    },
    split_duty=_APP4_SPLIT,
    wocl_early_start=True,
    max_extension_hours=1.0,
    extensions=ExtensionRules(
        unforeseen_hours_multi_pilot=1.0,
        unforeseen_hours_single_pilot=1.0,
        clause_unforeseen="§5.3",
        caller_must_verify=(
            ("§5.4", "The PIC is satisfied that he or she is fit for the extension"),
        ),
    ),
    early_starts=EarlyStartRules(
        available=True,
        max_consecutive=3,
        clause_limit="§11.1",
        clause_relief="§11.3",
        clause_wocl_limit="§11.2",
    ),
    clause_split_sleeping="§3.1",
    clause_split_resting="§3.3",
    clause_split_night_overlap="§3.4",
)


# ═══════════════════════════════════════════════════════════════════════
# APPENDIX 4A — Balloon Operations
# ═══════════════════════════════════════════════════════════════════════

_APP4A_SPLIT = SplitDutyRules(
    night_overlap_gate=True,
    night_overlap_grants_increase=False,
    sleeping_min_hours=4.0,
    sleeping_extension_type="duration",
    sleeping_fixed_extension=0.0,
    sleeping_cap_hours=15.0,
    resting_min_hours=99.0,   # no resting provision
    resting_extension_pct=0.0,
    resting_max_extension=0.0,
    post_split_max_hours=5.0,
    night_overlap_window=(_hm(21), _hm(3, 29)),  # 2100-0329 for balloons
    night_overlap_min_sleeping=7.0,
    night_overlap_cap_hours=15.0,
    night_overlap_credit_reduction=True,
    split_duty_odp_credit_hours=2.0,
)

APP4A = AppendixFdpConfig(
    appendix="4A",
    tables={
        "default": FdpTable(
            table_id="Clause 2",
            lookup_key="split_duty_status",
            rows=[
                FdpTableRow(TimeBand(0, 0, "no_split"), {"all": 6.0}),
                FdpTableRow(TimeBand(0, 0, "with_split"), {"all": 10.0}),
            ],
            notes="6h without split duty, up to 10h with >=4h split duty rest. Cannot continue beyond 6h without starting rest.",
        ),
    },
    split_duty=_APP4A_SPLIT,
    max_extension_hours=0.0,  # no extension provision
    extensions=ExtensionRules(available=False),
    clause_split_sleeping="§3.1",
    clause_split_night_overlap="§3.3",
)


# ═══════════════════════════════════════════════════════════════════════
# APPENDIX 4B — Medical Transport & Emergency Service Operations
# ═══════════════════════════════════════════════════════════════════════

_APP4B_TIME_BANDS = [
    TimeBand(_hm(5), _hm(5, 59), "0500-0559"),
    TimeBand(_hm(6), _hm(6, 59), "0600-0659"),
    TimeBand(_hm(7), _hm(11, 59), "0700-1159"),
    TimeBand(_hm(12), _hm(14, 59), "1200-1459"),
    TimeBand(_hm(15), _hm(15, 59), "1500-1559"),
    TimeBand(_hm(16), _hm(4, 59), "1600-0459"),
]

_APP4B_SPLIT = SplitDutyRules(
    post_split_max_from_table=True,   # §2.2
    sleeping_min_hours=2.0,
    sleeping_extension_type="duration",
    sleeping_fixed_extension=0.0,
    sleeping_cap_hours=16.0,
    resting_min_hours=2.0,
    resting_extension_pct=0.5,
    resting_max_extension=2.0,
    post_split_max_hours=99.0,  # post-split limited to table value for start time
    night_overlap_window=(_hm(23), _hm(5, 29)),
    night_overlap_min_sleeping=10.0,  # 10h sleeping covering local night = full ODP
    night_overlap_cap_hours=16.0,
    night_overlap_credit_reduction=False,
    split_duty_odp_credit_hours=0.0,  # 50% of rest duration instead
)

APP4B = AppendixFdpConfig(
    appendix="4B",
    tables={
        "default": FdpTable(
            table_id="Table 1.1",
            lookup_key="local_time_and_crew_type",
            rows=[
                FdpTableRow(_APP4B_TIME_BANDS[0], {"single_pilot": 11, "multi_1_2": 12, "multi_3+": 12}),
                FdpTableRow(_APP4B_TIME_BANDS[1], {"single_pilot": 11.5, "multi_1_2": 13, "multi_3+": 12.5}),
                FdpTableRow(_APP4B_TIME_BANDS[2], {"single_pilot": 12, "multi_1_2": 14, "multi_3+": 13}),
                FdpTableRow(_APP4B_TIME_BANDS[3], {"single_pilot": 11, "multi_1_2": 13, "multi_3+": 12}),
                FdpTableRow(_APP4B_TIME_BANDS[4], {"single_pilot": 10.5, "multi_1_2": 12, "multi_3+": 11.5}),
                FdpTableRow(_APP4B_TIME_BANDS[5], {"single_pilot": 10, "multi_1_2": 11, "multi_3+": 11}),
            ],
            notes="Lookup by local time and crew type (single-pilot, multi-pilot 1-2 sectors, multi-pilot 3+ sectors).",
        ),
    },
    split_duty=_APP4B_SPLIT,
    increased_fdp=True,
    # Clause 3 is titled "Extensions"; see ExtensionRules below. The scalar
    # is retained for backward compatibility and reports the unforeseen
    # multi-pilot figure.
    max_extension_hours=2.0,
    extensions=ExtensionRules(
        unforeseen_hours_multi_pilot=2.0,
        unforeseen_hours_single_pilot=1.0,
        # §3.1(b) only — an extension off a split-duty-increased limit.
        unforeseen_ceiling_after_split_duty_hours=16.0,
        # §3.1(a) states no explicit ceiling.
        unforeseen_ceiling_hours=None,
        clause_unforeseen="§3.1",
        urgent_available=True,
        urgent_hours=4.0,
        urgent_ceiling_hours=16.0,   # §3.2(c) and §3.2(d) both
        clause_urgent="§3.2",
        clause_cumulative_crosscheck="§3.6",
        caller_must_verify=(
            ("§3.2(a)", "The AOC holder has urgent operations procedures in the "
                        "operations manual"),
            ("§3.2(b)", "The operation is deemed urgent in accordance with that "
                        "manual"),
            ("§3.3", "The PIC of a multi-pilot operation consulted each FCM and "
                     "is satisfied each considers himself or herself fit"),
        ),
    ),
    clause_split_sleeping="§2.1",
    clause_split_resting="§2.4",
)


# ═══════════════════════════════════════════════════════════════════════
# APPENDIX 5 — Aerial Work & Associated Flight Training
# ═══════════════════════════════════════════════════════════════════════

_APP5_SPLIT = SplitDutyRules(
    sleeping_min_hours=3.0,
    sleeping_extension_type="duration",
    sleeping_fixed_extension=0.0,
    sleeping_cap_hours=99.0,  # no explicit cap stated; table + rest duration
    resting_min_hours=2.0,
    resting_extension_pct=0.5,
    resting_max_extension=2.0,
    post_split_max_hours=6.0,
    night_overlap_window=(_hm(23), _hm(5, 29)),
    night_overlap_min_sleeping=7.0,
    night_overlap_cap_hours=99.0,
    night_overlap_credit_reduction=False,
    split_duty_odp_credit_hours=0.0,
)

APP5 = AppendixFdpConfig(
    appendix="5",
    tables={
        "default": FdpTable(
            table_id="Table 1.1",
            lookup_key="local_time_and_crew_type",
            rows=[
                FdpTableRow(_APP4B_TIME_BANDS[0], {"single_pilot": 11, "multi_1_2": 12, "multi_3+": 12}),
                FdpTableRow(_APP4B_TIME_BANDS[1], {"single_pilot": 11.5, "multi_1_2": 13, "multi_3+": 12.5}),
                FdpTableRow(_APP4B_TIME_BANDS[2], {"single_pilot": 12, "multi_1_2": 14, "multi_3+": 13}),
                FdpTableRow(_APP4B_TIME_BANDS[3], {"single_pilot": 11, "multi_1_2": 13, "multi_3+": 12}),
                FdpTableRow(_APP4B_TIME_BANDS[4], {"single_pilot": 10.5, "multi_1_2": 12, "multi_3+": 11.5}),
                FdpTableRow(_APP4B_TIME_BANDS[5], {"single_pilot": 10, "multi_1_2": 11, "multi_3+": 11}),
            ],
            notes="Same table structure as Appendix 4B. Lookup by local time and crew type.",
        ),
    },
    split_duty=_APP5_SPLIT,
    increased_fdp=True,
    # Appendix 5 clause 3 is titled "Extensions": §3.1 grants up to 2 hours.
    # This was 0.0, which produced the same false "does not permit FDP
    # extensions" message as Appendix 4B. Found during Phase 3; App 5 is in
    # the spec's untested-areas list.
    max_extension_hours=2.0,
    extensions=ExtensionRules(
        unforeseen_hours_multi_pilot=2.0,
        unforeseen_hours_single_pilot=2.0,
        clause_unforeseen="§3.1",
        caller_must_verify=(
            ("§3.2", "The PIC of a multi-pilot operation consulted each FCM and "
                     "is satisfied each considers himself or herself fit"),
        ),
    ),
    clause_split_sleeping="§2.1",
    clause_split_resting="§2.2",
)


# ═══════════════════════════════════════════════════════════════════════
# APPENDIX 5A — Daylight Aerial Work
# ═══════════════════════════════════════════════════════════════════════

_APP5A_SPLIT = SplitDutyRules(
    sleeping_min_hours=99.0,
    sleeping_extension_type="fixed",
    sleeping_fixed_extension=0.0,
    sleeping_cap_hours=14.0,
    resting_min_hours=99.0,
    resting_extension_pct=0.0,
    resting_max_extension=0.0,
    post_split_max_hours=14.0,
    split_duty_odp_credit_hours=0.0,
    available=False,
)

APP5A = AppendixFdpConfig(
    appendix="5A",
    tables={
        "default": FdpTable(
            table_id="Clause 2",
            lookup_key="daylight_window",
            rows=[
                FdpTableRow(TimeBand(0, 0, "daylight"), {"all": 14.0}),
            ],
            notes=(
                "Max 14h per day. Must start <=30min before morning civil twilight "
                "and end by evening civil twilight. Extensible by up to 1h (FCM discretion)."
            ),
        ),
    },
    split_duty=_APP5A_SPLIT,
    max_extension_hours=1.0,
    extensions=ExtensionRules(
        unforeseen_hours_multi_pilot=1.0,
        unforeseen_hours_single_pilot=1.0,
        clause_unforeseen="§3.1",
        caller_must_verify=(
            ("§3.1", "The FCM considers himself or herself fit for the extension"),
            ("§3.2", "The FDP is not extended beyond the end of evening civil "
                     "twilight, unless necessary to complete the duties "
                     "associated with the last daylight flight"),
        ),
    ),
)


# ═══════════════════════════════════════════════════════════════════════
# APPENDIX 6 — Flight Training
# ═══════════════════════════════════════════════════════════════════════

_APP6_SPLIT = SplitDutyRules(
    night_overlap_gate=True,
    night_overlap_grants_increase=True,
    sleeping_min_hours=4.0,
    sleeping_extension_type="fixed",
    sleeping_fixed_extension=4.0,
    sleeping_cap_hours=15.0,
    resting_min_hours=2.0,
    resting_extension_pct=0.5,
    resting_max_extension=2.0,
    post_split_max_hours=5.0,
    night_overlap_window=(_hm(23), _hm(5, 29)),
    night_overlap_min_sleeping=7.0,
    night_overlap_cap_hours=15.0,
    night_overlap_credit_reduction=True,
    split_duty_odp_credit_hours=2.0,
)

APP6 = AppendixFdpConfig(
    appendix="6",
    tables={
        "default": FdpTable(
            table_id="Table 2.1",
            lookup_key="local_time",
            rows=[
                FdpTableRow(TimeBand(_hm(5), _hm(5, 59), "0500-0559"), {"all": 9.0}),
                FdpTableRow(TimeBand(_hm(6), _hm(6, 59), "0600-0659"), {"all": 10.0}),
                FdpTableRow(TimeBand(_hm(7), _hm(7, 59), "0700-0759"), {"all": 10.0}),
                FdpTableRow(TimeBand(_hm(8), _hm(10, 59), "0800-1059"), {"all": 11.0}),
                FdpTableRow(TimeBand(_hm(11), _hm(13, 59), "1100-1359"), {"all": 10.0}),
                FdpTableRow(TimeBand(_hm(14), _hm(22, 59), "1400-2259"), {"all": 9.0}),
                FdpTableRow(TimeBand(_hm(23), _hm(4, 59), "2300-0459"), {"all": 8.0}),
            ],
            flight_time_limit_hours=7.0,
            notes="Flight time limit 7h per FDP.",
        ),
    },
    split_duty=_APP6_SPLIT,
    wocl_early_start=True,
    max_extension_hours=1.0,
    extensions=ExtensionRules(
        unforeseen_hours_multi_pilot=1.0,
        unforeseen_hours_single_pilot=1.0,
        clause_unforeseen="§4.3",
        caller_must_verify=(
            ("§4.4", "The PIC consulted each FCM and is satisfied each considers "
                     "himself or herself fit for the extension"),
        ),
    ),
    early_starts=EarlyStartRules(
        available=True,
        max_consecutive=3,
        clause_limit="§10.1",
        clause_relief="§10.3",
        clause_wocl_limit="§10.2",
    ),
    clause_split_sleeping="§3.1",
    clause_split_resting="§3.3",
    clause_split_night_overlap="§3.4",
)


# ═══════════════════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════════════════

VALID_APPENDICES = {"1", "2", "3", "4", "4A", "4B", "5", "5A", "6"}

FDP_CONFIGS: dict[str, AppendixFdpConfig] = {
    "1": APP1,
    "2": APP2,
    "3": APP3,
    "4": APP4,
    "4A": APP4A,
    "4B": APP4B,
    "5": APP5,
    "5A": APP5A,
    "6": APP6,
}


def get_fdp_config(appendix: str) -> Optional[AppendixFdpConfig]:
    """Return the FDP configuration for a given appendix, or None if invalid."""
    return FDP_CONFIGS.get(appendix.upper())
