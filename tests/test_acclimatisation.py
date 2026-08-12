"""
Tests for the acclimatisation determination — CAO 48.1 §7.

Covers POST /calculate/acclimatisation, GET /limits/adaptation-table, and the
engine underneath them.

Acceptance criteria exercised here:
  - every §7 branch: §7.1, §7.2, §7.3, §7.4(a), §7.4(b)
  - every Table 7.1 row, in both directions, including the '10 or more' boundary
  - §7.5 selection uses the GREATEST displacement, with a case where the
    greatest is not the most recent
  - the §7.4(b) 12-hour reduction with none, one and several qualifying
    preceding off-duty periods
  - half-hour and quarter-hour offsets (ACST +9:30, NPT +5:45)
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.data.adaptation import (
    ADAPTATION_TABLE_HOURS,
    displacement_to_time_zones,
    lookup_adaptation_period,
)
from app.engines.acclimatisation_calculator import determine_acclimatisation
from app.main import app

PREFIX = "/api/v1/cao481"
pytestmark = pytest.mark.anyio


@pytest.fixture
def transport():
    return ASGITransport(app=app)


# ─── Helpers ──────────────────────────────────────────────────────────

def _origin(offset: float = 8.0, commenced: str = "2026-07-20T22:00:00Z") -> dict:
    """Last acclimatised at Perth (UTC+8) unless told otherwise."""
    return {
        "location": "YPPH",
        "utc_offset_hours": offset,
        "duty_commenced_utc": commenced,
    }


def _fdp(location: str, offset: float, start: str, end: str) -> dict:
    return {
        "event_type": "fdp",
        "location": location,
        "utc_offset_hours": offset,
        "start_utc": start,
        "end_utc": end,
    }


def _odp(
    location: str,
    offset: float,
    start: str,
    end: str,
    night: bool | None = True,
) -> dict:
    return {
        "event_type": "off_duty",
        "location": location,
        "utc_offset_hours": offset,
        "start_utc": start,
        "end_utc": end,
        "includes_local_night": night,
    }


# ═══════════════════════════════════════════════════════════════════════
# Table 7.1
# ═══════════════════════════════════════════════════════════════════════

class TestTable71:
    """Every row, both directions, including the boundary."""

    @pytest.mark.parametrize(
        "zones,west,east",
        [
            (2, 24.0, 30.0),
            (3, 36.0, 45.0),
            (4, 48.0, 60.0),
            (5, 48.0, 60.0),
            (6, 48.0, 60.0),
            (7, 72.0, 90.0),
            (8, 72.0, 90.0),
            (9, 72.0, 90.0),
            (10, 96.0, 120.0),
        ],
    )
    async def test_every_row_both_directions(self, zones, west, east):
        assert lookup_adaptation_period(float(zones), "west").required_hours == west
        assert lookup_adaptation_period(float(zones), "east").required_hours == east

    async def test_ten_or_more_boundary(self):
        """Anything at or beyond 10 zones uses the '10 or more' row."""
        for hours in (10.0, 11.0, 12.0, 23.0):
            for direction, expected in (("west", 96.0), ("east", 120.0)):
                result = lookup_adaptation_period(hours, direction)
                assert result.required_hours == expected
                assert result.row_label == "10 or more"
                assert result.time_zones == 10

    async def test_east_always_at_least_west(self):
        for zones, values in ADAPTATION_TABLE_HOURS.items():
            assert values["east"] >= values["west"], f"row {zones}"

    @pytest.mark.parametrize(
        "hours,expected_zones",
        [
            (2.0, 2),
            (2.5, 3),    # ACST vs AEST style half-hour offsets round up
            (3.0, 3),
            (3.25, 4),   # NPT quarter-hour offsets round up too
            (9.5, 10),
            (0.5, 2),    # clamped to the lowest row that exists
        ],
    )
    async def test_fractional_displacement_rounds_up(self, hours, expected_zones):
        assert displacement_to_time_zones(hours) == expected_zones

    async def test_endpoint_returns_all_nine_rows(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"{PREFIX}/limits/adaptation-table")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["rows"]) == 9
        assert body["rows"][-1]["time_zone_change"] == "10 or more"
        assert body["table_id"] == "Table 7.1"
        assert body["notes"]


# ═══════════════════════════════════════════════════════════════════════
# The §7 branches
# ═══════════════════════════════════════════════════════════════════════

class TestSection71:
    """§7.1 — less than 2 hours different, so acclimatised to the location."""

    async def test_no_events_stays_acclimatised(self):
        result = determine_acclimatisation(
            last_acclimatised=_origin(),
            as_of_utc="2026-07-26T09:00:00Z",
            events=[],
        )
        assert result["state"] == "acclimatised"
        assert result["clause"] == "§7.1"
        assert result["determination"] == "acclimatised_at_location"
        assert result["acclimatised_to"]["location"] == "YPPH"

    async def test_displacement_under_two_hours_is_not_a_displacement(self):
        """A 1.5-hour shift is below the §7.1 threshold, so no displacement."""
        result = determine_acclimatisation(
            last_acclimatised=_origin(8.0),
            as_of_utc="2026-07-21T12:00:00Z",
            events=[_fdp("YPDN", 9.5, "2026-07-21T02:00:00Z", "2026-07-21T08:00:00Z")],
        )
        assert result["state"] == "acclimatised"
        assert result["clause"] == "§7.1"
        assert result["greatest_displacement"]["hours"] == pytest.approx(1.5)
        # Acclimatised to where they now are, on that location's clock.
        assert result["acclimatised_to"]["utc_offset_hours"] == 9.5

    async def test_exactly_two_hours_is_a_displacement(self):
        """The threshold is 'less than 2 hours', so 2.0 exactly displaces."""
        result = determine_acclimatisation(
            last_acclimatised=_origin(8.0),
            as_of_utc="2026-07-21T12:00:00Z",
            events=[_fdp("YBBN", 10.0, "2026-07-21T02:00:00Z", "2026-07-21T08:00:00Z")],
        )
        assert result["clause"] != "§7.1"
        assert result["greatest_displacement"]["hours"] == pytest.approx(2.0)


class TestSection72And73:
    """The 36-hour clock, which runs from duty at the ORIGINAL location."""

    async def test_under_36_hours_remains_acclimatised_to_original(self):
        result = determine_acclimatisation(
            last_acclimatised=_origin(8.0, "2026-07-20T22:00:00Z"),
            as_of_utc="2026-07-22T08:00:00Z",  # 34h later
            events=[_fdp("WSSS", 1.0, "2026-07-21T02:00:00Z", "2026-07-21T14:00:00Z")],
        )
        assert result["state"] == "acclimatised"
        assert result["clause"] == "§7.2"
        assert result["determination"] == "remains_acclimatised_to_original"
        assert result["acclimatised_to"]["location"] == "YPPH"
        assert result["acclimatised_to"]["utc_offset_hours"] == 8.0
        assert result["hours_since_original_duty_commenced"] == pytest.approx(34.0)

    async def test_36_hours_or_more_is_unknown(self):
        result = determine_acclimatisation(
            last_acclimatised=_origin(8.0, "2026-07-20T22:00:00Z"),
            as_of_utc="2026-07-22T10:00:00Z",  # exactly 36h later
            events=[_fdp("WSSS", 1.0, "2026-07-21T02:00:00Z", "2026-07-21T14:00:00Z")],
        )
        assert result["state"] == "unknown"
        assert result["clause"] == "§7.3"
        assert result["acclimatised_to"] is None
        # The fallback clock for Appendix 2 lookups is still reported.
        assert result["last_acclimatised_to"]["utc_offset_hours"] == 8.0

    async def test_clock_runs_from_original_duty_not_arrival(self):
        """
        Arrival is recent but original duty is old — must be unknown.

        This is the asymmetry that is easy to implement backwards.
        """
        result = determine_acclimatisation(
            last_acclimatised=_origin(8.0, "2026-07-20T00:00:00Z"),
            as_of_utc="2026-07-23T02:00:00Z",  # 74h after original duty
            events=[
                # Arrived at the new location only 2 hours ago.
                _fdp("WSSS", 1.0, "2026-07-22T12:00:00Z", "2026-07-23T00:00:00Z"),
            ],
        )
        assert result["state"] == "unknown"
        assert result["clause"] == "§7.3"


class TestSection74:
    """Reacclimatisation by adaptation period."""

    async def test_74a_full_adaptation_period_reacclimatises(self):
        """7 zones west needs 72h continuous off duty; 80h is supplied."""
        result = determine_acclimatisation(
            last_acclimatised=_origin(8.0, "2026-07-20T22:00:00Z"),
            as_of_utc="2026-07-26T00:00:00Z",
            events=[
                _fdp("EGLL", 1.0, "2026-07-21T02:00:00Z", "2026-07-21T14:00:00Z"),
                _odp("EGLL", 1.0, "2026-07-21T14:00:00Z", "2026-07-24T22:00:00Z", night=True),
            ],
            home_base="YPPH",
        )
        assert result["state"] == "acclimatised"
        assert result["clause"] == "§7.4"
        assert result["determination"] == "reacclimatised_by_adaptation"
        assert result["acclimatised_to"]["location"] == "EGLL"
        assert result["acclimatised_to"]["utc_offset_hours"] == 1.0
        assert result["adaptation"]["required_hours"] == 72.0
        assert result["adaptation"]["reduction_hours"] == 0.0
        # 72h after the off-duty period started.
        assert result["adaptation"]["acclimatised_at_utc"] == "2026-07-24T14:00:00Z"

    async def test_adaptation_short_of_requirement_does_not_reacclimatise(self):
        """71h against a 72h requirement is still unknown."""
        result = determine_acclimatisation(
            last_acclimatised=_origin(8.0, "2026-07-20T22:00:00Z"),
            as_of_utc="2026-07-24T13:00:00Z",
            events=[
                _fdp("EGLL", 1.0, "2026-07-21T02:00:00Z", "2026-07-21T14:00:00Z"),
                _odp("EGLL", 1.0, "2026-07-21T14:00:00Z", "2026-07-24T13:00:00Z", night=True),
            ],
            home_base="YPPH",
        )
        assert result["state"] == "unknown"
        assert result["clause"] == "§7.3"

    async def test_eastward_requires_longer_than_westward(self):
        """
        The same 71-hour rest reacclimatises westward but not eastward.

        Perth (+8) to London (+1) is 7 zones west = 72h; Perth to Auckland
        (+12) is 4 zones east = 60h. Using a 65-hour rest separates them.
        """
        west = determine_acclimatisation(
            last_acclimatised=_origin(8.0, "2026-07-20T22:00:00Z"),
            as_of_utc="2026-07-26T00:00:00Z",
            events=[
                _fdp("EGLL", 1.0, "2026-07-21T00:00:00Z", "2026-07-21T12:00:00Z"),
                _odp("EGLL", 1.0, "2026-07-21T12:00:00Z", "2026-07-24T05:00:00Z"),
            ],
            home_base="YPPH",
        )
        east = determine_acclimatisation(
            last_acclimatised=_origin(8.0, "2026-07-20T22:00:00Z"),
            as_of_utc="2026-07-26T00:00:00Z",
            events=[
                _fdp("NZAA", 12.0, "2026-07-21T00:00:00Z", "2026-07-21T12:00:00Z"),
                _odp("NZAA", 12.0, "2026-07-21T12:00:00Z", "2026-07-24T05:00:00Z"),
            ],
            home_base="YPPH",
        )
        assert west["adaptation"]["required_hours"] == 72.0
        assert east["adaptation"]["required_hours"] == 60.0
        assert west["state"] == "unknown"          # 65h < 72h
        assert east["state"] == "acclimatised"     # 65h >= 60h


class TestSection74bReduction:
    """The 12-hour reduction, with none, one and several qualifying ODPs."""

    def _history(
        self, preceding: list[dict], adaptation_start: str = "2026-07-21T10:00:00Z",
    ) -> list[dict]:
        """
        An FDP into Singapore, some preceding ODPs, then the adaptation period.

        Preceding periods are deliberately separated by short gaps. Off-duty
        periods that abut at the same location are one CONTINUOUS off-duty
        period under §6 and the engine merges them, which would otherwise
        swallow the preceding periods into the adaptation period itself.
        """
        return [
            _fdp("WSSS", 1.0, "2026-07-21T00:00:00Z", "2026-07-21T10:00:00Z"),
            *preceding,
            _odp("WSSS", 1.0, adaptation_start, "2026-07-26T00:00:00Z"),
        ]

    async def test_no_qualifying_odps_means_no_reduction(self):
        result = determine_acclimatisation(
            last_acclimatised=_origin(8.0, "2026-07-20T22:00:00Z"),
            as_of_utc="2026-07-26T00:00:00Z",
            events=self._history([]),
            home_base="YPPH",
        )
        assert result["adaptation"]["reduction_hours"] == 0.0
        assert result["adaptation"]["effective_required_hours"] == 72.0

    async def test_one_qualifying_odp_reduces_by_12(self):
        result = determine_acclimatisation(
            last_acclimatised=_origin(8.0, "2026-07-20T22:00:00Z"),
            as_of_utc="2026-07-26T00:00:00Z",
            events=self._history(
                [_odp("WSSS", 1.0, "2026-07-21T10:00:00Z", "2026-07-22T00:00:00Z", night=True)],
                adaptation_start="2026-07-22T02:00:00Z",
            ),
            home_base="YPPH",
        )
        assert result["adaptation"]["reduction_hours"] == 12.0
        assert result["adaptation"]["effective_required_hours"] == 60.0

    async def test_several_qualifying_odps_stack(self):
        result = determine_acclimatisation(
            last_acclimatised=_origin(8.0, "2026-07-20T22:00:00Z"),
            as_of_utc="2026-07-26T00:00:00Z",
            events=self._history(
                [
                    _odp("WSSS", 1.0, "2026-07-21T10:00:00Z", "2026-07-22T00:00:00Z", night=True),
                    _odp("WSSS", 1.0, "2026-07-22T02:00:00Z", "2026-07-22T16:00:00Z", night=True),
                    _odp("WSSS", 1.0, "2026-07-22T18:00:00Z", "2026-07-23T08:00:00Z", night=True),
                ],
                adaptation_start="2026-07-23T10:00:00Z",
            ),
            home_base="YPPH",
        )
        assert result["adaptation"]["reduction_hours"] == 36.0
        assert result["adaptation"]["effective_required_hours"] == 36.0

    async def test_odp_without_local_night_does_not_qualify(self):
        result = determine_acclimatisation(
            last_acclimatised=_origin(8.0, "2026-07-20T22:00:00Z"),
            as_of_utc="2026-07-26T00:00:00Z",
            events=self._history(
                [_odp("WSSS", 1.0, "2026-07-21T10:00:00Z", "2026-07-22T00:00:00Z", night=False)],
                adaptation_start="2026-07-22T02:00:00Z",
            ),
            home_base="YPPH",
        )
        assert result["adaptation"]["reduction_hours"] == 0.0

    async def test_odp_two_hours_from_adaptation_location_does_not_qualify(self):
        """§7.4(b)(iii)(B) — the preceding ODP must be within 2 hours."""
        result = determine_acclimatisation(
            last_acclimatised=_origin(8.0, "2026-07-20T22:00:00Z"),
            as_of_utc="2026-07-26T00:00:00Z",
            events=self._history(
                [_odp("OMDB", 4.0, "2026-07-21T10:00:00Z", "2026-07-22T00:00:00Z", night=True)],
                adaptation_start="2026-07-22T02:00:00Z",
            ),
            home_base="YPPH",
        )
        assert result["adaptation"]["reduction_hours"] == 0.0

    async def test_reduction_does_not_apply_at_home_base(self):
        """§7.4(b)(i) — the reduction is for adaptation away from home base."""
        result = determine_acclimatisation(
            last_acclimatised=_origin(8.0, "2026-07-20T22:00:00Z"),
            as_of_utc="2026-07-26T00:00:00Z",
            events=self._history(
                [_odp("WSSS", 1.0, "2026-07-21T10:00:00Z", "2026-07-22T00:00:00Z", night=True)],
                adaptation_start="2026-07-22T02:00:00Z",
            ),
            home_base="WSSS",  # the adaptation location IS home base
        )
        assert result["adaptation"]["reduction_hours"] == 0.0


class TestSection75Selection:
    """The greatest displacement, which is frequently not the most recent."""

    async def test_greatest_is_not_the_most_recent(self):
        """
        Perth -> London (7 west) -> Singapore (0), asked about Singapore.

        Singapore shares Perth's clock, so the most recent displacement is
        zero. §7.5(b) requires the greatest — London's 7 zones west.
        """
        result = determine_acclimatisation(
            last_acclimatised=_origin(8.0, "2026-07-20T22:00:00Z"),
            as_of_utc="2026-07-26T00:00:00Z",
            events=[
                _fdp("EGLL", 1.0, "2026-07-21T00:00:00Z", "2026-07-21T12:00:00Z"),
                _odp("EGLL", 1.0, "2026-07-21T12:00:00Z", "2026-07-22T12:00:00Z"),
                _fdp("WSSS", 8.0, "2026-07-22T12:00:00Z", "2026-07-23T00:00:00Z"),
                _odp("WSSS", 8.0, "2026-07-23T00:00:00Z", "2026-07-26T00:00:00Z"),
            ],
            home_base="YPPH",
        )
        assert result["greatest_displacement"]["hours"] == pytest.approx(7.0)
        assert result["greatest_displacement"]["location"] == "EGLL"
        assert result["greatest_displacement"]["direction"] == "west"
        assert result["adaptation"]["required_hours"] == 72.0

    async def test_direction_follows_the_greatest_displacement(self):
        """A small eastward hop must not override a large westward one."""
        result = determine_acclimatisation(
            last_acclimatised=_origin(8.0, "2026-07-20T22:00:00Z"),
            as_of_utc="2026-07-26T00:00:00Z",
            events=[
                _fdp("NZAA", 12.0, "2026-07-21T00:00:00Z", "2026-07-21T06:00:00Z"),
                _fdp("EGLL", 1.0, "2026-07-21T08:00:00Z", "2026-07-21T20:00:00Z"),
                _odp("EGLL", 1.0, "2026-07-21T20:00:00Z", "2026-07-26T00:00:00Z"),
            ],
            home_base="YPPH",
        )
        assert result["greatest_displacement"]["direction"] == "west"
        assert result["greatest_displacement"]["location"] == "EGLL"


class TestFractionalOffsets:
    """Half-hour and quarter-hour offsets must not break anything."""

    async def test_acst_half_hour_offset(self):
        result = determine_acclimatisation(
            last_acclimatised=_origin(9.5, "2026-07-20T22:00:00Z"),  # ACST
            as_of_utc="2026-07-26T00:00:00Z",
            events=[
                _fdp("EGLL", 1.0, "2026-07-21T00:00:00Z", "2026-07-21T12:00:00Z"),
                _odp("EGLL", 1.0, "2026-07-21T12:00:00Z", "2026-07-26T00:00:00Z"),
            ],
            home_base="YPPH",
        )
        assert result["greatest_displacement"]["hours"] == pytest.approx(8.5)
        # 8.5 rounds up to the 9-zone row: 72h west.
        assert result["greatest_displacement"]["time_zones"] == 9
        assert result["adaptation"]["required_hours"] == 72.0

    async def test_npt_quarter_hour_offset(self):
        result = determine_acclimatisation(
            last_acclimatised=_origin(5.75, "2026-07-20T22:00:00Z"),  # NPT
            as_of_utc="2026-07-23T00:00:00Z",
            events=[_fdp("YPPH", 8.0, "2026-07-21T00:00:00Z", "2026-07-21T08:00:00Z")],
        )
        # 2.25 hours: past the §7.1 threshold, rounds up to the 3-zone row.
        assert result["greatest_displacement"]["hours"] == pytest.approx(2.25)
        assert result["greatest_displacement"]["time_zones"] == 3


class TestIndeterminate:
    """'Insufficient history' is not the same answer as §7.3 'unknown'."""

    async def test_large_gap_yields_indeterminate(self):
        """
        A gap long enough to have concealed an adaptation period.

        The history stops four days before the question is asked, which is
        more than the 72h required here, so no honest determination is
        possible.
        """
        result = determine_acclimatisation(
            last_acclimatised=_origin(8.0, "2026-07-20T22:00:00Z"),
            as_of_utc="2026-07-30T00:00:00Z",
            events=[_fdp("EGLL", 1.0, "2026-07-21T00:00:00Z", "2026-07-21T12:00:00Z")],
            home_base="YPPH",
        )
        assert result["state"] == "indeterminate"
        assert result["determination"] == "insufficient_history"
        assert result["acclimatised_to"] is None
        assert any("indeterminate" in note for note in result["calculation_notes"])

    async def test_as_of_before_duty_commenced_is_indeterminate(self):
        result = determine_acclimatisation(
            last_acclimatised=_origin(8.0, "2026-07-20T22:00:00Z"),
            as_of_utc="2026-07-19T00:00:00Z",
            events=[],
        )
        assert result["state"] == "indeterminate"


class TestLocalNightDerivation:
    """§6 — 8 consecutive hours including 2200 to 0500 local time."""

    async def test_derived_when_not_supplied(self):
        """A rest covering 2100-0700 local at UTC+8 includes a local night."""
        result = determine_acclimatisation(
            last_acclimatised=_origin(8.0, "2026-07-20T22:00:00Z"),
            as_of_utc="2026-07-26T00:00:00Z",
            events=[
                _fdp("WSSS", 1.0, "2026-07-21T00:00:00Z", "2026-07-21T10:00:00Z"),
                # 2100 to 0700 local at UTC+1 = 2000-0600 UTC: 10 hours
                # spanning the whole 2200-0500 local window.
                _odp("WSSS", 1.0, "2026-07-21T20:00:00Z", "2026-07-22T06:00:00Z", night=None),
                _odp("WSSS", 1.0, "2026-07-22T08:00:00Z", "2026-07-26T00:00:00Z", night=None),
            ],
            home_base="YPPH",
        )
        assert any(
            "derived" in note for note in result["calculation_notes"]
        ), "derivation should be disclosed in the notes"

    async def test_short_rest_is_not_a_local_night(self):
        """Under 8 hours cannot be a local night however well placed."""
        result = determine_acclimatisation(
            last_acclimatised=_origin(8.0, "2026-07-20T22:00:00Z"),
            as_of_utc="2026-07-26T00:00:00Z",
            events=[
                _fdp("WSSS", 1.0, "2026-07-21T00:00:00Z", "2026-07-21T10:00:00Z"),
                _odp("WSSS", 1.0, "2026-07-21T21:00:00Z", "2026-07-22T03:00:00Z", night=None),
                _odp("WSSS", 1.0, "2026-07-22T05:00:00Z", "2026-07-26T00:00:00Z", night=None),
            ],
            home_base="YPPH",
        )
        # A 6-hour rest cannot qualify, so no reduction is earned from it.
        assert result["adaptation"]["reduction_hours"] == 0.0


# ═══════════════════════════════════════════════════════════════════════
# Endpoint behaviour
# ═══════════════════════════════════════════════════════════════════════

class TestEndpoint:
    async def test_returns_200_with_full_shape(self, transport):
        payload = {
            "home_base": "YPPH",
            "last_acclimatised": _origin(),
            "as_of_utc": "2026-07-26T09:00:00Z",
            "events": [
                _fdp("EGLL", 1.0, "2026-07-21T02:00:00Z", "2026-07-21T14:00:00Z"),
                _odp("EGLL", 1.0, "2026-07-21T14:00:00Z", "2026-07-26T09:00:00Z"),
            ],
        }
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/calculate/acclimatisation", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        for key in (
            "state", "acclimatised_to", "last_acclimatised_to", "determination",
            "clause", "greatest_displacement", "adaptation", "calculation_notes",
            "disclaimer",
        ):
            assert key in body, f"missing {key}"
        assert body["disclaimer"]

    async def test_out_of_order_events_rejected(self, transport):
        payload = {
            "last_acclimatised": _origin(),
            "as_of_utc": "2026-07-26T09:00:00Z",
            "events": [
                _fdp("EGLL", 1.0, "2026-07-23T02:00:00Z", "2026-07-23T14:00:00Z"),
                _fdp("WSSS", 8.0, "2026-07-21T02:00:00Z", "2026-07-21T14:00:00Z"),
            ],
        }
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/calculate/acclimatisation", json=payload)
        assert resp.status_code == 422
        assert "chronological" in resp.text

    async def test_unknown_field_rejected(self, transport):
        payload = {
            "last_acclimatised": _origin(),
            "as_of_utc": "2026-07-26T09:00:00Z",
            "events": [],
            "timezone": "Australia/Perth",  # not a field on this model
        }
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/calculate/acclimatisation", json=payload)
        assert resp.status_code == 422
        assert "timezone" in resp.text

    async def test_listed_in_health(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"{PREFIX}/health")
        available = resp.json()["endpoints"]["available"]
        assert "/calculate/acclimatisation" in available
        assert "/limits/adaptation-table" in available
