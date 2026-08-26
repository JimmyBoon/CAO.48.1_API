"""
Phase 3 remediation regression tests — S5, S6, S7, S12, plus the Appendix 5
extension gap found while implementing S5.
"""

import re

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


def validate_fdp(**overrides):
    body = {
        "appendix": "3",
        "fdp_start_utc": "2026-03-23T23:00:00Z",
        "fdp_end_utc": "2026-03-24T09:00:00Z",
        "local_time_offset_hours": 8,
        "sectors": 2,
    }
    body.update(overrides)
    response = client.post(f"{BASE}/validate/fdp", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def check(body, name):
    return next(c for c in body["checks"] if c["check"] == name)


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


# ═══════════════════════════════════════════════════════════════════════
# S5 — Appendix 4B extensions denied and credited simultaneously
# ═══════════════════════════════════════════════════════════════════════

class TestS5Appendix4BExtensions:
    """
    v0.5.0 said "Appendix 4B does not permit FDP extensions" while passing
    fdp_within_limit at 18.0 <= 18.0. Clause 3 of Appendix 4B is titled
    "Extensions"; the denial was factually wrong and the 16h ceiling in
    §3.2(c) was never enforced.
    """

    PAYLOAD = {
        "appendix": "4B",
        "single_pilot": False,
        "sectors": 2,
        "fdp_start_utc": "2026-03-23T23:00:00Z",
        "fdp_end_utc": "2026-03-24T17:00:00Z",
        "local_time_offset_hours": 8,
        "extension": {"type": "urgent", "hours_used": 4, "pre_planned": False},
    }

    def test_urgent_extension_is_permitted_but_capped_at_16h(self):
        body = client.post(f"{BASE}/validate/fdp", json=self.PAYLOAD).json()

        assert body["valid"] is False
        duration = check(body, "fdp_within_limit")
        assert duration["passed"] is False       # v0.5.0 passed this at 18.0
        assert duration["limit"] == pytest.approx(16.0)
        assert duration["clause"] == "§3.2"

        # The extension itself is lawful — 4h is exactly what §3.2 grants.
        assert check(body, "extension_permitted")["passed"] is True

    def test_no_blanket_denial_message(self):
        body = client.post(f"{BASE}/validate/fdp", json=self.PAYLOAD).json()
        assert "does not permit FDP extensions" not in str(body)

    def test_retired_message_is_gone_from_the_codebase(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent
        for path in list(root.glob("app/**/*.py")) + list(root.glob("tests/**/*.py")):
            if path.name == pathlib.Path(__file__).name:
                continue
            assert "does not permit FDP extensions" not in path.read_text(), path

    def test_unforeseen_multi_pilot_two_hours_is_permitted(self):
        body = validate_fdp(
            appendix="4B", single_pilot=False,
            extension={"type": "unforeseen", "hours_used": 2.0},
        )
        assert check(body, "extension_permitted")["passed"] is True

    def test_unforeseen_single_pilot_is_limited_to_one_hour(self):
        body = validate_fdp(
            appendix="4B", single_pilot=True,
            extension={"type": "unforeseen", "hours_used": 2.0},
        )
        extension = check(body, "extension_permitted")
        assert extension["passed"] is False
        assert extension["limit"] == pytest.approx(1.0)
        assert "§3.1" in extension["clause"]

    @pytest.mark.parametrize("single_pilot,expected", [(False, 2.0), (True, 1.0)])
    def test_calculator_reports_the_real_allowance(self, single_pilot, expected):
        result = max_fdp(
            appendix="4B", fdp_start_utc="2026-03-23T23:00:00Z",
            single_pilot=single_pilot,
        )
        assert result["max_extension_hours"] == pytest.approx(expected)  # was 0.0

    def test_both_provisions_are_described(self):
        result = max_fdp(appendix="4B", fdp_start_utc="2026-03-23T23:00:00Z")
        provisions = {p["type"]: p for p in result["extension_options"]["provisions"]}
        assert provisions["unforeseen"]["clause"] == "§3.1"
        # §3.1's 16h proviso attaches to §3.1(b) only; §3.1(a) has no ceiling.
        assert provisions["unforeseen"]["extended_fdp_ceiling_hours"] is None
        assert provisions["urgent"]["clause"] == "§3.2"
        assert provisions["urgent"]["extended_fdp_ceiling_hours"] == pytest.approx(16.0)

    def test_unverifiable_conditions_are_surfaced(self):
        result = max_fdp(appendix="4B", fdp_start_utc="2026-03-23T23:00:00Z")
        clauses = [
            c["clause"]
            for c in result["extension_options"]["conditions_caller_must_verify"]
        ]
        assert {"§3.2(a)", "§3.2(b)", "§3.3"} <= set(clauses)
        assert result["extension_options"]["clause_cumulative_crosscheck"] == "§3.6"

    def test_cumulative_crosscheck_is_flagged_as_unchecked(self):
        body = client.post(f"{BASE}/validate/fdp", json=self.PAYLOAD).json()
        assert any("§3.6" in w for w in body["warnings"])

    def test_urgent_type_is_rejected_outside_appendix_4b(self):
        body = validate_fdp(
            appendix="3", extension={"type": "urgent", "hours_used": 4.0},
        )
        extension = check(body, "extension_permitted")
        assert extension["passed"] is False
        assert "4B" in extension["detail"]

    def test_appendix_5_extension_gap(self):
        """
        Found during Phase 3, outside the spec: Appendix 5 clause 3 is also
        titled "Extensions" and §3.1 grants up to 2 hours. v0.5.0 carried
        max_extension_hours 0.0 there too.
        """
        result = max_fdp(appendix="5", fdp_start_utc="2026-03-23T23:00:00Z")
        assert result["max_extension_hours"] == pytest.approx(2.0)
        assert result["extension_options"]["provisions"][0]["clause"] == "§3.1"

    def test_appendix_4a_genuinely_has_no_extension(self):
        result = max_fdp(appendix="4A", fdp_start_utc="2026-03-23T23:00:00Z")
        assert result["max_extension_hours"] == pytest.approx(0.0)
        assert result["extension_options"]["available"] is False


# ═══════════════════════════════════════════════════════════════════════
# S6 — 6th consecutive early start permitted
# ═══════════════════════════════════════════════════════════════════════

class TestS6ConsecutiveEarlyStarts:
    """
    v0.5.0 noted "5th+ consecutive early start: FDP reduced by 4h" and
    returned a limit with no violation. §11.3 enumerates a 4th and a 5th.
    There is no 6th; §11.1 prohibits it.
    """

    EARLY = {"fdp_start_utc": "2026-03-23T21:30:00Z", "local_time_offset_hours": 8}

    @pytest.mark.parametrize(
        "preceding,expected_limit",
        [(0, 11.0), (1, 11.0), (2, 11.0), (3, 9.0), (4, 7.0)],
    )
    def test_reductions_up_to_the_fifth_early_start(self, preceding, expected_limit):
        result = max_fdp(consecutive_early_starts=preceding, **self.EARLY)
        assert result["final_max_fdp_hours"] == pytest.approx(expected_limit)
        assert result["violations"] == []

    @pytest.mark.parametrize("preceding", [5, 6, 12])
    def test_sixth_and_beyond_is_a_hard_violation(self, preceding):
        result = max_fdp(consecutive_early_starts=preceding, **self.EARLY)
        assert result["violations"], "v0.5.0 clamped the reduction instead"
        violation = result["violations"][0]
        assert violation["clause"] == "§11.1"
        assert violation["check"] == "consecutive_early_starts"

    def test_validator_reports_the_same_violation(self):
        body = validate_fdp(
            fdp_start_utc="2026-03-23T21:30:00Z",
            fdp_end_utc="2026-03-24T02:30:00Z",
            consecutive_early_starts=5,
        )
        assert body["valid"] is False
        assert any(v["clause"] == "§11.1" for v in body["violations"])

    @pytest.mark.parametrize(
        "appendix,clause", [("2", "§13.1"), ("3", "§11.1"), ("4", "§11.1"), ("6", "§10.1")]
    )
    def test_each_appendix_cites_its_own_clause(self, appendix, clause):
        body = {"consecutive_early_starts": 5, "sectors": 2, **self.EARLY}
        if appendix == "2":
            body["acclimatisation"] = {
                "state": "acclimatised", "acclimatised_time_offset_hours": 8,
            }
        result = max_fdp(appendix=appendix, **body)
        assert [v["clause"] for v in result["violations"]] == [clause]

    def test_no_five_plus_string_survives(self):
        for preceding in range(0, 8):
            result = max_fdp(consecutive_early_starts=preceding, **self.EARLY)
            assert "5th+" not in str(result)

    def test_non_early_start_is_unaffected(self):
        result = max_fdp(consecutive_early_starts=9)  # 1000 local, not early
        assert result["violations"] == []
        assert result["wocl_early_start_reduction_hours"] == pytest.approx(0.0)


# ═══════════════════════════════════════════════════════════════════════
# S7 — Appendix 3 §3.4(a) split-duty gate not enforced
# ═══════════════════════════════════════════════════════════════════════

class TestS7SplitDutyNightGate:
    """
    v0.5.0 tested `if overlaps_night and duration >= 7`, so a 5h
    night-overlapping rest fell through to the ordinary §3.1 branch and
    collected the full increase. §3.1 and §3.3 both open "Subject to
    subclause 3.4" — §3.4(a) is a gate on the whole provision.
    """

    def test_short_sleeping_rest_overlapping_night_earns_nothing(self):
        result = max_fdp(split_duty=split(5, "sleeping", overlaps=True))
        assert result["final_max_fdp_hours"] == pytest.approx(13.0)  # was 16.0

    def test_resting_rest_overlapping_night_earns_nothing(self):
        """Not even the §3.3 half-credit — §3.4(a) requires sleeping."""
        result = max_fdp(split_duty=split(5, "resting", overlaps=True))
        assert result["final_max_fdp_hours"] == pytest.approx(13.0)  # was 15.0

    def test_absence_of_increase_is_auditable(self):
        result = max_fdp(split_duty=split(5, "sleeping", overlaps=True))
        adjustment = result["adjustments"][0]
        assert adjustment["adjustment_hours"] == pytest.approx(0.0)
        assert adjustment["clause"] == "§3.4(a)"

    def test_validator_emits_a_violation(self):
        body = validate_fdp(
            fdp_start_utc="2026-03-24T02:00:00Z",
            fdp_end_utc="2026-03-24T18:00:00Z",
            split_duty=split(5, "sleeping", overlaps=True),
        )
        assert any(v["clause"] == "§3.4(a)" for v in body["violations"])

    def test_seven_hour_sleeping_rest_still_reaches_16h(self):
        result = max_fdp(split_duty=split(7, "sleeping", overlaps=True))
        assert result["final_max_fdp_hours"] == pytest.approx(16.0)
        assert result["adjustments"][0]["clause"] == "§3.4(b)"

    def test_non_overlapping_rest_is_unaffected(self):
        result = max_fdp(split_duty=split(5, "sleeping", overlaps=False))
        assert result["final_max_fdp_hours"] == pytest.approx(16.0)
        assert result["adjustments"][0]["clause"] == "§3.1"

    def test_resting_clause_is_3_3_not_3_2(self):
        """§3.2 is the ODP credit. The resting increase is §3.3."""
        result = max_fdp(split_duty=split(4, "resting"))
        assert result["adjustments"][0]["clause"] == "§3.3"

    def test_odp_credit_interaction_is_not_regressed(self):
        """§3.4(c): a night-overlapping split rest forfeits the 2h ODP credit."""
        body = client.post(
            f"{BASE}/calculate/min-off-duty",
            json={
                "appendix": "3",
                "preceding_fdp": {
                    "start_utc": "2026-03-24T00:00:00Z",
                    "end_utc": "2026-03-24T14:00:00Z",
                    "duration_hours": 14,
                    "location": "away",
                    "split_duty": {
                        "duration_hours": 7,
                        "accommodation": "sleeping",
                        "overlaps_2300_0529": True,
                    },
                },
            },
        ).json()
        assert body["split_duty_credit_hours"] == pytest.approx(0.0)
        assert body["base_min_odp_hours"] == pytest.approx(15.0)


# ═══════════════════════════════════════════════════════════════════════
# S12 — fdp_within_limit credits extensions ruled unlawful
# ═══════════════════════════════════════════════════════════════════════

class TestS12ExtensionNotDoubleCounted:
    """
    v0.5.0 reported extension_permitted failed (2.0 > 1.0) and
    fdp_within_limit passed at 15.0 <= 15.0 in the same response — the
    duration check credited the extension the adjacent check had rejected.
    """

    OVER_LIMIT = {
        "fdp_start_utc": "2026-03-23T23:00:00Z",   # 0700 local, base 13h
        "fdp_end_utc": "2026-03-24T14:00:00Z",     # 15h actual
    }

    def test_duration_is_measured_against_the_permitted_extension(self):
        body = validate_fdp(
            extension={"type": "unforeseen", "hours_used": 2.0}, **self.OVER_LIMIT
        )
        duration = check(body, "fdp_within_limit")
        assert duration["passed"] is False           # v0.5.0 passed this
        assert duration["limit"] == pytest.approx(14.0)   # 13 base + 1 permitted
        assert check(body, "extension_permitted")["passed"] is False

    def test_detail_names_both_figures(self):
        body = validate_fdp(
            extension={"type": "unforeseen", "hours_used": 2.0}, **self.OVER_LIMIT
        )
        detail = check(body, "fdp_within_limit")["detail"]
        assert "1.00h permitted extension" in detail
        assert "2.00h requested" in detail

    def test_a_lawful_extension_still_counts(self):
        body = validate_fdp(
            extension={"type": "unforeseen", "hours_used": 1.0},
            fdp_start_utc="2026-03-23T23:00:00Z",
            fdp_end_utc="2026-03-24T13:00:00Z",   # exactly 14h
        )
        duration = check(body, "fdp_within_limit")
        assert duration["passed"] is True
        assert duration["limit"] == pytest.approx(14.0)
        assert check(body, "extension_permitted")["passed"] is True

    def test_no_check_consumes_a_rejected_value(self):
        """
        Response-level invariant (§8.5): if a check failed, no other check's
        limit may be computed from the value it rejected.
        """
        cases = [
            {"extension": {"type": "unforeseen", "hours_used": h}, **self.OVER_LIMIT}
            for h in (1.0, 2.0, 4.0, 10.0)
        ]
        for case in cases:
            body = validate_fdp(**case)
            extension = check(body, "extension_permitted")
            if extension["passed"]:
                continue
            duration = check(body, "fdp_within_limit")
            rejected = case["extension"]["hours_used"]
            assert duration["limit"] < 13.0 + rejected, (
                f"limit {duration['limit']} still credits the rejected "
                f"{rejected}h extension"
            )


# ═══════════════════════════════════════════════════════════════════════
# Citation hygiene on the FDP path
# ═══════════════════════════════════════════════════════════════════════

class TestFdpCitations:

    INTERNAL_ID = re.compile(r"^§\d+\.[a-z]+$")

    def test_no_internal_rule_identifier_leaks(self):
        """'§3.night' was an internal rule id in a user-facing field."""
        for appendix in ("1", "2", "3", "4", "4A", "4B", "5", "5A", "6"):
            body = {"appendix": appendix, "sectors": 2,
                    "fdp_start_utc": "2026-03-24T02:00:00Z",
                    "local_time_offset_hours": 8}
            if appendix == "2":
                body["acclimatisation"] = {
                    "state": "acclimatised", "acclimatised_time_offset_hours": 8,
                }
            for overlaps in (False, True):
                for accommodation in ("sleeping", "resting"):
                    result = max_fdp(
                        **body,
                        split_duty=split(5, accommodation, overlaps=overlaps),
                    )
                    for adjustment in result["adjustments"]:
                        assert not self.INTERNAL_ID.match(adjustment["clause"]), (
                            f"Appendix {appendix} emitted {adjustment['clause']!r}"
                        )

    def test_no_generic_appendix_label_where_a_clause_exists(self):
        body = validate_fdp(extension={"type": "unforeseen", "hours_used": 1.0})
        extension = check(body, "extension_permitted")
        assert extension["clause"] == "§5.3(a)"   # was "CAO 48.1 Appendix 3"
