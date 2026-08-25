"""
Phase 5 remediation regression tests — S13, S9, S10, S11, plus the parameter
contract item deferred from Phase 2 and two findings made while implementing.
"""

import re

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
BASE = "/api/v1/cao481"
APPENDICES = ["1", "2", "3", "4", "4A", "4B", "5", "5A", "6"]

FULL_SUMMARY = {
    "flight_time_168h_hours": 10.0, "flight_time_28d_hours": 10.0,
    "flight_time_90d_hours": 10.0, "flight_time_365d_hours": 10.0,
    "flight_time_384h_hours": 10.0, "duty_time_168h_hours": 10.0,
    "duty_time_336h_hours": 10.0, "days_off_in_28d": 9, "days_off_in_384h": 9,
    "recovery_36h_block_in_168h": True, "recovery_36h_block_in_336h": True,
    "recovery_72h_block_in_504h": True,
}


def cumulative(appendix, summary=None, **kw):
    body = {
        "appendix": appendix,
        "as_of_utc": "2026-03-25T00:00:00Z",
        "summary": summary if summary is not None else dict(FULL_SUMMARY),
    }
    body.update(kw)
    response = client.post(f"{BASE}/validate/cumulative", json=body)
    assert response.status_code == 200, response.text
    return response.json()


# ═══════════════════════════════════════════════════════════════════════
# S13 — clause citation errors
# ═══════════════════════════════════════════════════════════════════════

class TestS13Citations:
    """
    The clause mapping was half appendix-aware: flight-time, recovery and
    days-off citations were hardcoded to Appendix 2's numbering and emitted
    unchanged for every appendix, which is why Appendix 3 recovery came out
    as §10.5a.
    """

    EXPECTED = {
        "1":  {"flight_time_28d": "§5.1", "flight_time_365d": "§5.2",
               "recovery_36h_2ln_in_168h": "§4.2(a)", "days_off_in_28d": "§4.2(b)"},
        "2":  {"flight_time_28d": "§11.1", "flight_time_365d": "§11.2",
               "duty_time_168h": "§12.1", "duty_time_336h": "§12.2",
               "recovery_36h_2ln_in_168h": "§10.5", "days_off_in_28d": "§10.6"},
        "3":  {"flight_time_28d": "§9.1", "flight_time_365d": "§9.2",
               "duty_time_168h": "§10.1", "duty_time_336h": "§10.2",
               "recovery_36h_2ln_in_168h": "§8.5", "days_off_in_28d": "§8.6"},
        "4":  {"flight_time_28d": "§9.1", "flight_time_365d": "§9.2",
               "recovery_36h_2ln_in_168h": "§8.5", "days_off_in_28d": "§8.6"},
        "4A": {"flight_time_28d": "§6", "duty_time_168h": "§7.1",
               "duty_time_336h": "§7.2", "days_off_in_384h": "§5.3"},
        "4B": {"flight_time_28d": "§6.1", "flight_time_365d": "§6.2",
               "duty_time_168h": "§7.1", "duty_time_336h": "§7.2",
               "recovery_36h_2ln_in_336h": "§5.4(a)",
               "recovery_72h_3ln_in_504h": "§5.4(b)"},
        "5":  {"flight_time_168h": "§6.1", "flight_time_28d": "§6.2",
               "flight_time_90d": "§6.3", "flight_time_365d": "§6.5",
               "recovery_36h_2ln_in_336h": "§5.2(a)",
               "recovery_72h_3ln_in_504h": "§5.2(b)"},
        "5A": {"flight_time_384h": "§5.1", "flight_time_365d": "§5.4",
               "days_off_in_384h": "§4.2"},
        "6":  {"flight_time_28d": "§8.1", "flight_time_365d": "§8.2",
               "duty_time_168h": "§9.1", "duty_time_336h": "§9.2",
               "recovery_36h_2ln_in_168h": "§7.2", "days_off_in_28d": "§7.3"},
    }

    @pytest.mark.parametrize("appendix", APPENDICES)
    def test_each_appendix_cites_its_own_clauses(self, appendix):
        body = cumulative(appendix)
        emitted = {c["check"]: c["clause"] for c in body["checks"]}
        for check, clause in self.EXPECTED[appendix].items():
            assert emitted.get(check) == clause, (
                f"Appendix {appendix} {check}: expected {clause}, "
                f"got {emitted.get(check)}"
            )

    def test_appendix_3_recovery_is_not_appendix_2s_number(self):
        """The specific wrong output: §10.5a on an Appendix 3 response."""
        body = cumulative("3")
        clauses = {c["clause"] for c in body["checks"]}
        assert "§10.5a" not in clauses
        assert "§10.5b" not in clauses
        assert "§8.5" in clauses and "§8.6" in clauses

    def test_appendix_3_flight_time_is_not_appendix_2s_number(self):
        body = cumulative("3")
        emitted = {c["check"]: c["clause"] for c in body["checks"]}
        assert emitted["flight_time_28d"] == "§9.1"    # was §11.1
        assert emitted["flight_time_365d"] == "§9.2"   # was §11.2

    @pytest.mark.parametrize("appendix", APPENDICES)
    def test_no_citation_is_empty(self, appendix):
        for check in cumulative(appendix)["checks"]:
            assert check["clause"], f"{appendix} {check['check']} has no clause"

    @pytest.mark.parametrize("appendix", APPENDICES)
    def test_every_citation_resolves_to_its_own_appendix(self, appendix):
        """
        Structural test from the spec: enumerate every clause the API can emit
        for an appendix and assert each resolves via GET /sections/{id} to a
        section belonging to that appendix.
        """
        for check in cumulative(appendix)["checks"]:
            section = check["clause"].lstrip("§").split("(")[0].split(".")[0]
            section_id = f"APPENDIX {appendix}.{section}"
            response = client.get(f"{BASE}/sections/{section_id}")
            assert response.status_code == 200, (
                f"{appendix} {check['check']} cites {check['clause']} -> "
                f"{section_id} does not resolve"
            )

    @pytest.mark.parametrize("appendix", APPENDICES)
    def test_no_internal_identifier_shape(self, appendix):
        """Catches the §3.night class of leak."""
        pattern = re.compile(r"^§\d+\.[a-z]+$")
        for check in cumulative(appendix)["checks"]:
            assert not pattern.match(check["clause"])

    @pytest.mark.parametrize("appendix", APPENDICES)
    def test_citation_format_is_consistent(self, appendix):
        """The legislation writes 8.1(b), not 8.1b."""
        pattern = re.compile(r"^§\d+(\.\d+)?(\([a-z]\))?(\([iv]+\))?(\([A-Z]\))?$")
        for check in cumulative(appendix)["checks"]:
            assert pattern.match(check["clause"]), check["clause"]


