"""
Unit tests for the off-duty period validator engine.

Tests validate_off_duty() directly — no HTTP layer.
Covers passing/failing ODPs and reduction eligibility checks.
"""

import pytest

from app.engines.off_duty_validator import validate_off_duty


class TestOffDutyValidatorPassingCases:
    """ODPs that meet or exceed the minimum — valid=True expected."""

    def test_appendix3_away_at_minimum(self):
        """10h actual ODP = 10h minimum (away, ≤12h FDP) — passes."""
        result = validate_off_duty(
            appendix="3",
            preceding_fdp_duration_hours=10.0,
            actual_off_duty_hours=10.0,
            location="away",
        )
        assert result["valid"] is True
        assert result["violations"] == []
        check = result["checks"][0]
        assert check["check"] == "odp_meets_minimum"
        assert check["passed"] is True
        assert check["actual"] == 10.0
        assert check["limit"] == 10.0

    def test_appendix3_home_at_minimum(self):
        """12h actual against 12h home minimum — passes."""
        result = validate_off_duty(
            appendix="3",
            preceding_fdp_duration_hours=10.0,
            actual_off_duty_hours=12.0,
            location="home_base",
        )
        assert result["valid"] is True

    def test_appendix1_fixed_minimum(self):
        """Appendix 1 fixed 12h minimum — 12h actual passes."""
        result = validate_off_duty(
            appendix="1",
            preceding_fdp_duration_hours=8.0,
            actual_off_duty_hours=12.0,
        )
        assert result["valid"] is True

    def test_appendix3_above_minimum(self):
        """14h actual well above 10h minimum — passes."""
        result = validate_off_duty(
            appendix="3",
            preceding_fdp_duration_hours=8.0,
            actual_off_duty_hours=14.0,
            location="away",
        )
        assert result["valid"] is True

    def test_calculation_notes_forwarded(self):
        """calculation_notes from the ODP calculator should be in the result."""
        result = validate_off_duty(
            appendix="3",
            preceding_fdp_duration_hours=10.0,
            actual_off_duty_hours=10.0,
            location="away",
        )
        assert len(result["calculation_notes"]) > 0

    def test_only_odp_check_without_reduction(self):
        """Without reduction_claimed=True, only odp_meets_minimum is run."""
        result = validate_off_duty(
            appendix="3",
            preceding_fdp_duration_hours=10.0,
            actual_off_duty_hours=10.0,
            location="away",
        )
        check_ids = [c["check"] for c in result["checks"]]
        assert check_ids == ["odp_meets_minimum"]


class TestOffDutyValidatorFailingCases:
    """ODPs below the minimum — valid=False with violations."""

    def test_appendix3_below_minimum(self):
        """9h actual against 10h minimum (away) — fails."""
        result = validate_off_duty(
            appendix="3",
            preceding_fdp_duration_hours=10.0,
            actual_off_duty_hours=9.0,
            location="away",
        )
        assert result["valid"] is False
        assert len(result["violations"]) == 1
        v = result["violations"][0]
        assert v["check"] == "odp_meets_minimum"
        assert v["severity"] == "hard_limit"
        assert v["actual"] == 9.0
        assert v["limit"] == 10.0
        assert v["remediation"] != ""

    def test_appendix1_below_fixed_minimum(self):
        """10h actual against 12h fixed minimum — fails."""
        result = validate_off_duty(
            appendix="1",
            preceding_fdp_duration_hours=8.0,
            actual_off_duty_hours=10.0,
        )
        assert result["valid"] is False

    def test_failed_check_in_checks_list(self):
        """A failing check appears in the checks list with passed=False."""
        result = validate_off_duty(
            appendix="3",
            preceding_fdp_duration_hours=10.0,
            actual_off_duty_hours=9.0,
            location="away",
        )
        check = next(c for c in result["checks"] if c["check"] == "odp_meets_minimum")
        assert check["passed"] is False


class TestReductionEligibilityChecks:
    """Reduction condition checks (reduction_claimed=True)."""

    def test_reduction_eligible_and_conditions_met(self):
        """Appendix 3 — 9h reduction conditions met, 9h actual ODP — both checks pass."""
        result = validate_off_duty(
            appendix="3",
            preceding_fdp_duration_hours=6.0,
            actual_off_duty_hours=9.0,
            location="away",
            preceding_odp_duration_hours=13.0,
            preceding_odp_included_night=True,
            following_includes_local_night=True,
            reduction_claimed=True,
        )
        assert result["valid"] is True
        check_ids = {c["check"] for c in result["checks"]}
        assert "reduction_conditions_met" in check_ids
        red_check = next(c for c in result["checks"] if c["check"] == "reduction_conditions_met")
        assert red_check["passed"] is True

    def test_reduction_claimed_but_not_eligible(self):
        """Reduction claimed but conditions not satisfied — violation on reduction check."""
        result = validate_off_duty(
            appendix="3",
            preceding_fdp_duration_hours=6.0,
            actual_off_duty_hours=9.0,
            location="home_base",              # must be away for 9h reduction
            preceding_odp_duration_hours=8.0,  # must be ≥12h
            preceding_odp_included_night=False,
            following_includes_local_night=False,
            reduction_claimed=True,
        )
        red_check = next(c for c in result["checks"] if c["check"] == "reduction_conditions_met")
        assert red_check["passed"] is False
        assert any(v["check"] == "reduction_conditions_met" for v in result["violations"])

    def test_reduction_claimed_but_no_provision_appendix1(self):
        """Appendix 1 has no reduction provision — claiming one is a violation."""
        result = validate_off_duty(
            appendix="1",
            preceding_fdp_duration_hours=8.0,
            actual_off_duty_hours=12.0,
            reduction_claimed=True,
        )
        red_check = next(c for c in result["checks"] if c["check"] == "reduction_conditions_met")
        assert red_check["passed"] is False
        assert any(v["check"] == "reduction_conditions_met" for v in result["violations"])

    def test_two_checks_when_reduction_claimed(self):
        """When reduction_claimed=True, both checks are present in the checks list."""
        result = validate_off_duty(
            appendix="3",
            preceding_fdp_duration_hours=6.0,
            actual_off_duty_hours=10.0,
            location="away",
            reduction_claimed=True,
        )
        check_ids = [c["check"] for c in result["checks"]]
        assert "odp_meets_minimum" in check_ids
        assert "reduction_conditions_met" in check_ids


class TestAllAppendices:
    """Smoke test: all 9 appendices pass with a generous 14h actual ODP."""

    def test_all_appendices_valid_odp(self):
        for appendix in ["1", "2", "3", "4", "4A", "4B", "5", "5A", "6"]:
            result = validate_off_duty(
                appendix=appendix,
                preceding_fdp_duration_hours=6.0,
                actual_off_duty_hours=14.0,
                location="away",
            )
            assert result["valid"] is True, (
                f"Appendix {appendix}: expected valid=True, "
                f"got violations={result['violations']}"
            )

    def test_invalid_appendix_raises(self):
        with pytest.raises(ValueError, match="Unknown appendix"):
            validate_off_duty(
                appendix="99",
                preceding_fdp_duration_hours=8.0,
                actual_off_duty_hours=12.0,
            )
