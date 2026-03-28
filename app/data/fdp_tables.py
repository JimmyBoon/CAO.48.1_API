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

_APP1_SPLIT = SplitDutyRules(
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
)


# ═══════════════════════════════════════════════════════════════════════
# APPENDIX 3 — Multi-Pilot Operations Except Complex
# ═══════════════════════════════════════════════════════════════════════

_APP3_SPLIT = SplitDutyRules(
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
)


# ═══════════════════════════════════════════════════════════════════════
# APPENDIX 4 — Any Operations
# ═══════════════════════════════════════════════════════════════════════

_APP4_SPLIT = SplitDutyRules(
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
)


# ═══════════════════════════════════════════════════════════════════════
# APPENDIX 4A — Balloon Operations
# ═══════════════════════════════════════════════════════════════════════

_APP4A_SPLIT = SplitDutyRules(
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
    max_extension_hours=0.0,  # urgent ops extension handled separately (+4h)
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
    max_extension_hours=0.0,
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
)


# ═══════════════════════════════════════════════════════════════════════
# APPENDIX 6 — Flight Training
# ═══════════════════════════════════════════════════════════════════════

_APP6_SPLIT = SplitDutyRules(
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
