"""
Phase 4 remediation regression tests — S2 and S16 (Appendix 2 augmented crew).

Includes pins for the Table 5.1 / 5.2 lookups, which the spec lists as correct
and which must survive the §5.3 work layered on top of them.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
BASE = "/api/v1/cao481"

ACCLIMATISED = {"state": "acclimatised", "acclimatised_time_offset_hours": 8}


def max_fdp(**overrides):
    body = {
        "appendix": "2",
        "fdp_start_utc": "2026-03-24T03:00:00Z",   # 1100 acclimatised at +8
        "local_time_offset_hours": 8,
        "sectors": 2,
        "acclimatisation": ACCLIMATISED,
    }
    body.update(overrides)
    response = client.post(f"{BASE}/calculate/max-fdp", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def validate_fdp(**overrides):
    body = {
        "appendix": "2",
        "fdp_start_utc": "2026-03-24T04:00:00Z",
        "fdp_end_utc": "2026-03-24T22:00:00Z",     # 18h
        "local_time_offset_hours": 8,
        "sectors": 3,
        "acclimatisation": ACCLIMATISED,
    }
    body.update(overrides)
    response = client.post(f"{BASE}/validate/fdp", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def crew(fcms=2, rest_class="class_1", rest=None, **extra):
    payload = {"additional_fcms": fcms, "rest_facility_class": rest_class, **extra}
    if rest is not None:
        payload["in_flight_rest_hours_per_fcm"] = rest
    return payload


def clauses(body):
    return {v["clause"] for v in body["violations"]}


# ═══════════════════════════════════════════════════════════════════════
# Pins — Table 5.1 / 5.2 lookups are correct and must stay correct
# ═══════════════════════════════════════════════════════════════════════

class TestAugmentedTablePins:

    @pytest.mark.parametrize(
        "rest_class,fcms,utc,expected",
        [
            # Class 1 and 2 are flat across every acclimatised-time band.
            ("class_1", 1, "2026-03-23T23:00:00Z", 16.0),
            ("class_1", 2, "2026-03-23T23:00:00Z", 18.0),
            ("class_2", 1, "2026-03-24T03:00:00Z", 15.0),
            ("class_2", 2, "2026-03-24T03:00:00Z", 16.5),
            # Class 3 varies by band, including the 1600-0459 wrap.
            ("class_3", 1, "2026-03-23T23:00:00Z", 14.0),   # 0700-1059
            ("class_3", 1, "2026-03-24T03:00:00Z", 13.0),   # 1100-1559
            ("class_3", 1, "2026-03-24T08:00:00Z", 12.0),   # 1600-0459
            ("class_3", 1, "2026-03-23T21:00:00Z", 13.0),   # 0500-0659
            ("class_3", 2, "2026-03-24T08:00:00Z", 13.0),
        ],
    )
    def test_table_5_1(self, rest_class, fcms, utc, expected):
        result = max_fdp(
            fdp_start_utc=utc, sectors=1, augmented_crew=crew(fcms, rest_class),
        )
        assert result["base_max_fdp_hours"] == pytest.approx(expected)

    @pytest.mark.parametrize(
        "rest_class,fcms,odp_hours,expected",
        [
            ("class_1", 1, 20, 16.0), ("class_1", 2, 20, 18.0),
            ("class_3", 1, 20, 12.0), ("class_3", 1, 40, 14.0),
            ("class_3", 2, 20, 13.0), ("class_3", 2, 40, 15.0),
        ],
    )
    def test_table_5_2(self, rest_class, fcms, odp_hours, expected):
        result = max_fdp(
            sectors=1,
            acclimatisation={"state": "unknown"},
            preceding_off_duty_hours=odp_hours,
            augmented_crew=crew(fcms, rest_class),
        )
        assert result["base_max_fdp_hours"] == pytest.approx(expected)


# ═══════════════════════════════════════════════════════════════════════
# S2 — §5.3 conditions unimplemented
# ═══════════════════════════════════════════════════════════════════════

class TestS2AugmentedConditions:
    """
    v0.5.0 ran a single check on this payload — fdp_within_limit, 18.0 <= 18.0
    — and returned valid=true with empty violations and warnings. Five §5.3
    conditions were breached by the data supplied.
    """

    REST = [
        {"fcm_id": "CP", "rest_hours": 1, "at_controls_final_landing": True},
        {"fcm_id": "FO", "rest_hours": 1, "at_controls_final_landing": False},
    ]

    def test_spec_payload_is_now_invalid(self):
        body = validate_fdp(
            actual_flight_time_hours=16, augmented_crew=crew(rest=self.REST),
        )
        assert body["valid"] is False        # v0.5.0 returned True
        assert len(body["violations"]) >= 4

    def test_every_breached_condition_is_cited(self):
        body = validate_fdp(
            actual_flight_time_hours=16, augmented_crew=crew(rest=self.REST),
        )
        assert {
            "§5.3(f)(i)",      # >14h permits not more than 2 sectors; 3 assigned
            "§5.3(g)(i)",      # >16h permits only 1 sector
            "§5.3(d)(ii)",     # at-controls FCM needs 2h; had 1h
            "§5.3(d)(i)",      # not-at-controls FCM needs 1.5h; had 1h
            "§5.3(g)(ii)(B)",  # >16h at-controls needs 3h
            "§5.3(g)(ii)(A)",  # >16h not-at-controls needs 2h
        } <= clauses(body)

    def test_conditions_are_cumulative_not_alternatives(self):
        """
        §5.3 introduces a list of conditions, all of which must be met. An 18h
        3-sector FDP breaches §5.3(f)(i) AND §5.3(g)(i); reporting only the
        stricter one would hide the shorter FDP that was actually available.
        """
        body = validate_fdp(
            actual_flight_time_hours=16, augmented_crew=crew(rest=self.REST),
        )
        assert "§5.3(f)(i)" in clauses(body)
        assert "§5.3(g)(i)" in clauses(body)

    def test_rest_is_read_per_fcm_by_landing_role(self):
        """A 16h FDP: at-controls needs 2h (§5.3(d)(ii)), other needs 1.5h."""
        body = validate_fdp(
            fdp_end_utc="2026-03-24T20:00:00Z",   # 16h exactly, not over
            sectors=1,
            augmented_crew=crew(rest=[
                {"fcm_id": "CP", "rest_hours": 2.0, "at_controls_final_landing": True},
                {"fcm_id": "FO", "rest_hours": 1.5, "at_controls_final_landing": False},
            ]),
        )
        rest_checks = [c for c in body["checks"] if "in_flight_rest" in c["check"]]
        assert rest_checks and all(c["passed"] for c in rest_checks)

    def test_at_controls_discriminator_actually_discriminates(self):
        """1.5h satisfies §5.3(d)(i) but not §5.3(d)(ii)."""
        body = validate_fdp(
            fdp_end_utc="2026-03-24T20:00:00Z", sectors=1,
            augmented_crew=crew(rest=[
                {"fcm_id": "CP", "rest_hours": 1.5, "at_controls_final_landing": True},
                {"fcm_id": "FO", "rest_hours": 1.5, "at_controls_final_landing": False},
            ]),
        )
        assert "§5.3(d)(ii)" in clauses(body)
        assert "§5.3(d)(i)" not in clauses(body)

    def test_missing_rest_data_is_unavailable_not_passed(self):
        body = validate_fdp(actual_flight_time_hours=16, augmented_crew=crew())
        rest = next(c for c in body["checks"] if "in_flight_rest" in c["check"])
        assert rest["status"] == "data_unavailable"
        assert rest["passed"] is None       # explicitly not True
        assert body["checks_skipped"] >= 1
        assert body["valid"] is False       # incomplete is not compliant

    def test_unverifiable_conditions_are_surfaced_not_claimed(self):
        body = validate_fdp(actual_flight_time_hours=16, augmented_crew=crew(rest=self.REST))
        joined = " ".join(body["warnings"])
        for clause in ("§5.3(a)", "§5.3(b)", "§5.3(e)"):
            assert clause in joined
        # They must not appear as satisfied checks.
        assert not [
            c for c in body["checks"]
            if c["clause"] in ("§5.3(a)", "§5.3(b)", "§5.3(e)") and c["passed"]
        ]

    def test_compliant_augmented_fdp_still_passes(self):
        body = validate_fdp(
            fdp_end_utc="2026-03-24T20:00:00Z",   # 16h
            sectors=1,
            augmented_crew=crew(rest=[
                {"fcm_id": "CP", "rest_hours": 2.5, "at_controls_final_landing": True},
                {"fcm_id": "FO", "rest_hours": 2.0, "at_controls_final_landing": False},
            ]),
        )
        assert body["valid"] is True, body["violations"]
        assert body["checks_skipped"] == 0


class TestS2SectorCeiling:
    """
    v0.5.0 returned 18.0 for Class 1 / 2 additional FCMs at 1, 2, 3 and even 6
    sectors, with an empty adjustments array every time.
    """

    @pytest.mark.parametrize("sectors,expected", [(1, 18.0), (2, 16.0), (3, 14.0)])
    def test_ceiling_falls_with_sector_count(self, sectors, expected):
        result = max_fdp(sectors=sectors, augmented_crew=crew(2, "class_1"))
        assert result["final_max_fdp_hours"] == pytest.approx(expected)

    @pytest.mark.parametrize("sectors,clause", [(1, "§5.3(c)"), (2, "§5.3(g)(i)"), (3, "§5.3(f)(i)")])
    def test_each_ceiling_is_auditable(self, sectors, clause):
        result = max_fdp(sectors=sectors, augmented_crew=crew(2, "class_1"))
        assert result["adjustments"], "v0.5.0 returned an empty adjustments array"
        assert result["adjustments"][-1]["clause"] == clause

    def test_ceiling_does_not_raise_a_lower_table_value(self):
        """Class 3 / 1 FCM at 1600-0459 is 12h; the 2-sector cap is 16h."""
        result = max_fdp(
            fdp_start_utc="2026-03-24T08:00:00Z", sectors=2,
            augmented_crew=crew(1, "class_3"),
        )
        assert result["final_max_fdp_hours"] == pytest.approx(12.0)
        assert result["adjustments"][-1]["adjustment_hours"] == pytest.approx(0.0)


class TestS16FourOrMoreSectors:
    """§5.3(c): an augmented crew FDP must be limited to not more than 3 sectors."""

    @pytest.mark.parametrize("sectors", [4, 5, 6, 12])
    def test_prohibited_on_the_calculator(self, sectors):
        result = max_fdp(sectors=sectors, augmented_crew=crew(2, "class_1"))
        assert [v["clause"] for v in result["violations"]] == ["§5.3(c)"]

    @pytest.mark.parametrize("sectors", [4, 6])
    def test_prohibited_on_the_validator(self, sectors):
        body = validate_fdp(
            fdp_end_utc="2026-03-24T12:00:00Z", sectors=sectors,
            augmented_crew=crew(rest=[
                {"fcm_id": "CP", "rest_hours": 3, "at_controls_final_landing": True},
            ]),
        )
        assert body["valid"] is False
        assert "§5.3(c)" in clauses(body)

    @pytest.mark.parametrize("sectors", [1, 2, 3])
    def test_three_or_fewer_is_permitted(self, sectors):
        result = max_fdp(sectors=sectors, augmented_crew=crew(2, "class_1"))
        assert result["violations"] == []


class TestS53fii:
    """§5.3(f)(ii) — two sectors on an FDP exceeding 14 hours."""

    def _body(self, **crew_kwargs):
        return validate_fdp(
            fdp_end_utc="2026-03-24T20:00:00Z",   # 16h
            sectors=2,
            augmented_crew=crew(rest=[
                {"fcm_id": "CP", "rest_hours": 2.0, "at_controls_final_landing": True},
            ], **crew_kwargs),
        )

    def test_limb_b_satisfied_by_a_long_second_sector(self):
        body = self._body(second_sector_scheduled_flight_time_hours=9.0)
        check = next(c for c in body["checks"] if c["check"] == "augmented_two_sector_over_14h")
        assert check["passed"] is True
        assert check["clause"] == "§5.3(f)(ii)(B)"

    def test_limb_b_fails_below_nine_hours(self):
        body = self._body(second_sector_scheduled_flight_time_hours=8.0)
        assert "§5.3(f)(ii)" in clauses(body)

    def test_unsupplied_data_is_unavailable_not_passed(self):
        body = self._body()
        check = next(c for c in body["checks"] if c["check"] == "augmented_two_sector_over_14h")
        assert check["status"] == "data_unavailable"
        assert check["passed"] is None
        assert body["valid"] is False

    def test_does_not_apply_at_or_below_14h(self):
        body = validate_fdp(
            fdp_end_utc="2026-03-24T18:00:00Z",   # 14h exactly
            sectors=2,
            augmented_crew=crew(rest=[
                {"fcm_id": "CP", "rest_hours": 2.0, "at_controls_final_landing": True},
            ]),
        )
        assert not [
            c for c in body["checks"] if c["check"] == "augmented_two_sector_over_14h"
        ]


class TestAugmentedFlightTime:
    """
    The open reading in the spec, resolved against the served text.

    Clause 5's title and the Note under Table 5.2 both suggest the tables cap
    flight time as well as FDP. §2.2 settles it: "An acclimatised FCM must not
    be assigned flight time longer than 10.5 hours **except in an augmented
    crew operation**", with its own Note: "There is no flight time limit for an
    augmented crew operation." A null limit here is correct.
    """

    def test_no_flight_time_limit_on_the_augmented_path(self):
        result = max_fdp(sectors=1, augmented_crew=crew(2, "class_1"))
        assert result["flight_time_limit_hours"] is None

    def test_the_omission_is_explained_not_silent(self):
        result = max_fdp(sectors=1, augmented_crew=crew(2, "class_1"))
        joined = " ".join(result["calculation_notes"])
        assert "no flight time limit" in joined.lower()
        assert "§2.2" in joined

    def test_non_augmented_appendix_2_keeps_the_10_5h_limit(self):
        result = max_fdp(sectors=2)
        assert result["flight_time_limit_hours"] == pytest.approx(10.5)

    def test_high_flight_time_raises_no_augmented_violation(self):
        body = validate_fdp(
            fdp_end_utc="2026-03-24T20:00:00Z", sectors=1,
            actual_flight_time_hours=16,
            augmented_crew=crew(rest=[
                {"fcm_id": "CP", "rest_hours": 2.5, "at_controls_final_landing": True},
                {"fcm_id": "FO", "rest_hours": 2.0, "at_controls_final_landing": False},
            ]),
        )
        assert not [c for c in body["checks"] if "flight_time" in c["check"]]
        assert body["valid"] is True
