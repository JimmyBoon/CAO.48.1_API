"""
Pinning tests for ODP behaviour the remediation spec §6 lists as confirmed
correct. Written BEFORE Phase 2 touches off_duty_calculator.py so that a
regression shows up as a failure here rather than as a wrong roster.

These assert *numbers*, not clause strings — the citations on this path are
corrected in Phase 2 (S13 rows for min-off-duty), the arithmetic is not.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
BASE = "/api/v1/cao481"


def min_off_duty(**overrides):
    body = {
        "appendix": "3",
        "preceding_fdp": {
            "start_utc": "2026-03-24T00:00:00Z",
            "end_utc": "2026-03-24T12:00:00Z",
            "duration_hours": 12,
            "location": "away",
        },
        "following_off_duty_location": "away",
    }
    body.update(overrides)
    response = client.post(f"{BASE}/calculate/min-off-duty", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def fdp(duration_hours, location="away", **extra):
    hours = int(duration_hours)
    minutes = int(round((duration_hours - hours) * 60))
    return {
        "start_utc": "2026-03-24T00:00:00Z",
        "end_utc": f"2026-03-24T{hours:02d}:{minutes:02d}:00Z",
        "duration_hours": duration_hours,
        "location": location,
        **extra,
    }


class TestAppendix3Arithmetic:
    """§8.1 and §8.2 — the base figures everything else is derived from."""

    def test_under_12h_away_is_10h(self):
        assert min_off_duty(preceding_fdp=fdp(10, "away"))["base_min_odp_hours"] == 10.0

    def test_under_12h_at_home_base_is_12h(self):
        result = min_off_duty(preceding_fdp=fdp(10, "home_base"))
        assert result["base_min_odp_hours"] == 12.0

    @pytest.mark.parametrize(
        "duration,expected",
        [(13, 13.5), (14, 15.0), (16, 18.0)],  # 12 + 1.5 x excess
    )
    def test_over_12h_formula(self, duration, expected):
        result = min_off_duty(preceding_fdp=fdp(duration, "away"))
        assert result["base_min_odp_hours"] == pytest.approx(expected)

    def test_post_fdp_duty_counts_toward_the_threshold(self):
        result = min_off_duty(
            preceding_fdp=fdp(11.5, "away", post_fdp_duty_hours=1.0)
        )
        # 11.5 + 1.0 = 12.5h > 12h, so §8.2: 12 + 1.5 x 0.5 = 12.75
        assert result["fdp_plus_post_duty_hours"] == pytest.approx(12.5)
        assert result["base_min_odp_hours"] == pytest.approx(12.75)


class TestSplitDutyOdpCredit:
    """
    §3.2 grants a 2h credit against the effective duration used for the ODP
    calculation; §3.4(c) takes it away when the split rest overlapped the
    2300–0529 window. The spec calls this out explicitly: 'S7's fix must not
    regress this'.
    """

    def test_sleeping_split_earns_the_2h_credit(self):
        result = min_off_duty(
            preceding_fdp=fdp(
                14,
                "away",
                split_duty={
                    "duration_hours": 4,
                    "accommodation": "sleeping",
                    "overlaps_2300_0529": False,
                },
            )
        )
        assert result["split_duty_credit_hours"] == pytest.approx(2.0)
        assert result["effective_duration_for_calc_hours"] == pytest.approx(12.0)
        # Credited down to 12h, so §8.1 applies rather than §8.2.
        assert result["base_min_odp_hours"] == pytest.approx(10.0)

    def test_night_overlapping_split_forfeits_the_credit(self):
        result = min_off_duty(
            preceding_fdp=fdp(
                14,
                "away",
                split_duty={
                    "duration_hours": 7,
                    "accommodation": "sleeping",
                    "overlaps_2300_0529": True,
                },
            )
        )
        assert result["split_duty_credit_hours"] == pytest.approx(0.0)
        assert result["effective_duration_for_calc_hours"] == pytest.approx(14.0)
        assert result["base_min_odp_hours"] == pytest.approx(15.0)

    def test_resting_accommodation_earns_no_odp_credit(self):
        result = min_off_duty(
            preceding_fdp=fdp(
                14,
                "away",
                split_duty={
                    "duration_hours": 4,
                    "accommodation": "resting",
                    "overlaps_2300_0529": False,
                },
            )
        )
        assert result["split_duty_credit_hours"] == pytest.approx(0.0)


class TestAppendix3ReductionGating:
    """§8.3(c) — the 9h reduction is withheld at home base."""

    def test_no_reduction_at_home_base(self):
        result = min_off_duty(
            preceding_fdp=fdp(10, "home_base"),
            preceding_off_duty={"duration_hours": 13, "included_local_night": True},
            following_off_duty_location="home_base",
        )
        reduction = result["reduction_applicable"]
        assert reduction is None or reduction["eligible"] is False

    def test_no_reduction_without_a_qualifying_preceding_odp(self):
        result = min_off_duty(
            preceding_fdp=fdp(10, "away"),
            preceding_off_duty={"duration_hours": 9, "included_local_night": False},
        )
        reduction = result["reduction_applicable"]
        assert reduction is None or reduction["eligible"] is False


class TestSimpleAppendices:
    """Fixed-minimum appendices must be unaffected by Phase 2."""

    @pytest.mark.parametrize(
        "appendix,expected", [("1", 12.0), ("4A", 10.0), ("5A", 10.0)]
    )
    def test_fixed_minimums(self, appendix, expected):
        result = min_off_duty(appendix=appendix, preceding_fdp=fdp(10, "away"))
        assert result["base_min_odp_hours"] == expected
        assert result["final_min_odp_hours"] == expected
