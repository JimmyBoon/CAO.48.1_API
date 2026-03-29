"""
Unit tests for the FDP calculation engine.

Tests the calculate_max_fdp() function directly with various appendices,
time bands, sector counts, split duty scenarios, and WOCL reductions.
"""

import pytest

from app.engines.fdp_calculator import calculate_max_fdp


class TestAppendix1:
    """Appendix 1 — Basic Limits."""

    def test_basic_daytime(self):
        """0600-1359 local -> 9h."""
        result = calculate_max_fdp(
            appendix="1",
            fdp_start_utc="2026-03-28T22:00:00Z",  # 0600 local at +8
            local_time_offset_hours=8,
            sectors=1,
        )
        assert result["base_max_fdp_hours"] == 9.0
        assert result["final_max_fdp_hours"] == 9.0
        assert result["max_extension_hours"] == 1.0

    def test_early_morning(self):
        """0000-0559 local -> 8h."""
        result = calculate_max_fdp(
            appendix="1",
            fdp_start_utc="2026-03-28T20:00:00Z",  # 0400 local at +8
            local_time_offset_hours=8,
            sectors=1,
        )
        assert result["base_max_fdp_hours"] == 8.0

    def test_late_afternoon(self):
        """1400-2359 local -> 8h."""
        result = calculate_max_fdp(
            appendix="1",
            fdp_start_utc="2026-03-28T08:00:00Z",  # 1600 local at +8
            local_time_offset_hours=8,
            sectors=1,
        )
        assert result["base_max_fdp_hours"] == 8.0


class TestAppendix3:
    """Appendix 3 — Multi-Pilot Operations Except Complex."""

    def test_peak_time_3_sectors(self):
        """0700-1259, 1-3 sectors -> 13h."""
        result = calculate_max_fdp(
            appendix="3",
            fdp_start_utc="2026-03-28T02:00:00Z",  # 1000 local at +8
            local_time_offset_hours=8,
            sectors=3,
        )
        assert result["base_max_fdp_hours"] == 13.0
        assert result["flight_time_limit_hours"] == 10.5

    def test_peak_time_8_sectors(self):
        """0700-1259, 8+ sectors -> 10.5h."""
        result = calculate_max_fdp(
            appendix="3",
            fdp_start_utc="2026-03-28T02:00:00Z",  # 1000 local at +8
            local_time_offset_hours=8,
            sectors=8,
        )
        assert result["base_max_fdp_hours"] == 10.5

    def test_night_time(self):
        """0000-0459, 1-3 sectors -> 10h."""
        result = calculate_max_fdp(
            appendix="3",
            fdp_start_utc="2026-03-28T18:00:00Z",  # 0200 local at +8
            local_time_offset_hours=8,
            sectors=2,
        )
        assert result["base_max_fdp_hours"] == 10.0

    def test_split_duty_sleeping(self):
        """4h sleeping rest -> +4h, capped at 16h."""
        result = calculate_max_fdp(
            appendix="3",
            fdp_start_utc="2026-03-28T22:00:00Z",  # 0600 local at +8
            local_time_offset_hours=8,
            sectors=3,
            split_duty={
                "rest_start_utc": "2026-03-29T04:00:00Z",
                "rest_end_utc": "2026-03-29T08:00:00Z",
                "accommodation": "sleeping",
                "duration_hours": 4,
                "overlaps_2300_0529": False,
            },
        )
        # Base 12h (0600 band, 1-3 sectors) + 4h = 16h (at cap)
        assert result["base_max_fdp_hours"] == 12.0
        assert result["final_max_fdp_hours"] == 16.0
        assert result["post_split_max_hours"] == 6.0

    def test_split_duty_resting(self):
        """3h resting rest -> +1.5h (50% of 3h)."""
        result = calculate_max_fdp(
            appendix="3",
            fdp_start_utc="2026-03-28T22:00:00Z",  # 0600 local at +8
            local_time_offset_hours=8,
            sectors=3,
            split_duty={
                "rest_start_utc": "2026-03-29T04:00:00Z",
                "rest_end_utc": "2026-03-29T07:00:00Z",
                "accommodation": "resting",
                "duration_hours": 3,
                "overlaps_2300_0529": False,
            },
        )
        assert result["base_max_fdp_hours"] == 12.0
        assert result["final_max_fdp_hours"] == 13.5  # 12 + 1.5

    def test_early_start_4th_consecutive(self):
        """4th consecutive early start -> -2h reduction."""
        result = calculate_max_fdp(
            appendix="3",
            fdp_start_utc="2026-03-28T21:00:00Z",  # 0500 local at +8
            local_time_offset_hours=8,
            sectors=3,
            consecutive_early_starts=3,  # this is the 4th
        )
        assert result["wocl_early_start_reduction_hours"] == 2.0
        assert result["base_max_fdp_hours"] == 11.0  # 0500 band
        assert result["final_max_fdp_hours"] == 9.0   # 11 - 2

    def test_early_start_5th_consecutive(self):
        """5th consecutive early start -> -4h reduction."""
        result = calculate_max_fdp(
            appendix="3",
            fdp_start_utc="2026-03-28T22:30:00Z",  # 0630 local at +8
            local_time_offset_hours=8,
            sectors=3,
            consecutive_early_starts=4,  # this is the 5th
        )
        assert result["wocl_early_start_reduction_hours"] == 4.0


