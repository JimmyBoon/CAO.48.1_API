"""
Unit tests for app.engines.roster_validator.validate_roster().

Tests cover engine logic directly (not HTTP), using plain dicts as events.
"""

import pytest
from datetime import datetime, timezone

from app.engines.roster_validator import validate_roster


# ─── Helpers ─────────────────────────────────────────────────────────

def _dt(s: str) -> datetime:
    """Parse an ISO 8601 UTC string into a timezone-aware datetime."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _fdp(start: str, end: str, flight_h: float = 7.0, duty_h: float = 9.0,
         offset: float = 8.0, sectors: int = 3, crosses_wocl: bool = False) -> dict:
    return {
        "event_type": "fdp",
        "fdp_start_utc": _dt(start),
        "fdp_end_utc": _dt(end),
        "actual_flight_time_hours": flight_h,
        "actual_duty_time_hours": duty_h,
        "local_time_offset_hours": offset,
        "sectors": sectors,
        "crosses_wocl": crosses_wocl,
    }


def _odp(start: str, end: str, duration_h: float, night: bool = True,
         location: str = "away") -> dict:
    return {
        "event_type": "off_duty",
        "start_utc": _dt(start),
        "end_utc": _dt(end),
        "duration_hours": duration_h,
        "includes_local_night": night,
        "following_includes_local_night": night,
        "location": location,
    }


def _rest(start: str, end: str, count: int = 1, night: bool = True) -> dict:
    return {
        "event_type": "rest_day",
        "start_utc": _dt(start),
        "end_utc": _dt(end),
        "count": count,
        "includes_local_night": night,
    }


ROSTER_START = _dt("2026-03-24T00:00:00Z")
ROSTER_END   = _dt("2026-03-27T00:00:00Z")


# ─── Tests ───────────────────────────────────────────────────────────

class TestBasicRoster:
    def test_valid_two_fdp_roster(self):
        events = [
            _fdp("2026-03-24T22:00:00Z", "2026-03-25T08:00:00Z"),
            _odp("2026-03-25T08:00:00Z", "2026-03-25T22:00:00Z", duration_h=14.0),
            _fdp("2026-03-25T22:00:00Z", "2026-03-26T08:00:00Z"),
        ]
        result = validate_roster("3", ROSTER_START, ROSTER_END, events)
        assert result["summary"]["total_fdps"] == 2
        assert result["summary"]["total_off_duty_periods"] == 1
        assert result["summary"]["total_violations"] == 0

        assert result["valid"] is True

        # Phase 5 (S9): with no prior history the 28-day and 365-day windows
        # cannot be established. That is reported through checks_skipped, not
        # by failing the roster — `valid` tracks violations only.
        assert result["summary"]["checks_skipped"] > 0

    def test_response_has_required_keys(self):
        events = [_fdp("2026-03-24T22:00:00Z", "2026-03-25T08:00:00Z")]
        result = validate_roster("3", ROSTER_START, ROSTER_END, events)
        for key in ("valid", "appendix", "roster_start_utc", "roster_end_utc",
                    "summary", "fdp_results", "odp_results", "sequence_checks",
                    "sequence_violations", "cumulative_result", "all_violations", "warnings"):
            assert key in result, f"Missing key: {key}"

    def test_appendix_normalised_to_upper(self):
        events = [_fdp("2026-03-24T22:00:00Z", "2026-03-25T08:00:00Z")]
        result = validate_roster("3", ROSTER_START, ROSTER_END, events)
        assert result["appendix"] == "3"


class TestFdpViolation:
    def test_fdp_too_long_produces_violation(self):
        # 15-hour FDP — well over the ~13h App 3 limit
        events = [
            _fdp("2026-03-24T07:00:00Z", "2026-03-24T22:00:00Z",
                 flight_h=12.0, duty_h=15.0),
        ]
        result = validate_roster("3", ROSTER_START, ROSTER_END, events)
        assert result["valid"] is False
        assert result["fdp_results"][0]["valid"] is False
        assert len(result["all_violations"]) > 0
        assert result["summary"]["fdp_violations"] == 1
        assert result["summary"]["total_violations"] > 0


class TestOdpViolation:
    def test_odp_too_short_produces_violation(self):
        # Min ODP for App 3 is typically 10h; 8h is too short
        events = [
            _fdp("2026-03-24T22:00:00Z", "2026-03-25T08:00:00Z"),
            _odp("2026-03-25T08:00:00Z", "2026-03-25T16:00:00Z", duration_h=8.0),
        ]
        result = validate_roster("3", ROSTER_START, ROSTER_END, events)
        assert result["valid"] is False
        assert result["odp_results"][0]["valid"] is False
        assert result["summary"]["odp_violations"] == 1


class TestRestDayEvent:
    def test_rest_day_counted_in_summary(self):
        events = [
            _fdp("2026-03-24T22:00:00Z", "2026-03-25T08:00:00Z"),
            _rest("2026-03-25T10:00:00Z", "2026-03-26T10:00:00Z", count=1),
        ]
        result = validate_roster("3", ROSTER_START, ROSTER_END, events)
        assert result["summary"]["total_rest_days"] == 1

    def test_rest_day_resets_consecutive_counters(self):
        """After a rest day the next FDP WOCL counter should be reset."""
        wocl_fdps = [
            _fdp(f"2026-03-{20+i:02d}T02:00:00Z", f"2026-03-{20+i:02d}T08:00:00Z",
                 crosses_wocl=True)
            for i in range(4)
        ]
        # Last 3 WOCL fdps → 4th should trigger §13.2 violation
        # But insert a rest_day before the 4th to reset the counter
        events = (
            wocl_fdps[:3]
            + [_odp("2026-03-23T08:00:00Z", "2026-03-23T22:00:00Z", duration_h=14.0)]
            + [_rest("2026-03-23T22:00:00Z", "2026-03-26T00:00:00Z", count=2, night=True)]
            + [wocl_fdps[3]]
        )
        result = validate_roster("3", _dt("2026-03-20T00:00:00Z"), ROSTER_END, events)
        # With a 2-day rest between 3rd and 4th WOCL FDP, no §13.2 violation
        assert result["summary"]["sequence_violations"] == 0


class TestSequenceLevel:
    def test_wocl_132_triggers_sequence_violation(self):
        """4 consecutive WOCL FDPs (early 0400-local sign-ons) with 18h ODPs
        that each end at 0400 local — short of the 0500 needed to fully span
        the §6.1 2200-0500 local night — so none qualify as an intervening
        local night and the 4th FDP should trigger a §13.2 violation."""
        events = []
        for i in range(4):
            fdp_start = f"2026-03-{19+i:02d}T20:00:00Z"  # local 0400
            fdp_end = f"2026-03-{20+i:02d}T02:00:00Z"     # local 1000
            events.append(_fdp(fdp_start, fdp_end, crosses_wocl=True))
            if i < 3:
                # 1000 local -> 0400 local next day: ends before 0500, so it
                # does NOT fully span a local night.
                events.append(
                    _odp(fdp_end, f"2026-03-{20+i:02d}T20:00:00Z", duration_h=18.0)
                )
        result = validate_roster("3", _dt("2026-03-19T00:00:00Z"), ROSTER_END, events)
        assert result["summary"]["sequence_violations"] >= 1
        assert any("wocl" in v["check"] for v in result["sequence_violations"])

    def test_3_wocl_with_no_4th_does_not_trigger(self):
        """Three consecutive WOCL FDPs alone should not trigger the §13.2 check."""
        events = []
        for i in range(3):
            events.append(
                _fdp(f"2026-03-{20+i:02d}T02:00:00Z",
                     f"2026-03-{20+i:02d}T08:00:00Z",
                     crosses_wocl=True)
            )
            if i < 2:
                events.append(
                    _odp(f"2026-03-{20+i:02d}T08:00:00Z",
                         f"2026-03-{20+i+1:02d}T02:00:00Z",
                         duration_h=18.0, night=False)
                )
        result = validate_roster("3", _dt("2026-03-20T00:00:00Z"), ROSTER_END, events)
        assert result["summary"]["sequence_violations"] == 0


class TestCrossesWoclIsDerivedNotTrusted:
    """
    Regression tests for the silent-trust bug on crosses_wocl: a caller that
    wrongly claims (or, per the aviation-toolbox integration, simply never
    sends) crosses_wocl must not be able to disable the §13.2 check — it is
    always derived from fdp_start_utc/fdp_end_utc/local_time_offset_hours.
    """

    def _fdp_dict(self, start, end, offset=8.0, claim_crosses_wocl=False,
                  omit_crosses_wocl=False, acclimatisation=None):
        event = {
            "event_type": "fdp",
            "fdp_start_utc": _dt(start),
            "fdp_end_utc": _dt(end),
            "actual_flight_time_hours": 3.5,
            "actual_duty_time_hours": 6.0,
            "local_time_offset_hours": offset,
            "sectors": 2,
        }
        if not omit_crosses_wocl:
            event["crosses_wocl"] = claim_crosses_wocl
        if acclimatisation is not None:
            event["acclimatisation"] = acclimatisation
        return event

    def test_violations_caught_even_when_caller_claims_no_wocl_crossing(self):
        """Caller sets crosses_wocl=False on every FDP; all four actually
        sign on at 0400 local (inside 0200-0559), so §13.2 must still fire."""
        events = []
        for i in range(4):
            fdp_start = f"2026-03-{19+i:02d}T20:00:00Z"  # local 0400
            fdp_end = f"2026-03-{20+i:02d}T02:00:00Z"     # local 1000
            events.append(self._fdp_dict(fdp_start, fdp_end, claim_crosses_wocl=False))
            if i < 3:
                events.append(_odp(fdp_end, f"2026-03-{20+i:02d}T20:00:00Z", duration_h=18.0))
        result = validate_roster("3", _dt("2026-03-19T00:00:00Z"), ROSTER_END, events)
        assert result["summary"]["sequence_violations"] >= 1

    def test_violations_caught_when_crosses_wocl_never_sent(self):
        """Regression test for the aviation-toolbox bug: crosses_wocl absent
        from every FDP event entirely — must not silently pass the roster."""
        events = []
        for i in range(4):
            fdp_start = f"2026-03-{19+i:02d}T20:00:00Z"
            fdp_end = f"2026-03-{20+i:02d}T02:00:00Z"
            events.append(self._fdp_dict(fdp_start, fdp_end, omit_crosses_wocl=True))
            if i < 3:
                events.append(_odp(fdp_end, f"2026-03-{20+i:02d}T20:00:00Z", duration_h=18.0))
        assert all("crosses_wocl" not in e for e in events if e["event_type"] == "fdp")
        result = validate_roster("3", _dt("2026-03-19T00:00:00Z"), ROSTER_END, events)
        assert result["summary"]["sequence_violations"] >= 1

    def test_appendix_2_wocl_uses_acclimatised_offset(self):
        """
        §6.1(a): for Appendix 2, an acclimatised FCM's WOCL is assessed at the
        acclimatised location, not the duty-commencement location.

        Each FDP starts at UTC 20:00 — local 2000 at the commencement offset
        (0h, not inside 0200-0559) but local 0200 at the acclimatised offset
        (+6h). Only by using the acclimatised offset does this sequence cross
        the WOCL at all, let alone four times running.
        """
        events = []
        for i in range(4):
            fdp_start = f"2026-03-{19+i:02d}T20:00:00Z"
            fdp_end = f"2026-03-{20+i:02d}T02:00:00Z"
            events.append(self._fdp_dict(
                fdp_start, fdp_end, offset=0.0, claim_crosses_wocl=False,
                acclimatisation={"state": "acclimatised", "acclimatised_time_offset_hours": 6.0},
            ))
            if i < 3:
                events.append(_odp(fdp_end, f"2026-03-{20+i:02d}T20:00:00Z", duration_h=18.0))
        result = validate_roster("2", _dt("2026-03-19T00:00:00Z"), ROSTER_END, events)
        assert result["summary"]["sequence_violations"] >= 1

    def test_appendix_3_ignores_acclimatisation_for_wocl(self):
        """
        Same instants and offsets as the acclimatised-offset test above, but
        Appendix 3 has no acclimatisation concept (§6.1(b) uses the
        commencement location only) — even with acclimatisation supplied, the
        0h commencement offset never crosses the WOCL, so no violation.
        """
        events = []
        for i in range(4):
            fdp_start = f"2026-03-{19+i:02d}T20:00:00Z"
            fdp_end = f"2026-03-{20+i:02d}T02:00:00Z"
            events.append(self._fdp_dict(
                fdp_start, fdp_end, offset=0.0, claim_crosses_wocl=False,
                acclimatisation={"state": "acclimatised", "acclimatised_time_offset_hours": 6.0},
            ))
            if i < 3:
                events.append(_odp(fdp_end, f"2026-03-{20+i:02d}T20:00:00Z", duration_h=18.0))
        result = validate_roster("3", _dt("2026-03-19T00:00:00Z"), ROSTER_END, events)
        assert result["summary"]["sequence_violations"] == 0


class TestSummaryTotals:
    def test_summary_flight_time_totals(self):
        events = [
            _fdp("2026-03-24T22:00:00Z", "2026-03-25T08:00:00Z",
                 flight_h=7.5, duty_h=10.0),
            _odp("2026-03-25T08:00:00Z", "2026-03-25T22:00:00Z", duration_h=14.0),
            _fdp("2026-03-25T22:00:00Z", "2026-03-26T08:00:00Z",
                 flight_h=8.0, duty_h=10.0),
        ]
        result = validate_roster("3", ROSTER_START, ROSTER_END, events)
        assert abs(result["summary"]["total_flight_time_hours"] - 15.5) < 0.01
        assert abs(result["summary"]["total_duty_time_hours"] - 20.0) < 0.01

    def test_summary_counts(self):
        events = [
            _fdp("2026-03-24T22:00:00Z", "2026-03-25T08:00:00Z"),
            _odp("2026-03-25T08:00:00Z", "2026-03-25T22:00:00Z", duration_h=14.0),
            _fdp("2026-03-25T22:00:00Z", "2026-03-26T08:00:00Z"),
            _rest("2026-03-26T08:00:00Z", "2026-03-27T00:00:00Z"),
        ]
        result = validate_roster("3", ROSTER_START, ROSTER_END, events)
        s = result["summary"]
        assert s["total_fdps"] == 2
        assert s["total_off_duty_periods"] == 1
        assert s["total_rest_days"] == 1


class TestPriorHistory:
    def test_prior_fdp_log_accepted(self):
        from datetime import timedelta
        prior = [
            {
                "fdp_start_utc": _dt("2026-03-10T22:00:00Z"),
                "fdp_end_utc": _dt("2026-03-11T08:00:00Z"),
                "actual_flight_time_hours": 8.0,
                "actual_duty_time_hours": 10.0,
                "local_time_offset_hours": 8.0,
            }
        ]
        events = [_fdp("2026-03-24T22:00:00Z", "2026-03-25T08:00:00Z")]
        result = validate_roster("3", ROSTER_START, ROSTER_END, events, prior_fdp_log=prior)
        # Should complete without error and include a cumulative result
        assert "cumulative_result" in result
        assert isinstance(result["cumulative_result"], dict)

    def test_prior_summary_accepted(self):
        from app.models.validation import CumulativeSummaryInput
        summary = CumulativeSummaryInput(
            flight_time_28d_hours=50.0,
            flight_time_365d_hours=600.0,
            days_off_in_28d=6,
        )
        events = [_fdp("2026-03-24T22:00:00Z", "2026-03-25T08:00:00Z")]
        result = validate_roster("3", ROSTER_START, ROSTER_END, events, prior_summary=summary)
        assert "cumulative_result" in result


class TestInvalidAppendix:
    def test_raises_for_unknown_appendix(self):
        events = [_fdp("2026-03-24T22:00:00Z", "2026-03-25T08:00:00Z")]
        with pytest.raises(ValueError, match="Unknown appendix"):
            validate_roster("Z", ROSTER_START, ROSTER_END, events)


class TestAllViolationsFlattened:
    def test_all_violations_contains_fdp_violations(self):
        # 15-hour FDP too long
        events = [_fdp("2026-03-24T07:00:00Z", "2026-03-24T22:00:00Z",
                        flight_h=12.0, duty_h=15.0)]
        result = validate_roster("3", ROSTER_START, ROSTER_END, events)
        fdp_viols = result["fdp_results"][0]["violations"]
        all_viols = result["all_violations"]
        # all_violations must contain at least the FDP violations
        fdp_checks = {v["check"] for v in fdp_viols}
        all_checks = {v["check"] for v in all_viols}
        assert fdp_checks <= all_checks
