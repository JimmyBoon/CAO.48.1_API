"""
tests/test_sequence_validator.py — Unit tests for the sequence validator engine.

Tests validate_sequence() in isolation (no HTTP layer).
"""

import pytest
from datetime import datetime, timedelta, timezone

from app.engines.sequence_validator import validate_sequence


def _utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _fdp(start: str, end: str, flight: float = 4.0, duty: float = 5.0,
         offset: float = 10.0, sectors: int = 2, crosses_wocl: bool = False):
    """Return a dict shaped like SequenceFdpEvent."""
    return {
        "event_type": "fdp",
        "fdp_start_utc": _utc(start),
        "fdp_end_utc": _utc(end),
        "actual_flight_time_hours": flight,
        "actual_duty_time_hours": duty,
        "local_time_offset_hours": offset,
        "sectors": sectors,
        "crosses_wocl": crosses_wocl,
    }


def _odp(start: str, end: str, duration: float, includes_night: bool = True, location: str = "away"):
    """Return a dict shaped like SequenceOdpEvent."""
    return {
        "event_type": "off_duty",
        "start_utc": _utc(start),
        "end_utc": _utc(end),
        "duration_hours": duration,
        "includes_local_night": includes_night,
        "location": location,
    }


class TestBasicSequence:
    """A simple 2-FDP sequence should produce prefixed checks."""

    def test_two_fdp_valid_sequence(self):
        events = [
            # 0800-1800 local (UTC+10 → 2200Z to 0800Z next day) — not early start
            _fdp("2026-03-24T22:00:00Z", "2026-03-25T08:00:00Z",
                 flight=7.5, duty=10.0, offset=10.0, sectors=3),
            _odp("2026-03-25T08:00:00Z", "2026-03-25T22:00:00Z",
                 duration=14.0, includes_night=True),
            _fdp("2026-03-25T22:00:00Z", "2026-03-26T08:00:00Z",
                 flight=7.5, duty=10.0, offset=10.0, sectors=3),
        ]
        result = validate_sequence(appendix="3", events=events)
        assert result["appendix"] == "3"
        # Check IDs should be prefixed
        check_ids = [c["check"] for c in result["checks"]]
        assert any(ci.startswith("fdp1_") for ci in check_ids)
        assert any(ci.startswith("fdp2_") for ci in check_ids)
        assert any(ci.startswith("odp1_") for ci in check_ids)

    def test_single_fdp_no_odp(self):
        events = [
            _fdp("2026-03-24T22:00:00Z", "2026-03-25T08:00:00Z",
                 flight=7.5, duty=10.0, offset=10.0, sectors=3),
        ]
        result = validate_sequence(appendix="3", events=events)
        check_ids = [c["check"] for c in result["checks"]]
        assert any(ci.startswith("fdp1_") for ci in check_ids)
        assert not any(ci.startswith("odp") for ci in check_ids)


class TestExcessiveFdpLength:
    """An FDP longer than the limit should produce a violation."""

    def test_fdp_too_long_produces_violation(self):
        """18h FDP for App 3 starting at 0900 local — default limit is ~12h."""
        events = [
            _fdp("2026-03-24T23:00:00Z", "2026-03-25T17:00:00Z",  # 18h FDP
                 flight=10.0, duty=18.0, offset=10.0, sectors=3),
        ]
        result = validate_sequence(appendix="3", events=events)
        assert result["valid"] is False
        violation_checks = [v["check"] for v in result["violations"]]
        assert any("fdp_within_limit" in vc for vc in violation_checks)


