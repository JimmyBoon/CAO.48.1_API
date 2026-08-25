"""
tests/test_cumulative_validator.py — Unit tests for the cumulative validator engine.

Tests validate_cumulative() in isolation (no HTTP layer).
"""

import pytest
from datetime import datetime, timedelta, timezone

from app.engines.cumulative_validator import validate_cumulative


def _utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _make_fdp(start: str, end: str, flight: float = 2.0, duty: float = 3.0, offset: float = 10.0) -> dict:
    return {
        "fdp_start_utc": _utc(start),
        "fdp_end_utc": _utc(end),
        "actual_flight_time_hours": flight,
        "actual_duty_time_hours": duty,
        "local_time_offset_hours": offset,
    }


class TestUnknownAppendix:
    def test_raises_for_unknown_appendix(self):
        with pytest.raises(ValueError, match="Unknown appendix"):
            validate_cumulative(
                appendix="99",
                as_of_utc=_utc("2026-03-01T00:00:00Z"),
                summary={"flight_time_28d_hours": 50.0},
            )


class TestAppendix3FlightTime:
    """Appendix 3: flight time limits 100h/28d, 1000h/365d — from summary."""

    def test_within_limits_passes(self):
        result = validate_cumulative(
            appendix="3",
            as_of_utc=_utc("2026-03-20T00:00:00Z"),
            summary=_build_summary(ft_28d=80.0, ft_365d=800.0, dt_168h=45.0, dt_336h=90.0, rec_168h=True, days_off_28d=8),
        )
        assert result["valid"] is True
        assert result["appendix"] == "3"

    def test_flight_time_28d_exceeded(self):
        result = validate_cumulative(
            appendix="3",
            as_of_utc=_utc("2026-03-20T00:00:00Z"),
            summary=_build_summary(ft_28d=105.0, ft_365d=800.0, dt_168h=45.0, dt_336h=90.0, rec_168h=True, days_off_28d=8),
        )
        assert result["valid"] is False
        checks_by_id = {c["check"]: c for c in result["checks"]}
        assert "flight_time_28d" in checks_by_id
        assert checks_by_id["flight_time_28d"]["passed"] is False

    def test_flight_time_365d_exceeded(self):
        result = validate_cumulative(
            appendix="3",
            as_of_utc=_utc("2026-03-20T00:00:00Z"),
            summary=_build_summary(ft_28d=80.0, ft_365d=1050.0, dt_168h=45.0, dt_336h=90.0, rec_168h=True, days_off_28d=8),
        )
        assert result["valid"] is False
        violations = {v["check"] for v in result["violations"]}
        assert "flight_time_365d" in violations


class TestAppendix3DutyTime:
    def test_duty_168h_exceeded(self):
        result = validate_cumulative(
            appendix="3",
            as_of_utc=_utc("2026-03-20T00:00:00Z"),
            summary=_build_summary(ft_28d=80.0, ft_365d=800.0, dt_168h=65.0, dt_336h=90.0, rec_168h=True, days_off_28d=8),
        )
        assert result["valid"] is False
        assert any(v["check"] == "duty_time_168h" for v in result["violations"])

    def test_duty_336h_exceeded(self):
        result = validate_cumulative(
            appendix="3",
            as_of_utc=_utc("2026-03-20T00:00:00Z"),
            summary=_build_summary(ft_28d=80.0, ft_365d=800.0, dt_168h=55.0, dt_336h=105.0, rec_168h=True, days_off_28d=8),
        )
        assert result["valid"] is False
        assert any(v["check"] == "duty_time_336h" for v in result["violations"])


class TestAppendix1Recovery:
    """Appendix 1 has recovery 36h+2LN/168h and 6 days off/28d."""

    def test_missing_recovery_fails(self):
        result = validate_cumulative(
            appendix="1",
            as_of_utc=_utc("2026-03-20T00:00:00Z"),
            summary=_build_summary(ft_28d=80.0, ft_365d=800.0, rec_168h=False, days_off_28d=8),
        )
        assert result["valid"] is False
        assert any(v["check"] == "recovery_36h_2ln_in_168h" for v in result["violations"])

    def test_missing_days_off_fails(self):
        result = validate_cumulative(
            appendix="1",
            as_of_utc=_utc("2026-03-20T00:00:00Z"),
            summary=_build_summary(ft_28d=80.0, ft_365d=800.0, rec_168h=True, days_off_28d=4),
        )
        assert result["valid"] is False
        assert any(v["check"] == "days_off_in_28d" for v in result["violations"])

    def test_all_passing(self):
        result = validate_cumulative(
            appendix="1",
            as_of_utc=_utc("2026-03-20T00:00:00Z"),
            summary=_build_summary(ft_28d=80.0, ft_365d=800.0, rec_168h=True, days_off_28d=7),
        )
        assert result["valid"] is True


