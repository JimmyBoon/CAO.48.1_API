"""
Unit tests for the off-duty period calculation engine.

Tests the calculate_min_off_duty() function with various appendices,
locations, split duty scenarios, and reduction eligibility.
"""

import pytest

from app.engines.off_duty_calculator import calculate_min_off_duty


class TestAppendix1:
    """Appendix 1 — Basic Limits (simple fixed 12h)."""

    def test_fixed_minimum(self):
        result = calculate_min_off_duty(
            appendix="1",
            preceding_fdp_duration_hours=8.0,
        )
        assert result["base_min_odp_hours"] == 12.0
        assert result["final_min_odp_hours"] == 12.0

    def test_fixed_regardless_of_duration(self):
        result = calculate_min_off_duty(
            appendix="1",
            preceding_fdp_duration_hours=14.0,
        )
        assert result["final_min_odp_hours"] == 12.0


class TestAppendix3:
    """Appendix 3 — Multi-Pilot Except Complex (home/away)."""

    def test_away_under_12h(self):
        """Away from home base, <=12h -> 10h."""
        result = calculate_min_off_duty(
            appendix="3",
            preceding_fdp_duration_hours=10.0,
            post_fdp_duty_hours=0.5,
            location="away",
        )
        assert result["base_min_odp_hours"] == 10.0
        assert result["exceeds_12h"] is False

    def test_home_under_12h(self):
        """At home base, <=12h -> 12h."""
        result = calculate_min_off_duty(
            appendix="3",
            preceding_fdp_duration_hours=10.0,
            location="home_base",
        )
        assert result["base_min_odp_hours"] == 12.0

    def test_over_12h_formula(self):
        """Over 12h -> 12h + 1.5 * excess."""
        result = calculate_min_off_duty(
            appendix="3",
            preceding_fdp_duration_hours=14.0,
            post_fdp_duty_hours=0.0,
            location="away",
        )
        # 14h total, excess = 2h, base = 12 + 1.5*2 = 15h
        assert result["exceeds_12h"] is True
        assert result["base_min_odp_hours"] == 15.0

    def test_split_duty_credit(self):
        """Split duty sleeping should give 2h credit."""
        result = calculate_min_off_duty(
            appendix="3",
            preceding_fdp_duration_hours=10.0,
            location="away",
            split_duty_duration_hours=4.0,
            split_duty_accommodation="sleeping",
        )
        assert result["split_duty_credit_hours"] == 2.0
        assert result["effective_duration_for_calc_hours"] == 8.0  # 10 - 2

    def test_reduction_to_9h_eligible(self):
        """Reduction to 9h with all conditions met."""
        result = calculate_min_off_duty(
            appendix="3",
            preceding_fdp_duration_hours=10.0,
            location="away",
            preceding_odp_duration_hours=13.0,
            preceding_odp_included_night=True,
            following_includes_local_night=True,
        )
        assert result["reduction_applicable"] is not None
        assert result["reduction_applicable"]["eligible"] is True
        assert result["reduction_applicable"]["reduced_min_odp_hours"] == 9.0
        assert result["final_min_odp_hours"] == 9.0

    def test_reduction_not_eligible_home_base(self):
        """Reduction to 9h not eligible at home base."""
        result = calculate_min_off_duty(
            appendix="3",
            preceding_fdp_duration_hours=10.0,
            location="home_base",
            preceding_odp_duration_hours=13.0,
            preceding_odp_included_night=True,
            following_includes_local_night=True,
        )
        # At home base -> not eligible for 9h reduction
        if result["reduction_applicable"] is not None:
            assert result["reduction_applicable"]["eligible"] is False or \
                   result["reduction_applicable"]["reduced_min_odp_hours"] != 9.0