class TestAppendix2:
    """Appendix 2 — Multi-Pilot Operations."""

    def test_acclimatised_peak(self):
        """Acclimatised, 0700-1259 acclimatised time, 1-3 sectors -> 13h."""
        result = calculate_max_fdp(
            appendix="2",
            fdp_start_utc="2026-03-28T02:00:00Z",  # 1000 at +8
            local_time_offset_hours=8,
            sectors=3,
            acclimatisation_state="acclimatised",
            acclimatised_time_offset_hours=8,
        )
        assert result["base_max_fdp_hours"] == 13.0
        assert result["flight_time_limit_hours"] == 10.5

    def test_unknown_under_30h(self):
        """Unknown acclimatisation, <30h off-duty, 1-3 sectors -> 10h."""
        result = calculate_max_fdp(
            appendix="2",
            fdp_start_utc="2026-03-28T02:00:00Z",
            local_time_offset_hours=8,
            sectors=3,
            acclimatisation_state="unknown",
            preceding_off_duty_hours=20,
        )
        assert result["base_max_fdp_hours"] == 10.0

    def test_unknown_over_30h(self):
        """Unknown acclimatisation, >=30h off-duty, 1-3 sectors -> 12h."""
        result = calculate_max_fdp(
            appendix="2",
            fdp_start_utc="2026-03-28T02:00:00Z",
            local_time_offset_hours=8,
            sectors=3,
            acclimatisation_state="unknown",
            preceding_off_duty_hours=32,
        )
        assert result["base_max_fdp_hours"] == 12.0

    def test_augmented_crew_class1_1fcm(self):
        """Augmented crew, acclimatised, 0700-1059, class 1, 1 FCM -> 16h."""
        result = calculate_max_fdp(
            appendix="2",
            fdp_start_utc="2026-03-28T00:00:00Z",  # 0800 at +8
            local_time_offset_hours=8,
            sectors=3,
            acclimatisation_state="acclimatised",
            acclimatised_time_offset_hours=8,
            augmented_crew={
                "additional_fcms": 1,
                "rest_facility_class": "class_1",
            },
        )
        assert result["base_max_fdp_hours"] == 16.0
        assert result["flight_time_limit_hours"] is None  # no limit for augmented


class TestAppendix4:
    """Appendix 4 — Any Operations."""

    def test_peak_time(self):
        """0800-1059 -> 11h."""
        result = calculate_max_fdp(
            appendix="4",
            fdp_start_utc="2026-03-28T01:00:00Z",  # 0900 at +8
            local_time_offset_hours=8,
            sectors=1,
        )
        assert result["base_max_fdp_hours"] == 11.0

    def test_night_time(self):
        """2300-0459 -> 8h."""
        result = calculate_max_fdp(
            appendix="4",
            fdp_start_utc="2026-03-28T16:00:00Z",  # 0000 at +8
            local_time_offset_hours=8,
            sectors=1,
        )
        assert result["base_max_fdp_hours"] == 8.0

    def test_split_duty_cap_15h(self):
        """Split duty sleeping cap is 15h for Appendix 4."""
        result = calculate_max_fdp(
            appendix="4",
            fdp_start_utc="2026-03-28T01:00:00Z",  # 0900 at +8
            local_time_offset_hours=8,
            sectors=1,
            split_duty={
                "rest_start_utc": "2026-03-28T06:00:00Z",
                "rest_end_utc": "2026-03-28T10:00:00Z",
                "accommodation": "sleeping",
                "duration_hours": 4,
                "overlaps_2300_0529": False,
            },
        )
        assert result["final_max_fdp_hours"] == 15.0  # 11 + 4 = 15 (at cap)
        assert result["post_split_max_hours"] == 5.0