# ═══════════════════════════════════════════════════════════════════════
# S9 — absence of data treated as compliance
# ═══════════════════════════════════════════════════════════════════════

def two_day_roster(**extra):
    body = {
        "appendix": "3",
        "roster_start_utc": "2026-03-23T00:00:00Z",
        "roster_end_utc": "2026-03-25T00:00:00Z",
        "events": [{
            "event_type": "fdp",
            "fdp_start_utc": "2026-03-23T23:00:00Z",
            "fdp_end_utc": "2026-03-24T07:00:00Z",
            "actual_flight_time_hours": 6, "actual_duty_time_hours": 8,
            "local_time_offset_hours": 8, "sectors": 3,
        }],
    }
    body.update(extra)
    response = client.post(f"{BASE}/validate/roster", json=body)
    assert response.status_code == 200, response.text
    return response.json()


class TestS9DataUnavailable:
    """
    v0.5.0 counted the 26 days before the roster — about which it knew
    nothing — as days off, and reported finding a 36h recovery block in empty
    space.
    """

    def test_days_off_is_not_invented_from_empty_space(self):
        body = two_day_roster()
        check = next(
            c for c in body["cumulative_result"]["checks"]
            if c["check"] == "days_off_in_28d"
        )
        assert check["status"] == "data_unavailable"   # v0.5.0: passed, 26.0
        assert check["passed"] is None

    def test_recovery_block_is_not_found_in_empty_space(self):
        body = two_day_roster()
        check = next(
            c for c in body["cumulative_result"]["checks"]
            if c["check"] == "recovery_36h_2ln_in_168h"
        )
        assert check["status"] == "data_unavailable"
        assert "Found required" not in (check["detail"] or "")

    def test_no_response_claims_a_block_it_did_not_see(self):
        body = two_day_roster()
        assert "Found required 36h+ off-duty block" not in str(body)

    def test_accumulating_limits_are_also_unestablished(self):
        body = two_day_roster()
        statuses = {
            c["check"]: c["status"] for c in body["cumulative_result"]["checks"]
        }
        for check in ("flight_time_28d", "flight_time_365d",
                      "duty_time_168h", "duty_time_336h"):
            assert statuses[check] == "data_unavailable"

    def test_computed_lower_bound_is_still_reported(self):
        """A skipped accumulating check keeps its computed figure."""
        body = two_day_roster()
        check = next(
            c for c in body["cumulative_result"]["checks"]
            if c["check"] == "flight_time_28d"
        )
        assert check["actual"] == pytest.approx(6.0)
        assert check["passed"] is None

    def test_incompleteness_is_reported_without_failing_the_roster(self):
        """
        `valid` tracks violations only. Validating a roster without prior
        history is an ordinary thing to do, so an unestablished cumulative
        window is surfaced through checks_skipped and a warning rather than by
        marking the roster invalid — otherwise the flag cries wolf on the
        common case and stops meaning anything.
        """
        body = two_day_roster()
        assert body["summary"]["total_violations"] == 0
        assert body["valid"] is True
        assert body["summary"]["checks_skipped"] > 0
        assert any("not been shown to be compliant" in w for w in body["warnings"])

    def test_a_real_violation_still_fails_the_roster(self):
        body = two_day_roster(prior_summary={"duty_time_168h_hours": 500})
        assert body["valid"] is False
        assert body["summary"]["total_violations"] > 0

    def test_a_breach_visible_in_covered_data_is_still_a_breach(self):
        """
        Under-coverage must not mask a violation: a total that already exceeds
        the limit is a genuine breach whatever the missing history holds.
        """
        body = two_day_roster(prior_summary={"duty_time_168h_hours": 500})
        check = next(
            c for c in body["cumulative_result"]["checks"]
            if c["check"] == "duty_time_168h"
        )
        assert check["status"] == "failed"
        assert check["passed"] is False

    def test_full_history_resolves_the_checks(self):
        from datetime import datetime, timedelta

        log, day = [], datetime(2025, 3, 20)
        while day < datetime(2026, 3, 23):
            if day.day % 7 < 3:
                log.append({
                    "fdp_start_utc": day.strftime("%Y-%m-%dT00:00:00Z"),
                    "fdp_end_utc": day.strftime("%Y-%m-%dT06:00:00Z"),
                    "actual_flight_time_hours": 1.0,
                    "actual_duty_time_hours": 1.0,
                    "local_time_offset_hours": 8,
                })
            day += timedelta(days=1)

        body = two_day_roster(prior_fdp_log=log)
        statuses = {
            c["check"]: c["status"] for c in body["cumulative_result"]["checks"]
        }
        for check in ("flight_time_28d", "flight_time_365d", "duty_time_168h",
                      "duty_time_336h", "days_off_in_28d"):
            assert statuses[check] in ("passed", "failed"), (
                f"{check} should resolve on a full log, got {statuses[check]}"
            )

    def test_appendix_5a_behaviour_is_unchanged(self):
        """§6 of the spec: 5A's data_unavailable handling was already right."""
        body = cumulative("5A", summary={"flight_time_384h_hours": 50.0})
        statuses = {c["check"]: c["status"] for c in body["checks"]}
        assert statuses["flight_time_384h"] == "passed"
        assert statuses["flight_time_365d"] == "data_unavailable"

    def test_skipped_check_never_raises_a_violation(self):
        """`passed=None` is falsy — it must not be read as a failure."""
        body = two_day_roster()
        skipped = {
            c["check"] for c in body["cumulative_result"]["checks"]
            if c["status"] == "data_unavailable"
        }
        raised = {v["check"] for v in body["all_violations"]}
        assert not (skipped & raised)