class TestAppendix2:
    """Appendix 2 — Multi-Pilot Operations (home/away with displacement)."""

    def test_away_under_12h(self):
        result = calculate_min_off_duty(
            appendix="2",
            preceding_fdp_duration_hours=10.0,
            location="away",
        )
        assert result["base_min_odp_hours"] == 10.0

    def test_displacement_note(self):
        """Displacement time should be noted."""
        result = calculate_min_off_duty(
            appendix="2",
            preceding_fdp_duration_hours=10.0,
            location="away",
        )
        assert any("Displacement" in note or "displacement" in note
                    for note in result["calculation_notes"])


class TestAppendix4:
    """Appendix 4 — Any Operations (home/away with displacement)."""

    def test_away_under_12h(self):
        result = calculate_min_off_duty(
            appendix="4",
            preceding_fdp_duration_hours=10.0,
            location="away",
        )
        assert result["base_min_odp_hours"] == 10.0


class TestAppendix4A:
    """Appendix 4A — Balloon Operations (simple 10h)."""

    def test_fixed_minimum(self):
        result = calculate_min_off_duty(
            appendix="4A",
            preceding_fdp_duration_hours=6.0,
        )
        assert result["final_min_odp_hours"] == 10.0


class TestAppendix4B:
    """Appendix 4B — Medical Transport (night branching)."""

    def test_base_without_night(self):
        result = calculate_min_off_duty(
            appendix="4B",
            preceding_fdp_duration_hours=10.0,
            location="away",
        )
        assert result["base_min_odp_hours"] == 10.0

    def test_extension_penalty(self):
        """Extension hours add ODP penalty."""
        result = calculate_min_off_duty(
            appendix="4B",
            preceding_fdp_duration_hours=12.0,
            location="away",
            was_extended=True,
            extension_hours=1.0,
        )
        # Base 10h + 1h extension = 2 x 30min units -> +2h penalty
        assert result["base_min_odp_hours"] > 10.0


class TestAppendix5:
    """Appendix 5 — Aerial Work (night branching)."""

    def test_base_without_night(self):
        result = calculate_min_off_duty(
            appendix="5",
            preceding_fdp_duration_hours=10.0,
        )
        assert result["base_min_odp_hours"] == 10.0

    def test_reduction_to_12h(self):
        """ODP >12h can be reduced to 12h under conditions."""
        result = calculate_min_off_duty(
            appendix="5",
            preceding_fdp_duration_hours=14.0,
            was_extended=True,
            extension_hours=1.0,
        )
        if result["base_min_odp_hours"] > 12:
            assert result["reduction_applicable"] is not None
            assert result["reduction_applicable"]["reduced_min_odp_hours"] == 12.0


class TestAppendix5A:
    """Appendix 5A — Daylight Aerial Work (simple 10h)."""

    def test_fixed_minimum(self):
        result = calculate_min_off_duty(
            appendix="5A",
            preceding_fdp_duration_hours=12.0,
        )
        assert result["final_min_odp_hours"] == 10.0


class TestAppendix6:
    """Appendix 6 — Flight Training (formula)."""

    def test_under_12h(self):
        """<=12h -> 12h."""
        result = calculate_min_off_duty(
            appendix="6",
            preceding_fdp_duration_hours=10.0,
        )
        assert result["base_min_odp_hours"] == 12.0
        assert result["final_min_odp_hours"] == 12.0

    def test_over_12h_formula(self):
        """Over 12h -> 12h + 1.5 * excess."""
        result = calculate_min_off_duty(
            appendix="6",
            preceding_fdp_duration_hours=14.0,
        )
        # 14h total, excess = 2h, base = 12 + 1.5*2 = 15h
        assert result["base_min_odp_hours"] == 15.0


class TestCalculationNotes:
    """Verify calculation notes are populated."""

    def test_notes_present(self):
        result = calculate_min_off_duty(
            appendix="3",
            preceding_fdp_duration_hours=10.0,
            location="away",
        )
        assert len(result["calculation_notes"]) > 0

    def test_invalid_appendix_raises(self):
        with pytest.raises(ValueError):
            calculate_min_off_duty(
                appendix="99",
                preceding_fdp_duration_hours=10.0,
            )