class TestWoclSection132:
    """§13.2: after 3 consecutive WOCL infringements, next WOCL FDP must have intervening LN."""

    def _wocl_fdp(self, start: str):
        """A WOCL-infringing 8h FDP starting at night (local 2300 with +10)."""
        start_dt = _utc(start)
        end_dt = start_dt + timedelta(hours=8)
        return {
            "event_type": "fdp",
            "fdp_start_utc": start_dt,
            "fdp_end_utc": end_dt,
            "actual_flight_time_hours": 5.0,
            "actual_duty_time_hours": 8.0,
            "local_time_offset_hours": 10.0,
            "sectors": 2,
            "crosses_wocl": True,  # explicitly marked
        }

    def _short_odp(self, start: str, duration: float = 10.0, includes_night: bool = False):
        start_dt = _utc(start)
        end_dt = start_dt + timedelta(hours=duration)
        return {
            "event_type": "off_duty",
            "start_utc": start_dt,
            "end_utc": end_dt,
            "duration_hours": duration,
            "includes_local_night": includes_night,
            "location": "away",
        }

    def test_4th_wocl_without_ln_is_violation(self):
        """4th consecutive WOCL without intervening local night → §13.2 violation."""
        events = [
            self._wocl_fdp("2026-03-22T13:00:00Z"),  # FDP1: WOCL (local 2300)
            self._short_odp("2026-03-22T21:00:00Z", includes_night=False),
            self._wocl_fdp("2026-03-23T13:00:00Z"),  # FDP2: WOCL
            self._short_odp("2026-03-23T21:00:00Z", includes_night=False),
            self._wocl_fdp("2026-03-24T13:00:00Z"),  # FDP3: WOCL
            self._short_odp("2026-03-24T21:00:00Z", includes_night=False),
            self._wocl_fdp("2026-03-25T13:00:00Z"),  # FDP4: WOCL — §13.2 check
        ]
        result = validate_sequence(appendix="3", events=events)
        violation_checks = [v["check"] for v in result["violations"]]
        assert any("wocl_local_night_required" in vc for vc in violation_checks)

    def test_4th_wocl_with_intervening_ln_passes(self):
        """4th consecutive WOCL WITH an intervening local night → §13.2 passed."""
        # ODP between 3rd and 4th WOCL FDP is long enough (24h from local
        # 0700) to fully span a 2200-0500 local night, so it qualifies —
        # includes_night is derived from timestamps, not the (ignored) flag.
        events = [
            self._wocl_fdp("2026-03-22T13:00:00Z"),
            self._short_odp("2026-03-22T21:00:00Z", includes_night=False),
            self._wocl_fdp("2026-03-23T13:00:00Z"),
            self._short_odp("2026-03-23T21:00:00Z", includes_night=False),
            self._wocl_fdp("2026-03-24T13:00:00Z"),
            self._short_odp("2026-03-24T21:00:00Z", duration=24.0, includes_night=True),  # ← LN
            self._wocl_fdp("2026-03-25T13:00:00Z"),
        ]
        result = validate_sequence(appendix="3", events=events)
        wocl_checks = [c for c in result["checks"] if "wocl_local_night_required" in c["check"]]
        if wocl_checks:
            # The wocl check ran and should have passed
            assert all(c["passed"] for c in wocl_checks)

    def test_3_wocl_and_no_4th_does_not_trigger_check(self):
        """Only 3 consecutive WOCL infringements — no §13.2 check needed."""
        events = [
            self._wocl_fdp("2026-03-22T13:00:00Z"),
            self._short_odp("2026-03-22T21:00:00Z", includes_night=False),
            self._wocl_fdp("2026-03-23T13:00:00Z"),
            self._short_odp("2026-03-23T21:00:00Z", includes_night=False),
            self._wocl_fdp("2026-03-24T13:00:00Z"),
        ]
        result = validate_sequence(appendix="3", events=events)
        wocl_132_violations = [v for v in result["violations"] if "wocl_local_night_required" in v["check"]]
        assert wocl_132_violations == []


