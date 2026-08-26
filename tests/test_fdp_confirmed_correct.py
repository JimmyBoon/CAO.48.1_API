"""
Pinning tests for FDP behaviour the remediation spec §6 lists as confirmed
correct. Written BEFORE Phase 3 touches fdp_calculator.py / fdp_validator.py.

Numbers only, not clause strings — the citations on this path are corrected in
Phase 3 (§3.2 -> §3.3 for resting accommodation, §3.night -> §3.4), the
arithmetic is not.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
BASE = "/api/v1/cao481"


def max_fdp(**overrides):
    body = {
        "appendix": "3",
        "fdp_start_utc": "2026-03-24T02:00:00Z",  # 1000 local at +8
        "local_time_offset_hours": 8,
        "sectors": 2,
    }
    body.update(overrides)
    response = client.post(f"{BASE}/calculate/max-fdp", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def split(duration_hours, accommodation, overlaps=False):
    """
    Build a split-duty rest of the requested length.

    `overlaps_2300_0529` is now DERIVED from the rest period's own timestamps
    (Phase 7), so the window has to genuinely overlap or genuinely not:
    a 1400Z start at +8 is 2200 local and does overlap. Non-overlapping rests
    therefore start 0400Z (1200 local).
    """
    start_h = 14 if overlaps else 4
    end_h = start_h + int(duration_hours)
    end_m = int(round((duration_hours % 1) * 60))
    return {
        "rest_start_utc": f"2026-03-24T{start_h:02d}:00:00Z",
        "rest_end_utc": f"2026-03-24T{end_h:02d}:{end_m:02d}:00Z",
        "accommodation": accommodation,
        "duration_hours": duration_hours,
        "overlaps_2300_0529": overlaps,
    }


class TestTableLookups:
    """
    'Table lookups — flawless.' Boundary probes must keep resolving to the
    same rows: 0659/0700, 1259/1300, the 8+ bucket, half-hour offsets, and
    midnight wrap.
    """

    @pytest.mark.parametrize(
        "utc,offset,expected",
        [
            ("2026-03-23T22:59:00Z", 8, 12.0),   # 0659 local -> 0600-0659 band
            ("2026-03-23T23:00:00Z", 8, 13.0),   # 0700 local -> 0700-1259 band
            ("2026-03-24T04:59:00Z", 8, 13.0),   # 1259 local
            ("2026-03-24T05:00:00Z", 8, 12.0),   # 1300 local -> 1300-1359 band
            ("2026-03-23T16:00:00Z", 8, 10.0),   # 0000 local -> 0000-0459 band
            ("2026-03-24T06:30:00Z", 5.5, 13.0),  # IST +5.5: 1200 local -> 0700-1259
            ("2026-03-24T09:00:00Z", 5.5, 11.0),  # IST +5.5: 1430 local -> 1400-1459
        ],
    )
    def test_time_band_boundaries(self, utc, offset, expected):
        result = max_fdp(fdp_start_utc=utc, local_time_offset_hours=offset, sectors=2)
        assert result["base_max_fdp_hours"] == pytest.approx(expected)

    @pytest.mark.parametrize(
        "sectors,expected",
        [(1, 13.0), (3, 13.0), (4, 12.5), (5, 12.0), (6, 11.5), (7, 11.0), (8, 10.5), (12, 10.5)],
    )
    def test_sector_buckets(self, sectors, expected):
        result = max_fdp(sectors=sectors)
        assert result["base_max_fdp_hours"] == pytest.approx(expected)

    def test_appendix_2_table_5_1_wraps_midnight(self):
        """Table 5.1's 1600-0459 band wraps midnight and must resolve."""
        result = max_fdp(
            appendix="2",
            fdp_start_utc="2026-03-23T18:00:00Z",  # 0200 local at +8
            sectors=2,
            acclimatisation={"state": "acclimatised", "acclimatised_time_offset_hours": 8},
            augmented_crew={"additional_fcms": 2, "rest_facility_class": "class_1"},
        )
        assert result["base_max_fdp_hours"] > 0