class TestAppendix4A:
    """Appendix 4A — Balloon Operations."""

    def test_no_split(self):
        """No split duty -> 6h."""
        result = calculate_max_fdp(
            appendix="4A",
            fdp_start_utc="2026-03-28T22:00:00Z",
            local_time_offset_hours=8,
            sectors=1,
        )
        assert result["base_max_fdp_hours"] == 6.0
        assert result["max_extension_hours"] == 0.0

    def test_with_split(self):
        """With split duty -> 10h base (extension applied separately)."""
        result = calculate_max_fdp(
            appendix="4A",
            fdp_start_utc="2026-03-28T22:00:00Z",
            local_time_offset_hours=8,
            sectors=1,
            split_duty={
                "rest_start_utc": "2026-03-29T02:00:00Z",
                "rest_end_utc": "2026-03-29T06:00:00Z",
                "accommodation": "sleeping",
                "duration_hours": 4,
                "overlaps_2300_0529": False,
            },
        )
        assert result["base_max_fdp_hours"] == 10.0


class TestAppendix4B:
    """Appendix 4B — Medical Transport & Emergency Service Operations."""

    def test_single_pilot_peak(self):
        """Single pilot, 0700-1159 -> 12h."""
        result = calculate_max_fdp(
            appendix="4B",
            fdp_start_utc="2026-03-28T01:00:00Z",  # 0900 at +8
            local_time_offset_hours=8,
            sectors=1,
            single_pilot=True,
        )
        assert result["base_max_fdp_hours"] == 12.0

    def test_multi_pilot_1_2_sectors_peak(self):
        """Multi-pilot, 1-2 sectors, 0700-1159 -> 14h."""
        result = calculate_max_fdp(
            appendix="4B",
            fdp_start_utc="2026-03-28T01:00:00Z",
            local_time_offset_hours=8,
            sectors=2,
            single_pilot=False,
        )
        assert result["base_max_fdp_hours"] == 14.0

    def test_multi_pilot_3plus_sectors_peak(self):
        """Multi-pilot, 3+ sectors, 0700-1159 -> 13h."""
        result = calculate_max_fdp(
            appendix="4B",
            fdp_start_utc="2026-03-28T01:00:00Z",
            local_time_offset_hours=8,
            sectors=3,
            single_pilot=False,
        )
        assert result["base_max_fdp_hours"] == 13.0


class TestAppendix6:
    """Appendix 6 — Flight Training."""

    def test_peak_time(self):
        """0800-1059 -> 11h, flight time 7h."""
        result = calculate_max_fdp(
            appendix="6",
            fdp_start_utc="2026-03-28T01:00:00Z",  # 0900 at +8
            local_time_offset_hours=8,
            sectors=1,
        )
        assert result["base_max_fdp_hours"] == 11.0
        assert result["flight_time_limit_hours"] == 7.0

    def test_early_morning(self):
        """0500-0559 -> 9h."""
        result = calculate_max_fdp(
            appendix="6",
            fdp_start_utc="2026-03-28T21:00:00Z",  # 0500 at +8
            local_time_offset_hours=8,
            sectors=1,
        )
        assert result["base_max_fdp_hours"] == 9.0

    def test_wocl_rules_apply(self):
        """Appendix 6 has WOCL/early start rules."""
        result = calculate_max_fdp(
            appendix="6",
            fdp_start_utc="2026-03-28T21:00:00Z",  # 0500 at +8
            local_time_offset_hours=8,
            sectors=1,
            consecutive_early_starts=3,  # 4th early start
        )
        assert result["wocl_early_start_reduction_hours"] == 2.0


class TestAppendix5A:
    """Appendix 5A — Daylight Aerial Work."""

    def test_daylight_max(self):
        """Daylight max -> 14h."""
        result = calculate_max_fdp(
            appendix="5A",
            fdp_start_utc="2026-03-28T22:00:00Z",
            local_time_offset_hours=8,
            sectors=1,
        )
        assert result["base_max_fdp_hours"] == 14.0
        assert result["max_extension_hours"] == 1.0


class TestCalculationNotes:
    """Verify calculation notes are populated."""

    def test_notes_present(self):
        result = calculate_max_fdp(
            appendix="3",
            fdp_start_utc="2026-03-28T02:00:00Z",
            local_time_offset_hours=8,
            sectors=3,
        )
        assert len(result["calculation_notes"]) > 0
        assert any("Table 2.1" in note for note in result["calculation_notes"])

    def test_split_duty_notes(self):
        result = calculate_max_fdp(
            appendix="3",
            fdp_start_utc="2026-03-28T22:00:00Z",
            local_time_offset_hours=8,
            sectors=3,
            split_duty={
                "rest_start_utc": "2026-03-29T04:00:00Z",
                "rest_end_utc": "2026-03-29T08:00:00Z",
                "accommodation": "sleeping",
                "duration_hours": 4,
                "overlaps_2300_0529": False,
            },
        )
        assert any("Split duty" in note for note in result["calculation_notes"])