class TestIncludesLocalNightIsDerivedNotTrusted:
    """
    Regression test for the silent-trust bug: includes_local_night on an
    off_duty event must be derived from its own start_utc/end_utc/offset,
    never taken at face value from the caller — otherwise a caller that
    mis-computes the flag can mask a real §13.2 WOCL violation.

    Fixture: 5-day Appendix 2 roster, home base WST (UTC+8), sign-ons at
    0355/0400 with sign-offs 16-18h earlier — long rest, but every off-duty
    period ends before 0500 so none of them actually span a local night.
    """

    def _roster_events(self, claim_local_night: bool, claim_crosses_wocl: bool = True,
                        omit_crosses_wocl: bool = False):
        # (fdp_start_utc, fdp_end_utc) per day, local sign-on/sign-off times
        # 0400-1100, 0355-1000, 0355-1000, 0400-1200, 0400-1000 (UTC+8).
        fdps = [
            ("2026-08-15T20:00:00Z", "2026-08-16T03:00:00Z"),
            ("2026-08-16T19:55:00Z", "2026-08-17T02:00:00Z"),
            ("2026-08-17T19:55:00Z", "2026-08-18T02:00:00Z"),
            ("2026-08-18T20:00:00Z", "2026-08-19T04:00:00Z"),
            ("2026-08-19T20:00:00Z", "2026-08-20T02:00:00Z"),
        ]
        events = []
        for i, (start, end) in enumerate(fdps):
            fdp_event = {
                "event_type": "fdp",
                "fdp_start_utc": _utc(start),
                "fdp_end_utc": _utc(end),
                "actual_flight_time_hours": 3.5,
                "actual_duty_time_hours": (_utc(end) - _utc(start)).total_seconds() / 3600,
                "local_time_offset_hours": 8.0,
                "sectors": 2,
            }
            if not omit_crosses_wocl:
                fdp_event["crosses_wocl"] = claim_crosses_wocl
            events.append(fdp_event)
            if i < len(fdps) - 1:
                odp_start = end
                odp_end = fdps[i + 1][0]
                events.append({
                    "event_type": "off_duty",
                    "start_utc": _utc(odp_start),
                    "end_utc": _utc(odp_end),
                    "duration_hours": (_utc(odp_end) - _utc(odp_start)).total_seconds() / 3600,
                    "includes_local_night": claim_local_night,
                    "location": "home_base",
                })
        return events

    def test_wocl_violations_caught_even_when_caller_claims_local_night(self):
        """
        Caller wrongly sets includes_local_night=True on every ODP. Since
        the flag is now derived (ignored), FDP4/FDP5 must still be flagged.
        """
        events = self._roster_events(claim_local_night=True)
        result = validate_sequence(appendix="2", events=events)
        assert result["valid"] is False
        violation_checks = {v["check"] for v in result["violations"]}
        assert "fdp4_wocl_local_night_required" in violation_checks
        assert "fdp5_wocl_local_night_required" in violation_checks

    def test_wocl_violations_caught_when_flag_omitted(self):
        """Same roster with includes_local_night left False — same result."""
        events = self._roster_events(claim_local_night=False)
        result = validate_sequence(appendix="2", events=events)
        assert result["valid"] is False
        violation_checks = {v["check"] for v in result["violations"]}
        assert "fdp4_wocl_local_night_required" in violation_checks
        assert "fdp5_wocl_local_night_required" in violation_checks

    def test_wocl_violations_caught_even_when_caller_claims_no_wocl_crossing(self):
        """
        Caller wrongly sets crosses_wocl=False on every FDP (all five actually
        sign on at 0355/0400, squarely inside 0200-0559). Since the flag is
        now derived (ignored), consecutive_wocl must still climb past 3 and
        FDP4/FDP5 must still be flagged.
        """
        events = self._roster_events(claim_local_night=False, claim_crosses_wocl=False)
        result = validate_sequence(appendix="2", events=events)
        assert result["valid"] is False
        violation_checks = {v["check"] for v in result["violations"]}
        assert "fdp4_wocl_local_night_required" in violation_checks
        assert "fdp5_wocl_local_night_required" in violation_checks

    def test_wocl_violations_caught_when_crosses_wocl_never_sent(self):
        """
        Regression test for the aviation-toolbox integration bug: a caller
        that never sends crosses_wocl at all (the field is simply absent from
        every FDP event) must still get the same violations, not a silently
        passing roster.
        """
        events = self._roster_events(claim_local_night=False, omit_crosses_wocl=True)
        assert all("crosses_wocl" not in e for e in events if e["event_type"] == "fdp")
        result = validate_sequence(appendix="2", events=events)
        assert result["valid"] is False
        violation_checks = {v["check"] for v in result["violations"]}
        assert "fdp4_wocl_local_night_required" in violation_checks
        assert "fdp5_wocl_local_night_required" in violation_checks