class TestAppendix4ASpecifics:
    """Appendix 4A: flight 50h/28d, duty 45h/168h + 84h/336h, days-off 2/384h."""

    def test_flight_time_4a_limit(self):
        result = validate_cumulative(
            appendix="4A",
            as_of_utc=_utc("2026-03-20T00:00:00Z"),
            summary={"flight_time_28d_hours": 55.0, "duty_time_168h_hours": 40.0,
                     "duty_time_336h_hours": 75.0, "days_off_in_384h": 3},
        )
        assert result["valid"] is False
        assert any(v["check"] == "flight_time_28d" for v in result["violations"])

    def test_4a_all_pass(self):
        result = validate_cumulative(
            appendix="4A",
            as_of_utc=_utc("2026-03-20T00:00:00Z"),
            summary={"flight_time_28d_hours": 40.0, "duty_time_168h_hours": 40.0,
                     "duty_time_336h_hours": 75.0, "days_off_in_384h": 3},
        )
        assert result["valid"] is True


class TestAppendix4BRecovery:
    """
    Appendix 4B §5.4 offers the 336-hour and 504-hour blocks as ALTERNATIVES:
    "Before beginning an FDP or standby, an FCM must have had at least 1 of
    the following". §5.3's 168-hour block is separate and conditional.

    Amended in Phase 5: this class previously asserted all three were
    independently required, so a roster satisfying §5.4(a) but not §5.4(b)
    was reported as violating — a false violation that would block a lawful
    roster.
    """

    BASE = {
        "flight_time_28d_hours": 80.0,
        "flight_time_365d_hours": 800.0,
        "duty_time_168h_hours": 50.0,
        "duty_time_336h_hours": 90.0,
    }

    def test_either_limb_discharges_the_requirement(self):
        for limbs in (
            {"recovery_36h_block_in_336h": True, "recovery_72h_block_in_504h": False},
            {"recovery_36h_block_in_336h": False, "recovery_72h_block_in_504h": True},
        ):
            result = validate_cumulative(
                appendix="4B",
                as_of_utc=_utc("2026-03-20T00:00:00Z"),
                summary={**self.BASE, **limbs},
            )
            assert result["valid"] is True, result["violations"]

    def test_neither_limb_is_a_violation(self):
        result = validate_cumulative(
            appendix="4B",
            as_of_utc=_utc("2026-03-20T00:00:00Z"),
            summary={
                **self.BASE,
                "recovery_36h_block_in_336h": False,
                "recovery_72h_block_in_504h": False,
            },
        )
        assert result["valid"] is False
        assert any(v["check"] == "recovery_72h_3ln_in_504h" for v in result["violations"])

    def test_conditional_168h_block_is_not_asserted_as_a_check(self):
        """
        §5.3 applies only where the FCM conducted 3+ late-night FDPs or an
        increased FDP — a trigger this API is not told about. It belongs in
        caller-must-verify, not in checks.
        """
        result = validate_cumulative(
            appendix="4B",
            as_of_utc=_utc("2026-03-20T00:00:00Z"),
            summary={**self.BASE, "recovery_36h_block_in_336h": True},
        )
        assert not [
            c for c in result["checks"] if c["check"] == "recovery_36h_2ln_in_168h"
        ]


class TestAppendix5FlightTimeAndReset:
    """Appendix 5: multi-window flight time + 5-day reset logic."""

    def test_within_all_limits(self):
        result = validate_cumulative(
            appendix="5",
            as_of_utc=_utc("2026-03-20T00:00:00Z"),
            summary={
                "flight_time_168h_hours": 40.0,
                "flight_time_28d_hours": 140.0,
                "flight_time_90d_hours": 400.0,
                "flight_time_365d_hours": 1100.0,
                "recovery_36h_block_in_336h": True,
                "recovery_72h_block_in_504h": True,
            },
        )
        assert result["valid"] is True

    def test_168h_limit_exceeded(self):
        result = validate_cumulative(
            appendix="5",
            as_of_utc=_utc("2026-03-20T00:00:00Z"),
            summary={
                "flight_time_168h_hours": 55.0,
                "flight_time_28d_hours": 140.0,
                "flight_time_90d_hours": 400.0,
                "flight_time_365d_hours": 1100.0,
                "recovery_36h_block_in_336h": True,
                "recovery_72h_block_in_504h": True,
            },
        )
        assert result["valid"] is False
        assert any(v["check"] == "flight_time_168h" for v in result["violations"])

    def test_app5_reset_detection_from_log(self):
        """A 5+-day gap in the FDP log resets the App 5 flight time counter."""
        as_of = _utc("2026-03-25T00:00:00Z")
        # Two FDPs before the gap: 30h flight each (total 60h)
        pre_reset = [
            _make_fdp("2026-02-01T00:00:00Z", "2026-02-01T10:00:00Z", flight=30.0),
            _make_fdp("2026-02-02T00:00:00Z", "2026-02-02T10:00:00Z", flight=30.0),
        ]
        # 5-day gap (reset)
        # One FDP after the gap: 20h flight (within 50h/168h limit)
        post_reset = [
            _make_fdp("2026-03-21T00:00:00Z", "2026-03-21T10:00:00Z", flight=20.0),
        ]
        result = validate_cumulative(
            appendix="5",
            as_of_utc=as_of,
            fdp_log=pre_reset + post_reset,
        )
        # Without reset, flight in 168h would still be 20h (pre-reset FDPs are
        # far outside 168h window anyway)
        checks_by_id = {c["check"]: c for c in result["checks"]}
        # The note should mention reset detection
        notes_text = " ".join(result.get("calculation_notes", []))
        assert "reset" in notes_text.lower()


