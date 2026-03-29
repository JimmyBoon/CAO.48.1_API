"""
Unit tests for the FDP validator engine.

Tests validate_fdp() directly — no HTTP layer.
Covers passing/failing FDPs, extension validation, and flight time limit checks.
"""

import pytest

from app.engines.fdp_validator import validate_fdp


class TestFdpValidatorPassingCases:
    """FDPs within limits — valid=True expected."""

    def test_appendix3_at_limit(self):
        """12h FDP against 12h limit (0600 local, 1-3 sectors) — passes."""
        result = validate_fdp(
            appendix="3",
            fdp_start_utc="2026-03-28T22:00:00Z",   # 0600 local at +8
            fdp_end_utc="2026-03-29T10:00:00Z",       # exactly 12h
            local_time_offset_hours=8,
            sectors=3,
        )
        assert result["valid"] is True
        assert result["violations"] == []
        check = result["checks"][0]
        assert check["check"] == "fdp_within_limit"
        assert check["passed"] is True
        assert check["actual"] == 12.0
        assert check["limit"] == 12.0

    def test_appendix3_below_limit(self):
        """10h FDP against 12h limit — passes."""
        result = validate_fdp(
            appendix="3",
            fdp_start_utc="2026-03-28T22:00:00Z",
            fdp_end_utc="2026-03-29T08:00:00Z",       # 10h
            local_time_offset_hours=8,
            sectors=3,
        )
        assert result["valid"] is True

    def test_appendix1_within_limit(self):
        """9h FDP against 9h limit for Appendix 1 (0600 local) — passes."""
        result = validate_fdp(
            appendix="1",
            fdp_start_utc="2026-03-28T22:00:00Z",
            fdp_end_utc="2026-03-29T07:00:00Z",       # 9h
            local_time_offset_hours=8,
            sectors=1,
        )
        assert result["valid"] is True

    def test_calculation_notes_forwarded(self):
        """calculation_notes from the FDP calculator should appear in the result."""
        result = validate_fdp(
            appendix="3",
            fdp_start_utc="2026-03-28T22:00:00Z",
            fdp_end_utc="2026-03-29T10:00:00Z",
            local_time_offset_hours=8,
            sectors=3,
        )
        assert len(result["calculation_notes"]) > 0

    def test_only_fdp_check_when_no_extras(self):
        """With no extension and no flight time arg, only fdp_within_limit is run."""
        result = validate_fdp(
            appendix="3",
            fdp_start_utc="2026-03-28T22:00:00Z",
            fdp_end_utc="2026-03-29T10:00:00Z",
            local_time_offset_hours=8,
            sectors=3,
        )
        check_ids = [c["check"] for c in result["checks"]]
        assert check_ids == ["fdp_within_limit"]


class TestFdpValidatorFailingCases:
    """FDPs exceeding limits — valid=False with violations."""

    def test_appendix3_exceeds_limit(self):
        """13h FDP against 12h limit — fails with hard_limit violation."""
        result = validate_fdp(
            appendix="3",
            fdp_start_utc="2026-03-28T22:00:00Z",
            fdp_end_utc="2026-03-29T11:00:00Z",       # 13h
            local_time_offset_hours=8,
            sectors=3,
        )
        assert result["valid"] is False
        assert len(result["violations"]) == 1
        v = result["violations"][0]
        assert v["check"] == "fdp_within_limit"
        assert v["severity"] == "hard_limit"
        assert v["actual"] == 13.0
        assert v["limit"] == 12.0
        assert v["remediation"] != ""

    def test_failed_check_also_in_checks_list(self):
        """A failing check is in both violations and checks, with passed=False."""
        result = validate_fdp(
            appendix="3",
            fdp_start_utc="2026-03-28T22:00:00Z",
            fdp_end_utc="2026-03-29T11:00:00Z",
            local_time_offset_hours=8,
            sectors=3,
        )
        check = next(c for c in result["checks"] if c["check"] == "fdp_within_limit")
        assert check["passed"] is False


class TestExtensionValidation:
    """Extension-related checks."""

    def test_valid_unforeseen_extension(self):
        """13h FDP with 1h unforeseen extension against 12h base — valid."""
        result = validate_fdp(
            appendix="3",
            fdp_start_utc="2026-03-28T22:00:00Z",
            fdp_end_utc="2026-03-29T11:00:00Z",       # 13h = 12h + 1h ext
            local_time_offset_hours=8,
            sectors=3,
            extension={"type": "unforeseen", "hours_used": 1.0},
        )
        assert result["valid"] is True
        check_ids = {c["check"] for c in result["checks"]}
        assert "fdp_within_limit" in check_ids
        assert "extension_permitted" in check_ids
        ext_check = next(c for c in result["checks"] if c["check"] == "extension_permitted")
        assert ext_check["passed"] is True

    def test_extension_hours_exceed_max(self):
        """extension.hours_used > max_extension_hours — extension_permitted fails."""
        result = validate_fdp(
            appendix="3",
            fdp_start_utc="2026-03-28T22:00:00Z",
            fdp_end_utc="2026-03-29T12:00:00Z",       # 14h = 12h + 2h ext
            local_time_offset_hours=8,
            sectors=3,
            extension={"type": "unforeseen", "hours_used": 2.0},  # max is 1h
        )
        ext_check = next(c for c in result["checks"] if c["check"] == "extension_permitted")
        assert ext_check["passed"] is False
        assert result["valid"] is False
        assert any(v["check"] == "extension_permitted" for v in result["violations"])

    def test_urgent_extension_invalid_for_non_4b(self):
        """'urgent' type is only valid for Appendix 4B."""
        result = validate_fdp(
            appendix="3",
            fdp_start_utc="2026-03-28T22:00:00Z",
            fdp_end_utc="2026-03-29T11:00:00Z",       # 13h
            local_time_offset_hours=8,
            sectors=3,
            extension={"type": "urgent", "hours_used": 1.0},
        )
        ext_check = next(c for c in result["checks"] if c["check"] == "extension_permitted")
        assert ext_check["passed"] is False
        assert result["valid"] is False

    def test_extension_above_base_but_below_cap(self):
        """FDP exceeds base but within extension cap — valid when extension is valid."""
        result = validate_fdp(
            appendix="3",
            fdp_start_utc="2026-03-28T22:00:00Z",
            fdp_end_utc="2026-03-29T10:30:00Z",       # 12.5h, between 12h and 13h absolute max
            local_time_offset_hours=8,
            sectors=3,
            extension={"type": "unforeseen", "hours_used": 0.5},
        )
        assert result["valid"] is True