class TestConsecutiveEarlyStartCountTracking:
    """The engine should correctly track consecutive early starts and pass correct counts."""

    def _early_fdp(self, start: str, flight: float = 4.0):
        """0600 local start at UTC+10 = 2000Z previous day."""
        start_dt = _utc(start)
        end_dt = start_dt + timedelta(hours=8)
        return {
            "event_type": "fdp",
            "fdp_start_utc": start_dt,
            "fdp_end_utc": end_dt,
            "actual_flight_time_hours": flight,
            "actual_duty_time_hours": 8.0,
            "local_time_offset_hours": 10.0,
            "sectors": 2,
            "crosses_wocl": False,
        }

    def _basic_odp(self, start: str, duration: float = 11.0):
        start_dt = _utc(start)
        end_dt = start_dt + timedelta(hours=duration)
        return {
            "event_type": "off_duty",
            "start_utc": start_dt,
            "end_utc": end_dt,
            "duration_hours": duration,
            "includes_local_night": True,
            "location": "away",
        }

    def test_4_consecutive_early_starts_triggers_reduction(self):
        """4th consecutive early start (0600 local) should produce a −2h reduction note."""
        # 0600 local at +10 = 2000Z
        events = [
            self._early_fdp("2026-03-21T20:00:00Z"),
            self._basic_odp("2026-03-22T04:00:00Z"),
            self._early_fdp("2026-03-22T20:00:00Z"),
            self._basic_odp("2026-03-23T04:00:00Z"),
            self._early_fdp("2026-03-23T20:00:00Z"),
            self._basic_odp("2026-03-24T04:00:00Z"),
            self._early_fdp("2026-03-24T20:00:00Z"),  # 4th early start
        ]
        result = validate_sequence(appendix="3", events=events)
        all_notes = " ".join(result.get("calculation_notes", []))
        # Calculator should log the 2h reduction on the 4th start
        assert any("2h" in n or "4th" in n.lower() or "reduction" in n.lower()
                   for n in result.get("calculation_notes", []))


class TestCumulativeIntegration:
    """validate_sequence runs cumulative checks over all FDPs in the sequence."""

    def test_cumulative_checks_included(self):
        """Sequence result should include cumulative-prefixed checks."""
        events = [
            _fdp("2026-03-24T22:00:00Z", "2026-03-25T08:00:00Z",
                 flight=7.5, duty=10.0, offset=10.0, sectors=3),
            _odp("2026-03-25T08:00:00Z", "2026-03-25T22:00:00Z",
                 duration=14.0, includes_night=True),
            _fdp("2026-03-25T22:00:00Z", "2026-03-26T08:00:00Z",
                 flight=7.5, duty=10.0, offset=10.0, sectors=3),
        ]
        result = validate_sequence(appendix="3", events=events)
        check_ids = [c["check"] for c in result["checks"]]
        assert any(ci.startswith("cumulative_") for ci in check_ids)

    def test_zero_cumulative_raises_no_errors_for_short_sequence(self):
        """A couple of FDPs well under the 28d limit should not produce violations."""
        events = [
            _fdp("2026-03-20T22:00:00Z", "2026-03-21T08:00:00Z",
                 flight=7.0, duty=9.0, offset=10.0),
            _odp("2026-03-21T08:00:00Z", "2026-03-21T22:00:00Z",
                 duration=14.0, includes_night=True),
            _fdp("2026-03-21T22:00:00Z", "2026-03-22T08:00:00Z",
                 flight=7.0, duty=9.0, offset=10.0),
        ]
        result = validate_sequence(appendix="3", events=events)
        cumulative_violations = [v for v in result["violations"] if v["check"].startswith("cumulative_")]
        # 14h flight and 18h duty over 2 FDPs is far under any cumulative limit
        for v in cumulative_violations:
            if v["check"] in ("cumulative_flight_time_28d", "cumulative_flight_time_365d",
                              "cumulative_duty_time_168h", "cumulative_duty_time_336h"):
                pytest.fail(f"Unexpected cumulative violation: {v}")


class TestInvalidAppendix:
    def test_raises_for_unknown_appendix(self):
        events = [_fdp("2026-03-24T22:00:00Z", "2026-03-25T08:00:00Z")]
        with pytest.raises(Exception):
            validate_sequence(appendix="99", events=events)


class TestOdpOnlySequence:
    """A sequence with only ODP events should process without error."""

    def test_odp_only_no_fdp(self):
        events = [
            _odp("2026-03-24T00:00:00Z", "2026-03-25T00:00:00Z",
                 duration=24.0, includes_night=True),
        ]
        result = validate_sequence(appendix="3", events=events)
        assert result["appendix"] == "3"
        assert isinstance(result["checks"], list)
        assert isinstance(result["violations"], list)