# ═══════════════════════════════════════════════════════════════════════
# S10 — Appendix 1 §2.1 FDP window and §2.5 late FDPs
# ═══════════════════════════════════════════════════════════════════════

class TestS10Appendix1Window:
    """
    v0.5.0 accepted an Appendix 1 FDP starting 1900 local and running 8h to
    0300 local: valid=true, 8.0 <= 8.0. §2.1(b) confines it to 0100 local on
    the following day.
    """

    def _validate(self, start_utc, end_utc):
        response = client.post(f"{BASE}/validate/fdp", json={
            "appendix": "1", "fdp_start_utc": start_utc,
            "fdp_end_utc": end_utc, "local_time_offset_hours": 8, "sectors": 1,
        })
        assert response.status_code == 200, response.text
        return response.json()

    def test_1900_start_running_8h_is_invalid(self):
        body = self._validate("2026-03-24T11:00:00Z", "2026-03-24T19:00:00Z")
        assert body["valid"] is False       # v0.5.0 returned True
        assert any(v["clause"] == "§2.1(b)" for v in body["violations"])

    def test_1900_start_running_5h_is_valid(self):
        body = self._validate("2026-03-24T11:00:00Z", "2026-03-24T16:00:00Z")
        assert body["valid"] is True, body["violations"]

    def test_calculator_caps_at_the_window(self):
        response = client.post(f"{BASE}/calculate/max-fdp", json={
            "appendix": "1", "fdp_start_utc": "2026-03-24T11:00:00Z",
            "local_time_offset_hours": 8, "sectors": 1,
        })
        result = response.json()
        assert result["final_max_fdp_hours"] == pytest.approx(6.0)  # was 8.0
        assert result["adjustments"][-1]["clause"] == "§2.1(b)"

    def test_daytime_fdp_is_unaffected(self):
        response = client.post(f"{BASE}/calculate/max-fdp", json={
            "appendix": "1", "fdp_start_utc": "2026-03-24T02:00:00Z",
            "local_time_offset_hours": 8, "sectors": 1,
        })
        assert response.json()["final_max_fdp_hours"] == pytest.approx(9.0)

    def test_start_before_0700_cannot_be_verified(self):
        """
        §2.1(a) is the EARLIER of morning civil twilight and 0700. Twilight
        needs a position this API is not given, so an earlier start is
        data_unavailable — assuming 0700 would fail the lawful pre-0600 starts
        that §2.3 expressly contemplates.
        """
        body = self._validate("2026-03-23T21:00:00Z", "2026-03-24T04:00:00Z")
        check = next(
            c for c in body["checks"] if c["check"] == "fdp_starts_within_window"
        )
        assert check["status"] == "data_unavailable"
        assert not any(
            v["check"] == "fdp_starts_within_window" for v in body["violations"]
        )

    def test_start_at_or_after_0700_satisfies_2_1_a(self):
        body = self._validate("2026-03-23T23:00:00Z", "2026-03-24T06:00:00Z")
        check = next(
            c for c in body["checks"] if c["check"] == "fdp_starts_within_window"
        )
        assert check["status"] == "passed"

    def test_other_appendices_have_no_window_rule(self):
        for appendix in ("2", "3", "4B"):
            body = {"appendix": appendix, "fdp_start_utc": "2026-03-24T11:00:00Z",
                    "fdp_end_utc": "2026-03-24T19:00:00Z",
                    "local_time_offset_hours": 8, "sectors": 1}
            if appendix == "2":
                body["acclimatisation"] = {
                    "state": "acclimatised", "acclimatised_time_offset_hours": 8,
                }
            result = client.post(f"{BASE}/validate/fdp", json=body).json()
            assert not [
                c for c in result["checks"] if c["check"] == "fdp_within_daily_window"
            ]

    def test_appendix_1_has_no_blanket_flight_time_limit(self):
        """§6 of the spec: flight_time_limit_hours null is correct here."""
        response = client.post(f"{BASE}/calculate/max-fdp", json={
            "appendix": "1", "fdp_start_utc": "2026-03-24T02:00:00Z",
            "local_time_offset_hours": 8, "sectors": 1,
        })
        assert response.json()["flight_time_limit_hours"] is None


