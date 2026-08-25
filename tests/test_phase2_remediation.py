"""
Phase 2 remediation regression tests — S3, S4, S15, plus the §8.3/§10.3 duty
gate found while implementing them.

Each test records what v0.5.0 produced, so a regression reads as a specific
wrong answer rather than just a red bar.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
BASE = "/api/v1/cao481"


def calc(**overrides):
    body = {"appendix": "3", "preceding_fdp": {}}
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


# ═══════════════════════════════════════════════════════════════════════
# S3 — ODP reductions auto-applied without being claimed
# ═══════════════════════════════════════════════════════════════════════

class TestS3ReductionMustBeClaimed:
    """
    v0.5.0 computed 15.0h correctly under §8.2, then applied the §8.4
    reduction anyway and validated a 14.5h ODP against 14.0h — returning
    valid=true with reduction_claimed explicitly false.
    """

    PAYLOAD = {
        "appendix": "3",
        "actual_off_duty_hours": 14.5,
        "reduction_claimed": False,
        "preceding_fdp": {
            "start_utc": "2026-03-24T00:00:00Z",
            "end_utc": "2026-03-24T14:00:00Z",
            "duration_hours": 14,
            "location": "away",
        },
    }

    def test_unclaimed_reduction_validates_against_the_full_minimum(self):
        body = client.post(f"{BASE}/validate/off-duty", json=self.PAYLOAD).json()
        check = next(c for c in body["checks"] if c["check"] == "odp_meets_minimum")

        assert body["valid"] is False, "v0.5.0 returned valid=true here"
        assert check["limit"] == pytest.approx(15.0)  # v0.5.0 used 14.0
        assert check["clause"] == "§8.2"

    def test_claimed_reduction_validates_against_the_reduced_minimum(self):
        payload = dict(self.PAYLOAD, reduction_claimed=True)
        body = client.post(f"{BASE}/validate/off-duty", json=payload).json()
        check = next(c for c in body["checks"] if c["check"] == "odp_meets_minimum")

        assert body["valid"] is True
        assert check["limit"] == pytest.approx(14.0)
        assert check["clause"] == "§8.4"

    def test_claimed_reduction_enumerates_caller_conditions_separately(self):
        payload = dict(self.PAYLOAD, reduction_claimed=True)
        body = client.post(f"{BASE}/validate/off-duty", json=payload).json()
        reduction_check = next(
            c for c in body["checks"] if c["check"] == "reduction_conditions_met"
        )
        assert reduction_check["passed"] is True
        assert "§8.4(c)" in reduction_check["detail"]

    def test_calculator_returns_the_unreduced_minimum(self):
        result = calc(preceding_fdp=fdp(14, "away"))
        # v0.5.0 returned final_min_odp_hours: 14.0 — the reduced figure.
        assert result["final_min_odp_hours"] == pytest.approx(15.0)
        assert result["base_min_odp_hours"] == pytest.approx(15.0)
        assert result["reduction_applicable"]["reduced_min_odp_hours"] == pytest.approx(14.0)

    def test_conditions_met_never_contains_an_unverifiable_condition(self):
        """
        Acceptance criterion: no response contains a string matching
        'caller must verify' inside a conditions_met array.
        """
        for appendix, state in (("3", "not_applicable"), ("2", "acclimatised")):
            result = calc(
                appendix=appendix,
                acclimatisation_state=state,
                preceding_fdp=fdp(14, "away"),
            )
            reduction = result["reduction_applicable"]
            assert reduction is not None
            for entry in reduction["conditions_met"]:
                assert "caller must verify" not in entry.lower()
            assert reduction["conditions_caller_must_verify"], (
                "the unverifiable condition must still be reported, separately"
            )

    def test_unverifiable_condition_alone_cannot_grant_eligibility(self):
        """A reduction whose checkable conditions fail is not eligible."""
        result = calc(preceding_fdp=fdp(14, "home_base"))
        reduction = result["reduction_applicable"]
        assert reduction["eligible"] is False
        assert reduction["reduced_min_odp_hours"] is None


# ═══════════════════════════════════════════════════════════════════════
# S4 — Appendix 2 acclimatisation_state ignored in ODP calculation
# ═══════════════════════════════════════════════════════════════════════

class TestS4AcclimatisationBranching:
    """
    v0.5.0 returned 10.0h and 14.0h for these two cases by falling through to
    the acclimatised away-from-base rule. The second is a 3-hour under-rest on
    a long-haul unacclimatised crew member.
    """

    def test_unknown_state_under_12h_uses_10_1_c(self):
        result = calc(
            appendix="2",
            acclimatisation_state="unknown",
            following_off_duty_location="away",
            preceding_fdp=fdp(10, "away"),
        )
        assert result["base_min_odp_hours"] == pytest.approx(14.0)  # was 10.0
        assert result["clause"] == "§10.1(c)"

    def test_unknown_state_over_12h_uses_10_2_b(self):
        result = calc(
            appendix="2",
            acclimatisation_state="unknown",
            following_off_duty_location="away",
            preceding_fdp=fdp(14, "away"),
        )
        assert result["base_min_odp_hours"] == pytest.approx(17.0)  # was 14.0
        assert result["clause"] == "§10.2(b)"

    def test_location_is_irrelevant_under_10_1_c(self):
        figures = {
            location: calc(
                appendix="2",
                acclimatisation_state="unknown",
                following_off_duty_location=location,
                preceding_fdp=fdp(10, location),
            )["base_min_odp_hours"]
            for location in ("away", "home_base")
        }
        assert figures["away"] == figures["home_base"] == pytest.approx(14.0)

    def test_acclimatised_state_keeps_the_location_branch(self):
        away = calc(
            appendix="2", acclimatisation_state="acclimatised",
            preceding_fdp=fdp(10, "away"),
        )
        home = calc(
            appendix="2", acclimatisation_state="acclimatised",
            preceding_fdp=fdp(10, "home_base"),
        )
        assert away["base_min_odp_hours"] == pytest.approx(10.0)
        assert away["clause"] == "§10.1(a)"
        assert home["base_min_odp_hours"] == pytest.approx(12.0)
        assert home["clause"] == "§10.1(b)"

    def test_appendix_4_has_displacement_but_no_acclimatisation_branch(self):
        """
        App 4 §8.1 is away/home only — verified against the served text. An
        unknown state must not select a 14h base there.
        """
        result = calc(
            appendix="4",
            acclimatisation_state="unknown",
            preceding_fdp=fdp(10, "away"),
        )
        assert result["base_min_odp_hours"] == pytest.approx(10.0)
        assert result["clause"] == "§8.1(a)"


class TestS4Displacement:
    """
    v0.5.0 emitted a prose note and accepted no parameter from which
    displacement could be derived, so Appendix 2 figures were structurally
    incomplete.
    """

    def test_acclimatised_adds_only_the_excess_westward(self):
        result = calc(
            appendix="2", acclimatisation_state="acclimatised",
            fdp_start_offset_hours=8, odp_start_offset_hours=0,
            preceding_fdp=fdp(10, "away"),
        )
        # 8h west, only the amount over 3h counts: +5h on a 10h base.
        assert result["displacement"]["status"] == "computed"
        assert result["displacement"]["direction"] == "west"
        assert result["displacement"]["added_hours"] == pytest.approx(5.0)
        assert result["base_min_odp_hours"] == pytest.approx(15.0)

    def test_acclimatised_adds_only_the_excess_eastward(self):
        result = calc(
            appendix="2", acclimatisation_state="acclimatised",
            fdp_start_offset_hours=0, odp_start_offset_hours=8,
            preceding_fdp=fdp(10, "away"),
        )
        # 8h east, threshold 2h: +6h.
        assert result["displacement"]["direction"] == "east"
        assert result["displacement"]["added_hours"] == pytest.approx(6.0)
        assert result["base_min_odp_hours"] == pytest.approx(16.0)

    def test_unknown_state_adds_the_full_displacement(self):
        result = calc(
            appendix="2", acclimatisation_state="unknown",
            fdp_start_offset_hours=8, odp_start_offset_hours=0,
            preceding_fdp=fdp(10, "away"),
        )
        # §10.1(c): 14h base + the FULL 8h displacement.
        assert result["displacement"]["added_hours"] == pytest.approx(8.0)
        assert result["base_min_odp_hours"] == pytest.approx(22.0)

    def test_small_shift_below_threshold_adds_nothing(self):
        result = calc(
            appendix="2", acclimatisation_state="acclimatised",
            fdp_start_offset_hours=8, odp_start_offset_hours=6,
            preceding_fdp=fdp(10, "away"),
        )
        assert result["displacement"]["added_hours"] == pytest.approx(0.0)
        assert result["displacement"]["status"] == "computed"

    def test_missing_offsets_report_data_unavailable_not_zero(self):
        """
        A computed zero and an unknown must be distinguishable. v0.5.0 emitted
        only a prose note, which a consumer cannot act on.
        """
        result = calc(
            appendix="2", acclimatisation_state="unknown",
            preceding_fdp=fdp(10, "away"),
        )
        assert result["displacement"]["status"] == "data_unavailable"
        assert result["displacement"]["displacement_hours"] is None
        assert "lower bound" in result["displacement"]["detail"]

    def test_appendix_3_reports_displacement_not_applicable(self):
        result = calc(appendix="3", preceding_fdp=fdp(10, "away"))
        assert result["displacement"]["status"] == "not_applicable"
        assert result["displacement"]["added_hours"] == 0.0

    @pytest.mark.parametrize("field", ["fdp_start_offset_hours", "odp_start_offset_hours"])
    def test_offsets_are_range_checked(self, field):
        response = client.post(
            f"{BASE}/calculate/min-off-duty",
            json={"appendix": "2", "preceding_fdp": fdp(10, "away"), field: 50},
        )
        assert response.status_code == 422
        assert field in response.text


# ═══════════════════════════════════════════════════════════════════════
# S15 — Appendix 2 §10.4(c) omitted entirely
# ═══════════════════════════════════════════════════════════════════════

class TestS15Appendix2Condition10_4_c:
    """
    v0.5.0 granted the reduction with three conditions and cited §10.5 (the
    recovery rule). §10.4 has four, and the request's own
    acclimatisation_state: "unknown" contradicts (c).
    """

    def test_unknown_state_blocks_the_reduction(self):
        result = calc(
            appendix="2",
            acclimatisation_state="unknown",
            preceding_fdp=fdp(14, "away"),
        )
        reduction = result["reduction_applicable"]
        assert reduction["eligible"] is False  # v0.5.0 said True
        assert "§10.4(c)" in [c["clause"] for c in reduction["conditions_failed"]]
        assert "§10.4(c)" in reduction["reason"]

    def test_citation_is_10_4_not_10_5(self):
        result = calc(
            appendix="2", acclimatisation_state="acclimatised",
            preceding_fdp=fdp(14, "away"),
        )
        assert result["reduction_applicable"]["clause"] == "§10.4"  # was §10.5

    def test_acclimatised_enumerates_four_conditions(self):
        result = calc(
            appendix="2", acclimatisation_state="acclimatised",
            preceding_fdp=fdp(14, "away"),
        )
        reduction = result["reduction_applicable"]
        assert [c["clause"] for c in reduction["conditions_verified"]] == [
            "§10.4(a)", "§10.4(b)", "§10.4(c)",
        ]
        assert [c["clause"] for c in reduction["conditions_caller_must_verify"]] == [
            "§10.4(d)",
        ]

    def test_appendix_3_keeps_three_conditions(self):
        """§8.4 has no acclimatisation condition. The lists are not the same."""
        result = calc(appendix="3", preceding_fdp=fdp(14, "away"))
        reduction = result["reduction_applicable"]
        total = (
            len(reduction["conditions_verified"])
            + len(reduction["conditions_failed"])
            + len(reduction["conditions_caller_must_verify"])
        )
        assert total == 3
        assert "acclimatised" not in str(reduction).lower()

    def test_appendix_2_nine_hour_rule_also_requires_acclimatisation(self):
        """§10.3(b) is the same asymmetry on the 9h provision."""
        result = calc(
            appendix="2",
            acclimatisation_state="unknown",
            preceding_fdp=fdp(10, "away"),
            preceding_off_duty={"duration_hours": 13, "included_local_night": True},
        )
        reduction = result["reduction_applicable"]
        assert reduction["eligible"] is False
        assert "§10.3(b)" in [c["clause"] for c in reduction["conditions_failed"]]

    def test_appendix_3_nine_hour_rule_has_four_conditions(self):
        result = calc(
            appendix="3",
            preceding_fdp=fdp(10, "away"),
            preceding_off_duty={"duration_hours": 13, "included_local_night": True},
        )
        reduction = result["reduction_applicable"]
        assert reduction["eligible"] is True
        assert [c["clause"] for c in reduction["conditions_verified"]] == [
            "§8.3(a)", "§8.3(b)", "§8.3(c)",
        ]
        assert [c["clause"] for c in reduction["conditions_caller_must_verify"]] == [
            "§8.3(d)",
        ]


# ═══════════════════════════════════════════════════════════════════════
# §8.3 / §10.3 duty-total gate — found during Phase 2, not in the spec
# ═══════════════════════════════════════════════════════════════════════

class TestNineHourReductionDutyGate:
    """
    §8.3 opens 'Despite subclause 8.1, if the sum of an FCM's FDP ... does not
    exceed 10 hours'. v0.5.0 never applied that gate, so a 14h FDP requiring
    15.0h under §8.2 was reduced to 9.0h — a six-hour under-rest, and the
    largest single error found in this remediation.
    """

    def test_fourteen_hour_fdp_cannot_reach_the_nine_hour_reduction(self):
        result = calc(
            preceding_fdp=fdp(14, "away"),
            preceding_off_duty={"duration_hours": 13, "included_local_night": True},
        )
        assert result["final_min_odp_hours"] == pytest.approx(15.0)  # v0.5.0: 9.0
        reduction = result["reduction_applicable"]
        assert reduction["clause"] == "§8.4"
        assert reduction["reduced_min_odp_hours"] == pytest.approx(14.0)

    @pytest.mark.parametrize("duration", [10.5, 11.0, 12.0, 13.0])
    def test_gate_holds_just_above_ten_hours(self, duration):
        result = calc(
            preceding_fdp=fdp(duration, "away"),
            preceding_off_duty={"duration_hours": 13, "included_local_night": True},
        )
        reduction = result["reduction_applicable"]
        if reduction is not None:
            assert reduction["clause"] != "§8.3", (
                f"§8.3 must not apply at {duration}h of duty"
            )
        assert result["final_min_odp_hours"] >= 10.0

    def test_gate_permits_exactly_ten_hours(self):
        result = calc(
            preceding_fdp=fdp(10, "away"),
            preceding_off_duty={"duration_hours": 13, "included_local_night": True},
        )
        assert result["reduction_applicable"]["clause"] == "§8.3"
        assert result["reduction_applicable"]["reduced_min_odp_hours"] == pytest.approx(9.0)

    def test_validator_rejects_a_nine_hour_odp_after_a_fourteen_hour_fdp(self):
        body = client.post(
            f"{BASE}/validate/off-duty",
            json={
                "appendix": "3",
                "actual_off_duty_hours": 9.5,
                "reduction_claimed": True,
                "preceding_fdp": {
                    "start_utc": "2026-03-24T00:00:00Z",
                    "end_utc": "2026-03-24T14:00:00Z",
                    "duration_hours": 14,
                    "location": "away",
                },
                "preceding_off_duty": {
                    "duration_hours": 13,
                    "included_local_night": True,
                },
            },
        ).json()
        assert body["valid"] is False
        check = next(c for c in body["checks"] if c["check"] == "odp_meets_minimum")
        assert check["limit"] == pytest.approx(14.0)


# ═══════════════════════════════════════════════════════════════════════
# Citation hygiene on this code path (S13 rows for min-off-duty)
# ═══════════════════════════════════════════════════════════════════════

class TestOdpCitations:

    @pytest.mark.parametrize(
        "appendix,acclim,duration,location,expected",
        [
            ("3", "not_applicable", 10, "away", "§8.1(a)"),
            ("3", "not_applicable", 10, "home_base", "§8.1(b)"),   # was §8.1a
            ("3", "not_applicable", 14, "away", "§8.2"),           # was §8.1b
            ("2", "acclimatised", 10, "away", "§10.1(a)"),
            ("2", "acclimatised", 10, "home_base", "§10.1(b)"),
            ("2", "acclimatised", 14, "away", "§10.2(a)"),         # was §10.1b
            ("2", "unknown", 10, "away", "§10.1(c)"),
            ("2", "unknown", 14, "away", "§10.2(b)"),
        ],
    )
    def test_base_clause_citations(self, appendix, acclim, duration, location, expected):
        result = calc(
            appendix=appendix,
            acclimatisation_state=acclim,
            preceding_fdp=fdp(duration, location),
        )
        assert result["clause"] == expected

    def test_no_internal_rule_identifier_leaks(self):
        """No citation may match the §N.word shape that produced '§3.night'."""
        import re

        pattern = re.compile(r"^§\d+\.[a-z]+$")
        for appendix in ("1", "2", "3", "4", "4A", "4B", "5", "5A", "6"):
            result = calc(
                appendix=appendix,
                acclimatisation_state="acclimatised" if appendix == "2" else "not_applicable",
                preceding_fdp=fdp(
                    14, "away",
                    split_duty={
                        "duration_hours": 4,
                        "accommodation": "sleeping",
                        "overlaps_2300_0529": False,
                    },
                ),
            )
            citations = [result["clause"], result.get("split_duty_credit_clause")]
            if result.get("reduction_applicable"):
                citations.append(result["reduction_applicable"]["clause"])
                for key in (
                    "conditions_verified",
                    "conditions_failed",
                    "conditions_caller_must_verify",
                ):
                    citations += [c["clause"] for c in result["reduction_applicable"][key]]
            for citation in citations:
                if citation:
                    assert not pattern.match(citation), (
                        f"Appendix {appendix} emitted internal identifier {citation!r}"
                    )