class TestFlightTimeLimitCheck:
    """Per-FDP flight time limit checks."""

    def test_appendix3_flight_time_within_limit(self):
        """8h flight time against 10.5h limit — passes."""
        result = validate_fdp(
            appendix="3",
            fdp_start_utc="2026-03-28T22:00:00Z",
            fdp_end_utc="2026-03-29T10:00:00Z",
            local_time_offset_hours=8,
            sectors=3,
            actual_flight_time_hours=8.0,
        )
        ft_check = next(c for c in result["checks"] if c["check"] == "flight_time_within_limit")
        assert ft_check["passed"] is True
        assert ft_check["limit"] == 10.5

    def test_appendix3_flight_time_at_limit(self):
        """Exactly at the flight time limit — passes."""
        result = validate_fdp(
            appendix="3",
            fdp_start_utc="2026-03-28T22:00:00Z",
            fdp_end_utc="2026-03-29T10:00:00Z",
            local_time_offset_hours=8,
            sectors=3,
            actual_flight_time_hours=10.5,
        )
        ft_check = next(c for c in result["checks"] if c["check"] == "flight_time_within_limit")
        assert ft_check["passed"] is True

    def test_appendix3_flight_time_exceeds_limit(self):
        """11h flight time against 10.5h limit — fails."""
        result = validate_fdp(
            appendix="3",
            fdp_start_utc="2026-03-28T22:00:00Z",
            fdp_end_utc="2026-03-29T10:00:00Z",
            local_time_offset_hours=8,
            sectors=3,
            actual_flight_time_hours=11.0,
        )
        assert result["valid"] is False
        v = next(v for v in result["violations"] if v["check"] == "flight_time_within_limit")
        assert v["actual"] == 11.0
        assert v["limit"] == 10.5
        assert v["severity"] == "hard_limit"

    def test_appendix1_no_flight_time_limit(self):
        """Appendix 1 has no per-FDP flight time limit — check is skipped."""
        result = validate_fdp(
            appendix="1",
            fdp_start_utc="2026-03-28T22:00:00Z",
            fdp_end_utc="2026-03-29T07:00:00Z",
            local_time_offset_hours=8,
            sectors=1,
            actual_flight_time_hours=8.5,
        )
        check_ids = {c["check"] for c in result["checks"]}
        assert "flight_time_within_limit" not in check_ids

    def test_no_flight_time_provided_skips_check(self):
        """If actual_flight_time_hours not provided, the check is omitted."""
        result = validate_fdp(
            appendix="3",
            fdp_start_utc="2026-03-28T22:00:00Z",
            fdp_end_utc="2026-03-29T10:00:00Z",
            local_time_offset_hours=8,
            sectors=3,
        )
        check_ids = {c["check"] for c in result["checks"]}
        assert "flight_time_within_limit" not in check_ids


class TestAllAppendices:
    """Smoke test: all 9 appendices pass with conservative (4h) FDP inputs."""

    # FDP start = 0600 local (+8 UTC offset), end = 4h later (universally within limits)
    _PARAMS: dict = {
        "1":  {},
        "2":  {"acclimatisation_state": "acclimatised", "acclimatised_time_offset_hours": 8.0},
        "3":  {},
        "4":  {},
        "4A": {},
        "4B": {},
        "5":  {},
        "5A": {},
        "6":  {},
    }

    def test_all_appendices_within_limit(self):
        for appendix, extra in self._PARAMS.items():
            result = validate_fdp(
                appendix=appendix,
                fdp_start_utc="2026-03-28T22:00:00Z",
                fdp_end_utc="2026-03-29T02:00:00Z",   # 4h — well within any limit
                local_time_offset_hours=8,
                sectors=1,
                **extra,
            )
            assert result["valid"] is True, (
                f"Appendix {appendix}: expected valid=True, "
                f"got violations={result['violations']}"
            )

    def test_invalid_appendix_raises(self):
        with pytest.raises(ValueError, match="Unknown appendix"):
            validate_fdp(
                appendix="99",
                fdp_start_utc="2026-03-28T22:00:00Z",
                fdp_end_utc="2026-03-29T02:00:00Z",
                local_time_offset_hours=8,
                sectors=1,
            )