class TestSplitDutyArithmetic:
    """§3.1 (+4h capped at 16h), §3.3 (half the rest capped at 2h), §3.5."""

    def test_sleeping_rest_adds_up_to_4h_capped_at_16(self):
        result = max_fdp(split_duty=split(4, "sleeping"))
        assert result["final_max_fdp_hours"] == pytest.approx(16.0)  # 13 + 4 -> capped
        assert result["adjustments"][0]["adjustment_hours"] == pytest.approx(3.0)

    def test_longer_sleeping_rest_does_not_exceed_the_cap(self):
        assert max_fdp(split_duty=split(6, "sleeping"))["final_max_fdp_hours"] == pytest.approx(16.0)

    @pytest.mark.parametrize(
        "duration,expected_increase",
        [(2, 1.0), (3, 1.5), (4, 2.0), (5, 2.0)],  # half the rest, capped at 2h
    )
    def test_resting_rest_adds_half_capped_at_2h(self, duration, expected_increase):
        result = max_fdp(split_duty=split(duration, "resting"))
        assert result["final_max_fdp_hours"] == pytest.approx(13.0 + expected_increase)

    def test_resting_rest_below_2h_earns_nothing(self):
        result = max_fdp(split_duty=split(1.5, "resting"))
        assert result["final_max_fdp_hours"] == pytest.approx(13.0)
        assert result["adjustments"] == []

    def test_night_overlapping_7h_sleeping_rest_reaches_16h(self):
        """§3.4(b): the increase to 16h where §3.4(a) is satisfied."""
        result = max_fdp(split_duty=split(7, "sleeping", overlaps=True))
        assert result["final_max_fdp_hours"] == pytest.approx(16.0)

    def test_post_split_remainder_limit_is_reported(self):
        """§3.5: any remaining portion after the rest must be <= 6h."""
        result = max_fdp(split_duty=split(4, "sleeping"))
        assert result["post_split_max_hours"] == pytest.approx(6.0)


class TestExtensionAllowances:
    """Appendix 3's 1-hour extension is correct and must survive Phase 3."""

    @pytest.mark.parametrize("appendix", ["1", "2", "3", "4", "5A", "6"])
    def test_one_hour_extension_appendices(self, appendix):
        body = {"appendix": appendix, "sectors": 2}
        if appendix == "2":
            body["acclimatisation"] = {
                "state": "acclimatised",
                "acclimatised_time_offset_hours": 8,
            }
        result = max_fdp(**body)
        assert result["max_extension_hours"] == pytest.approx(1.0)

    def test_absolute_max_is_final_plus_extension(self):
        result = max_fdp()
        assert result["absolute_max_with_extension_hours"] == pytest.approx(
            result["final_max_fdp_hours"] + result["max_extension_hours"]
        )


class TestSequenceValidatorUnchanged:
    """
    '/validate/sequence — the standout endpoint.' §11.2 tracking across four
    FDPs must be untouched by Phase 3.
    """

    def test_fourth_consecutive_wocl_infringement_is_caught(self):
        events = []
        for day in range(24, 28):
            events.append({
                "event_type": "fdp",
                "fdp_start_utc": f"2026-03-{day}T17:00:00Z",   # 0100 local at +8
                "fdp_end_utc": f"2026-03-{day}T23:00:00Z",
                "actual_flight_time_hours": 5.0,
                "actual_duty_time_hours": 6.0,
                "local_time_offset_hours": 8.0,
                "sectors": 2,
            })
            if day < 27:
                events.append({
                    "event_type": "off_duty",
                    "start_utc": f"2026-03-{day}T23:00:00Z",
                    "end_utc": f"2026-03-{day + 1}T17:00:00Z",
                    "duration_hours": 18.0,
                    "location": "away",
                })

        body = client.post(
            f"{BASE}/validate/sequence", json={"appendix": "3", "events": events}
        ).json()

        wocl = [
            v for v in body["violations"]
            if "wocl" in v["check"].lower() or "wocl" in v["detail"].lower()
        ]
        assert wocl, "the 4th consecutive WOCL infringement must still be caught"
