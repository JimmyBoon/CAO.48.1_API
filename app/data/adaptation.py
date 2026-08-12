"""
Table 7.1 — Adaptation period to become acclimatised.

Source: CAO 48.1 Instrument 2019 (Compilation No. 3, F2021C01239),
subsection 7, Table 7.1.

The table gives the continuous off-duty period required for a flight crew
member to become acclimatised to a new location, indexed by time zone change
and by the direction of travel. Eastward travel requires longer, reflecting
the greater difficulty of phase-advancing the circadian clock.

Two readings of the instrument are encoded here and both are documented on the
endpoint, because §6 defines a `time zone` as a region differing "by 1 hour, or
by part of 1 hour" while Table 7.1 is indexed in whole time zones:

  - the §7.1 "less than 2 hours" test uses the RAW hour difference, so a
    1.5-hour displacement is not a displacement at all; and
  - Table 7.1 row selection ROUNDS UP to the next whole zone, so a 2.5-hour
    displacement selects the 3-zone row.

Both readings are the conservative one in their own context: the first avoids
declaring someone unacclimatised on a sub-2-hour shift, and the second never
under-states the adaptation period. CAAP 48-01 should be consulted if a
definitive interpretation is ever required.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

Direction = Literal["west", "east"]

# ─── Table 7.1 ────────────────────────────────────────────────────────
# Keyed by whole time zones changed. The final key (10) is the "10 or more"
# row — any displacement of 10 zones or greater uses it.
ADAPTATION_TABLE_HOURS: dict[int, dict[Direction, float]] = {
    2:  {"west": 24.0, "east": 30.0},
    3:  {"west": 36.0, "east": 45.0},
    4:  {"west": 48.0, "east": 60.0},
    5:  {"west": 48.0, "east": 60.0},
    6:  {"west": 48.0, "east": 60.0},
    7:  {"west": 72.0, "east": 90.0},
    8:  {"west": 72.0, "east": 90.0},
    9:  {"west": 72.0, "east": 90.0},
    10: {"west": 96.0, "east": 120.0},
}

# The lowest and highest rows present in the table.
MIN_TABLE_ZONES = 2
MAX_TABLE_ZONES = 10

# §7.1 — a location less than this many hours different is not a displacement.
DISPLACEMENT_THRESHOLD_HOURS = 2.0

# §7.2 / §7.3 — hours after commencing a duty period at the original location.
UNKNOWN_STATE_THRESHOLD_HOURS = 36.0

# §7.4(b)(iii) — reduction per qualifying immediately preceding off-duty period.
ADAPTATION_REDUCTION_PER_ODP_HOURS = 12.0


@dataclass(frozen=True)
class AdaptationLookup:
    """The outcome of a Table 7.1 lookup."""

    time_zones: int          # the row actually used (2-10)
    direction: Direction
    required_hours: float
    row_label: str           # e.g. "10 or more"
    rounded_up: bool         # True if a fractional displacement was rounded up


def displacement_to_time_zones(displacement_hours: float) -> int:
    """
    Convert an hours displacement into a whole number of time zones.

    Rounds UP, so 2.5 hours is treated as a 3-zone change. See the module
    docstring for why. Clamped to the range the table covers.

    Parameters
    ----------
    displacement_hours : float
        Absolute difference in local time, in hours. Always non-negative.

    Returns
    -------
    int
        Whole time zones, clamped to 2..10.
    """
    zones = math.ceil(round(abs(displacement_hours), 6))
    return max(MIN_TABLE_ZONES, min(zones, MAX_TABLE_ZONES))


def lookup_adaptation_period(
    displacement_hours: float,
    direction: Direction,
) -> AdaptationLookup:
    """
    Look up the Table 7.1 adaptation period for a displacement and direction.

    Parameters
    ----------
    displacement_hours : float
        The GREATEST displacement determined under §7.5(b), in hours.
    direction : {'west', 'east'}
        The direction in which that greatest displacement occurred, per §7.5(d).

    Returns
    -------
    AdaptationLookup
        The row used and the required continuous off-duty period in hours.
    """
    zones = displacement_to_time_zones(displacement_hours)
    required = ADAPTATION_TABLE_HOURS[zones][direction]
    label = "10 or more" if zones == MAX_TABLE_ZONES else str(zones)
    rounded = abs(displacement_hours - round(displacement_hours)) > 1e-9 or (
        displacement_hours > 0 and zones != round(displacement_hours)
    )
    return AdaptationLookup(
        time_zones=zones,
        direction=direction,
        required_hours=required,
        row_label=label,
        rounded_up=rounded,
    )


def adaptation_table_rows() -> list[dict]:
    """
    Return Table 7.1 as a list of plain rows, for GET /limits/adaptation-table.

    Ordered by time zone change ascending.
    """
    rows = []
    for zones in sorted(ADAPTATION_TABLE_HOURS):
        rows.append(
            {
                "time_zone_change": "10 or more" if zones == MAX_TABLE_ZONES else str(zones),
                "time_zones": zones,
                "west_hours": ADAPTATION_TABLE_HOURS[zones]["west"],
                "east_hours": ADAPTATION_TABLE_HOURS[zones]["east"],
            }
        )
    return rows