class TestS10LateFdps:
    """§2.5 — not more than 3 late FDPs in any 168 consecutive hours."""

    def _sequence(self, count):
        events = []
        for offset in range(count):
            day = 24 + offset
            events.append({
                "event_type": "fdp",
                "fdp_start_utc": f"2026-03-{day}T08:00:00Z",   # 1600 local
                "fdp_end_utc": f"2026-03-{day}T15:00:00Z",     # 2300 local
                "actual_flight_time_hours": 5, "actual_duty_time_hours": 7,
                "local_time_offset_hours": 8, "sectors": 1,
            })
            if offset < count - 1:
                events.append({
                    "event_type": "off_duty",
                    "start_utc": f"2026-03-{day}T15:00:00Z",
                    "end_utc": f"2026-03-{day + 1}T08:00:00Z",
                    "duration_hours": 17.0, "location": "away",
                })
        response = client.post(
            f"{BASE}/validate/sequence", json={"appendix": "1", "events": events}
        )
        assert response.status_code == 200, response.text
        return response.json()

    def test_three_late_fdps_are_permitted(self):
        body = self._sequence(3)
        assert not [v for v in body["violations"] if "late_fdp" in v["check"]]

    def test_a_fourth_late_fdp_violates_2_5(self):
        body = self._sequence(4)
        late = [v for v in body["violations"] if "late_fdp" in v["check"]]
        assert late
        assert late[0]["clause"] == "§2.5"
        assert late[0]["actual"] == pytest.approx(4.0)
        assert late[0]["limit"] == pytest.approx(3.0)