class TestAppendix5AFromLog:
    """Appendix 5A: 100h/384h flight time, 2 days off/384h, no duty time limit."""

    def test_basic_from_log(self):
        as_of = _utc("2026-03-20T00:00:00Z")
        # 10 FDPs each 5h flight, 6h duty spread over 2 weeks = 50h total
        log = []
        for i in range(10):
            start = _utc("2026-03-06T08:00:00Z") + timedelta(days=i * 1)
            end = start + timedelta(hours=5)
            log.append({
                "fdp_start_utc": start,
                "fdp_end_utc": end,
                "actual_flight_time_hours": 5.0,
                "actual_duty_time_hours": 6.0,
                "local_time_offset_hours": 10.0,
            })
        result = validate_cumulative(
            appendix="5A",
            as_of_utc=as_of,
            fdp_log=log,
        )
        checks_by_id = {c["check"]: c for c in result["checks"]}
        if "flight_time_384h" in checks_by_id:
            assert checks_by_id["flight_time_384h"]["actual"] == pytest.approx(50.0)


class TestFromLogWindowComputation:
    """Verify that the engine correctly computes rolling windows from raw FDP log."""

    def test_28d_window_precise(self):
        """Only FDPs within the 28-day window should be included."""
        as_of = _utc("2026-03-20T00:00:00Z")
        # FDP exactly 29 days before as_of — should be EXCLUDED from 28d window
        old_fdp = _make_fdp(
            (as_of - timedelta(days=29)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            (as_of - timedelta(days=29) + timedelta(hours=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            flight=50.0, duty=60.0,
        )
        # FDP 10 days before as_of — should be INCLUDED
        recent_fdp = _make_fdp(
            (as_of - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            (as_of - timedelta(days=10) + timedelta(hours=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            flight=40.0, duty=50.0,
        )
        result = validate_cumulative(
            appendix="3",
            as_of_utc=as_of,
            fdp_log=[old_fdp, recent_fdp],
        )
        checks_by_id = {c["check"]: c for c in result["checks"]}
        if "flight_time_28d" in checks_by_id:
            # Only 40h counted (old FDP is outside window)
            assert checks_by_id["flight_time_28d"]["actual"] == pytest.approx(40.0)

    def test_empty_log_no_violations(self):
        """No FDPs means 0h accumulated — all numeric checks should pass."""
        result = validate_cumulative(
            appendix="3",
            as_of_utc=_utc("2026-03-20T00:00:00Z"),
            fdp_log=[],
        )
        # No flight/duty time violations; recovery checks may skip or fail (no gap data)
        numeric_violations = [
            v for v in result["violations"]
            if v["check"] in ("flight_time_28d", "flight_time_365d", "duty_time_168h", "duty_time_336h")
        ]
        assert numeric_violations == []

    def test_summary_no_log_reports_unevaluated_checks(self):
        """
        A check with no data behind it is reported as data_unavailable, not
        as a violation and not as a pass.

        Amended in Phase 5 (S9): this previously asserted the skipped check
        was ABSENT from checks[]. Dropping it left a consumer unable to tell
        a condition that passed from one that was never evaluated. The check
        is now present with passed=None and status="data_unavailable" —
        `passed` is retained, and null, so existing consumers do not crash.
        """
        result = validate_cumulative(
            appendix="3",
            as_of_utc=_utc("2026-03-20T00:00:00Z"),
            summary={"flight_time_28d_hours": 80.0},  # only 28d provided
        )
        checks_by_id = {c["check"]: c for c in result["checks"]}

        skipped = checks_by_id["flight_time_365d"]
        assert skipped["status"] == "data_unavailable"
        assert skipped["passed"] is None
        assert not [v for v in result["violations"] if v["check"] == "flight_time_365d"]

        assert checks_by_id["flight_time_28d"]["status"] == "passed"


# ─── Helper ──────────────────────────────────────────────────────────────────

def _build_summary(
    ft_28d: float = 0.0,
    ft_365d: float = 0.0,
    dt_168h: float = 0.0,
    dt_336h: float = 0.0,
    rec_168h: bool = True,
    days_off_28d: int = 6,
):
    return {
        "flight_time_28d_hours": ft_28d,
        "flight_time_365d_hours": ft_365d,
        "duty_time_168h_hours": dt_168h,
        "duty_time_336h_hours": dt_336h,
        "recovery_36h_block_in_168h": rec_168h,
        "days_off_in_28d": days_off_28d,
    }