# ═══════════════════════════════════════════════════════════════════════
# S11 — consecutive_wocl_infringements inert on /validate/fdp
# ═══════════════════════════════════════════════════════════════════════

class TestS11ConsecutiveWocl:
    """
    v0.5.0 accepted consecutive_wocl_infringements and did nothing with it,
    while consecutive_early_starts on the same endpoint took effect.

    Resolved as Option B rather than the spec's preferred Option A: Option A
    would reject consecutive_early_starts with a 422, which contradicts S6's
    requirement that it raise a §11.1 violation on the validator.
    """

    def _wocl_fdp(self, count, appendix="3"):
        body = {
            "appendix": appendix,
            "fdp_start_utc": "2026-03-23T18:00:00Z",   # 0200 local at +8
            "fdp_end_utc": "2026-03-24T02:00:00Z",
            "local_time_offset_hours": 8, "sectors": 2,
            "consecutive_wocl_infringements": count,
        }
        if appendix == "2":
            body["acclimatisation"] = {
                "state": "acclimatised", "acclimatised_time_offset_hours": 8,
            }
        response = client.post(f"{BASE}/validate/fdp", json=body)
        assert response.status_code == 200, response.text
        return response.json()

    def test_three_prior_infringements_blocks_a_fourth(self):
        body = self._wocl_fdp(3)
        assert body["valid"] is False       # v0.5.0: no violation at all
        assert any(v["clause"] == "§11.2" for v in body["violations"])

    def test_two_prior_infringements_is_permitted(self):
        body = self._wocl_fdp(2)
        check = next(
            c for c in body["checks"]
            if c["check"] == "consecutive_wocl_infringements"
        )
        assert check["passed"] is True

    @pytest.mark.parametrize("appendix,clause", [("2", "§13.2"), ("3", "§11.2")])
    def test_each_appendix_cites_its_own_clause(self, appendix, clause):
        body = self._wocl_fdp(3, appendix)
        assert any(v["clause"] == clause for v in body["violations"])

    def test_non_wocl_fdp_is_unaffected(self):
        body = client.post(f"{BASE}/validate/fdp", json={
            "appendix": "3", "fdp_start_utc": "2026-03-24T02:00:00Z",
            "fdp_end_utc": "2026-03-24T10:00:00Z",
            "local_time_offset_hours": 8, "sectors": 2,
            "consecutive_wocl_infringements": 5,
        }).json()
        assert body["valid"] is True
        assert any("does not infringe the WOCL" in n for n in body["calculation_notes"])

    def test_consecutive_early_starts_still_works(self):
        """S6 must not be regressed by the S11 resolution."""
        body = client.post(f"{BASE}/validate/fdp", json={
            "appendix": "3", "fdp_start_utc": "2026-03-23T21:30:00Z",
            "fdp_end_utc": "2026-03-24T02:30:00Z",
            "local_time_offset_hours": 8, "sectors": 2,
            "consecutive_early_starts": 5,
        }).json()
        assert any(v["clause"] == "§11.1" for v in body["violations"])

    def test_calculator_retains_both_parameters(self):
        response = client.post(f"{BASE}/calculate/max-fdp", json={
            "appendix": "3", "fdp_start_utc": "2026-03-23T21:30:00Z",
            "local_time_offset_hours": 8, "sectors": 2,
            "consecutive_early_starts": 2, "consecutive_wocl_infringements": 1,
        })
        assert response.status_code == 200

    def test_sequence_wocl_handling_is_unchanged(self):
        events = []
        for day in range(24, 28):
            events.append({
                "event_type": "fdp",
                "fdp_start_utc": f"2026-03-{day}T17:00:00Z",
                "fdp_end_utc": f"2026-03-{day}T23:00:00Z",
                "actual_flight_time_hours": 5.0, "actual_duty_time_hours": 6.0,
                "local_time_offset_hours": 8.0, "sectors": 2,
            })
            if day < 27:
                events.append({
                    "event_type": "off_duty",
                    "start_utc": f"2026-03-{day}T23:00:00Z",
                    "end_utc": f"2026-03-{day + 1}T17:00:00Z",
                    "duration_hours": 18.0, "location": "away",
                })
        body = client.post(
            f"{BASE}/validate/sequence", json={"appendix": "3", "events": events}
        ).json()
        assert [v for v in body["violations"] if "wocl" in v["check"].lower()]


# ═══════════════════════════════════════════════════════════════════════
# Parameter contract — deferred from Phase 2
# ═══════════════════════════════════════════════════════════════════════

class TestFollowingOffDutyLocation:
    """
    `following_off_duty_location` was accepted and never read: only
    `preceding_fdp.location` drove the §8.1 / §10.1 branch. Two fields, one
    meaning, one wired.
    """

    def _payload(self, **kw):
        body = {
            "appendix": "3",
            "preceding_fdp": {
                "start_utc": "2026-03-24T00:00:00Z",
                "end_utc": "2026-03-24T10:00:00Z",
                "duration_hours": 10, "location": "home_base",
            },
        }
        body.update(kw)
        return body

    def test_disagreement_is_rejected(self):
        response = client.post(
            f"{BASE}/calculate/min-off-duty",
            json=self._payload(following_off_duty_location="away"),
        )
        assert response.status_code == 422
        assert "following_off_duty_location" in response.text

    def test_agreement_is_accepted(self):
        response = client.post(
            f"{BASE}/calculate/min-off-duty",
            json=self._payload(following_off_duty_location="home_base"),
        )
        assert response.status_code == 200
        assert response.json()["base_min_odp_hours"] == pytest.approx(12.0)

    def test_omitting_it_keeps_the_existing_behaviour(self):
        response = client.post(f"{BASE}/calculate/min-off-duty", json=self._payload())
        assert response.status_code == 200
        assert response.json()["base_min_odp_hours"] == pytest.approx(12.0)

    def test_validate_off_duty_applies_the_same_rule(self):
        response = client.post(
            f"{BASE}/validate/off-duty",
            json={
                **self._payload(following_off_duty_location="away"),
                "actual_off_duty_hours": 14.0,
            },
        )
        assert response.status_code == 422


# ═══════════════════════════════════════════════════════════════════════
# Found while implementing Phase 5
# ═══════════════════════════════════════════════════════════════════════

class TestRecoveryAlternatives:
    """
    App 4B §5.4 and App 5 §5.2 read "at least 1 of the following". Both limbs
    were being demanded, producing a false violation that would block a
    lawful roster.
    """

    @pytest.mark.parametrize("appendix", ["4B", "5"])
    @pytest.mark.parametrize(
        "limbs",
        [
            {"recovery_36h_block_in_336h": True, "recovery_72h_block_in_504h": False},
            {"recovery_36h_block_in_336h": False, "recovery_72h_block_in_504h": True},
        ],
    )
    def test_either_limb_discharges_the_requirement(self, appendix, limbs):
        body = cumulative(appendix, summary={**FULL_SUMMARY, **limbs})
        assert body["valid"] is True, body["violations"]

    @pytest.mark.parametrize("appendix", ["4B", "5"])
    def test_neither_limb_is_a_violation(self, appendix):
        body = cumulative(appendix, summary={
            **FULL_SUMMARY,
            "recovery_36h_block_in_336h": False,
            "recovery_72h_block_in_504h": False,
        })
        assert body["valid"] is False


class TestConditionalRecoveryBlocks:
    """
    App 4B §5.3 and App 5 §5.3 make the 168-hour block conditional on a
    trigger this API is not told about. Asserting it unconditionally raised
    violations the legislation does not support.
    """

    @pytest.mark.parametrize("appendix", ["4B", "5"])
    def test_not_asserted_as_a_check(self, appendix):
        body = cumulative(appendix)
        assert not [
            c for c in body["checks"] if c["check"] == "recovery_36h_2ln_in_168h"
        ]

    @pytest.mark.parametrize("appendix", ["4B", "5"])
    def test_unconditional_appendices_still_check_it(self, appendix):
        body = cumulative("3")
        assert [
            c for c in body["checks"] if c["check"] == "recovery_36h_2ln_in_168h"
        ]


class TestAppendix5ANoRecoveryBlock:
    """
    Appendix 5A has no 168-hour recovery requirement — §4.1 is the 10h ODP and
    §4.2 is 2 consecutive days off in 384 hours. The inherited default was
    emitting a check with no clause behind it.
    """

    def test_no_unfounded_recovery_check(self):
        body = cumulative("5A")
        assert not [
            c for c in body["checks"] if c["check"] == "recovery_36h_2ln_in_168h"
        ]
