"""
Phase 1 remediation regression tests — S1 and S8.

Each test asserts the *specific* wrong output the API produced before the fix,
not merely that the endpoint responds. The comments record what v0.5.0 returned
so a regression is recognisable rather than just red.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
BASE = "/api/v1/cao481"


def _fdp_event(start="2026-03-23T23:00:00Z", end="2026-03-24T07:00:00Z", **kw):
    event = {
        "event_type": "fdp",
        "fdp_start_utc": start,
        "fdp_end_utc": end,
        "actual_flight_time_hours": 6,
        "actual_duty_time_hours": 8,
        "local_time_offset_hours": 8,
        "sectors": 3,
    }
    event.update(kw)
    return event


NON_ZERO_SUMMARY = {
    "flight_time_28d_hours": 999,
    "flight_time_365d_hours": 9999,
    "duty_time_168h_hours": 500,
    "duty_time_336h_hours": 900,
    "days_off_in_28d": 0,
    "recovery_36h_block_in_168h": False,
}


# ═══════════════════════════════════════════════════════════════════════
# S1 — prior_summary silently ignored by /validate/roster
# ═══════════════════════════════════════════════════════════════════════

class TestS1PriorSummaryWired:
    """
    v0.5.0 returned valid=true, total_violations=0, and flight_time_28d
    actual=6.0 (the roster's own total) for this payload. Every prior figure
    was discarded because the roster's own FDPs made `combined_log` non-empty,
    which suppressed the summary.
    """

    @pytest.fixture
    def payload(self):
        return {
            "appendix": "3",
            "roster_start_utc": "2026-03-23T00:00:00Z",
            "roster_end_utc": "2026-03-25T00:00:00Z",
            "events": [_fdp_event()],
            "prior_summary": dict(NON_ZERO_SUMMARY),
        }

    def test_returns_invalid_with_six_cumulative_violations(self, payload):
        body = client.post(f"{BASE}/validate/roster", json=payload).json()

        assert body["valid"] is False, "v0.5.0 returned valid=true here"
        assert body["summary"]["cumulative_violations"] == 6

        failed = {
            check["check"]
            for check in body["cumulative_result"]["checks"]
            if check["passed"] is False
        }
        assert failed == {
            "flight_time_28d",
            "flight_time_365d",
            "duty_time_168h",
            "duty_time_336h",
            "days_off_in_28d",
            "recovery_36h_2ln_in_168h",
        }

    def test_flight_time_28d_is_not_the_roster_only_total(self, payload):
        body = client.post(f"{BASE}/validate/roster", json=payload).json()
        actual = next(
            c["actual"]
            for c in body["cumulative_result"]["checks"]
            if c["check"] == "flight_time_28d"
        )
        # v0.5.0 reported 6.0 — the roster's own flight time, prior discarded.
        assert actual != 6.0
        assert actual == pytest.approx(1005.0)  # 999 prior + 6 roster

    def test_hour_windows_never_fall_below_the_roster_only_total(self, payload):
        """
        Acceptance criterion: for any non-zero prior_summary, every hour-based
        cumulative actual is >= the roster-only total for that window.
        """
        with_prior = client.post(f"{BASE}/validate/roster", json=payload).json()

        roster_only_payload = dict(payload)
        roster_only_payload.pop("prior_summary")
        roster_only = client.post(
            f"{BASE}/validate/roster", json=roster_only_payload
        ).json()

        baseline = {
            c["check"]: c["actual"] for c in roster_only["cumulative_result"]["checks"]
        }
        for check in with_prior["cumulative_result"]["checks"]:
            if not check["check"].startswith(("flight_time_", "duty_time_")):
                continue  # days-off and recovery are assertions, not totals
            assert check["actual"] >= baseline[check["check"]], check["check"]

    def test_matches_validate_cumulative_for_the_same_summary(self):
        """
        The same summary must produce the same actuals on both endpoints.
        Compared on a roster with no FDPs of its own, so the two calls are
        describing an identical window.
        """
        summary = {"flight_time_28d_hours": 999, "duty_time_168h_hours": 500}

        roster = client.post(
            f"{BASE}/validate/roster",
            json={
                "appendix": "3",
                "roster_start_utc": "2026-03-23T00:00:00Z",
                "roster_end_utc": "2026-03-25T00:00:00Z",
                "events": [
                    {
                        "event_type": "rest_day",
                        "start_utc": "2026-03-23T00:00:00Z",
                        "end_utc": "2026-03-25T00:00:00Z",
                        "count": 2,
                        "includes_local_night": True,
                    }
                ],
                "prior_summary": summary,
            },
        ).json()

        cumulative = client.post(
            f"{BASE}/validate/cumulative",
            json={
                "appendix": "3",
                "as_of_utc": "2026-03-25T00:00:00Z",
                "summary": summary,
            },
        ).json()

        assert {
            c["check"]: c["actual"] for c in roster["cumulative_result"]["checks"]
        } == {c["check"]: c["actual"] for c in cumulative["checks"]}

    def test_supplying_both_warns_and_prefers_the_log(self):
        body = client.post(
            f"{BASE}/validate/roster",
            json={
                "appendix": "3",
                "roster_start_utc": "2026-03-23T00:00:00Z",
                "roster_end_utc": "2026-03-25T00:00:00Z",
                "events": [_fdp_event()],
                "prior_summary": {"flight_time_28d_hours": 999},
                "prior_fdp_log": [
                    {
                        "fdp_start_utc": "2026-03-20T00:00:00Z",
                        "fdp_end_utc": "2026-03-20T10:00:00Z",
                        "actual_flight_time_hours": 10,
                        "actual_duty_time_hours": 10,
                        "local_time_offset_hours": 8,
                    }
                ],
            },
        ).json()

        assert any(
            "prior_summary" in w and "prior_fdp_log" in w for w in body["warnings"]
        ), "the ignored field must be named, not silently dropped"

        actual = next(
            c["actual"]
            for c in body["cumulative_result"]["checks"]
            if c["check"] == "flight_time_28d"
        )
        assert actual == pytest.approx(16.0)  # log 10 + roster 6; summary ignored

    def test_prior_fdp_log_alone_is_unchanged(self):
        """§6 of the spec: prior_fdp_log already worked. Guard it."""
        body = client.post(
            f"{BASE}/validate/roster",
            json={
                "appendix": "3",
                "roster_start_utc": "2026-03-23T00:00:00Z",
                "roster_end_utc": "2026-03-25T00:00:00Z",
                "events": [_fdp_event()],
                "prior_fdp_log": [
                    {
                        "fdp_start_utc": f"2026-03-{day}T00:00:00Z",
                        "fdp_end_utc": f"2026-03-{day}T10:00:00Z",
                        "actual_flight_time_hours": 10,
                        "actual_duty_time_hours": 10,
                        "local_time_offset_hours": 8,
                    }
                    for day in ("18", "19", "20")
                ],
            },
        ).json()

        actual = next(
            c["actual"]
            for c in body["cumulative_result"]["checks"]
            if c["check"] == "flight_time_28d"
        )
        assert actual == pytest.approx(36.0)  # 3 x 10 prior + 6 roster
        assert body["warnings"] == []


# ═══════════════════════════════════════════════════════════════════════
# S8 — no input validation
# ═══════════════════════════════════════════════════════════════════════

def _detail(response) -> str:
    detail = response.json()["detail"]
    if isinstance(detail, list):
        return " ".join(str(item.get("msg", item)) for item in detail)
    return str(detail)


class TestS8InputValidation:

    def test_negative_fdp_duration_is_rejected(self):
        """
        v0.5.0 returned valid=true with
        'Actual FDP -8.00h <= limit 10.00h' for a transposed start/end.
        """
        response = client.post(
            f"{BASE}/validate/fdp",
            json={
                "appendix": "3",
                "fdp_start_utc": "2026-03-24T10:00:00Z",
                "fdp_end_utc": "2026-03-24T02:00:00Z",
                "local_time_offset_hours": 8,
                "sectors": 2,
            },
        )
        assert response.status_code == 422
        assert "fdp_end_utc" in _detail(response)

    def test_out_of_range_offset_is_rejected_not_wrapped(self):
        """v0.5.0 accepted 50 and wrapped it mod 24 into a plausible band."""
        response = client.post(
            f"{BASE}/validate/fdp",
            json={
                "appendix": "3",
                "fdp_start_utc": "2026-03-24T10:00:00Z",
                "fdp_end_utc": "2026-03-24T20:00:00Z",
                "local_time_offset_hours": 50,
                "sectors": 2,
            },
        )
        assert response.status_code == 422
        assert "local_time_offset_hours" in _detail(response)

    @pytest.mark.parametrize("offset", [5.5, 8.75, 12.75, -12, 14, 0])
    def test_real_fractional_and_boundary_offsets_still_work(self, offset):
        """IST +5.5, Eucla +8.75, Chatham +12.75 are legitimate."""
        response = client.post(
            f"{BASE}/validate/fdp",
            json={
                "appendix": "3",
                "fdp_start_utc": "2026-03-24T10:00:00Z",
                "fdp_end_utc": "2026-03-24T18:00:00Z",
                "local_time_offset_hours": offset,
                "sectors": 2,
            },
        )
        assert response.status_code == 200

    def test_acclimatised_offset_range_is_checked(self):
        response = client.post(
            f"{BASE}/calculate/max-fdp",
            json={
                "appendix": "2",
                "fdp_start_utc": "2026-03-24T10:00:00Z",
                "local_time_offset_hours": 8,
                "sectors": 2,
                "acclimatisation": {
                    "state": "acclimatised",
                    "acclimatised_time_offset_hours": -20,
                },
            },
        )
        assert response.status_code == 422
        assert "acclimatised_time_offset_hours" in _detail(response)

    def test_duration_disagreeing_with_timestamps_is_rejected(self):
        response = client.post(
            f"{BASE}/validate/off-duty",
            json={
                "appendix": "3",
                "actual_off_duty_hours": 14.5,
                "reduction_claimed": False,
                "preceding_fdp": {
                    "start_utc": "2026-03-24T00:00:00Z",
                    "end_utc": "2026-03-24T14:00:00Z",
                    "duration_hours": 9,
                    "location": "away",
                },
            },
        )
        assert response.status_code == 422
        assert "duration_hours" in _detail(response)

    def test_duration_within_one_minute_is_accepted(self):
        response = client.post(
            f"{BASE}/validate/off-duty",
            json={
                "appendix": "3",
                "actual_off_duty_hours": 16.0,
                "reduction_claimed": False,
                "preceding_fdp": {
                    "start_utc": "2026-03-24T00:00:00Z",
                    "end_utc": "2026-03-24T10:00:00Z",
                    "duration_hours": 10.008,  # 30 seconds of drift
                    "location": "away",
                },
            },
        )
        assert response.status_code == 200

    def test_reversed_split_duty_rest_window_is_rejected(self):
        response = client.post(
            f"{BASE}/calculate/max-fdp",
            json={
                "appendix": "3",
                "fdp_start_utc": "2026-03-24T10:00:00Z",
                "local_time_offset_hours": 8,
                "sectors": 2,
                "split_duty": {
                    "rest_start_utc": "2026-03-24T19:00:00Z",
                    "rest_end_utc": "2026-03-24T14:00:00Z",
                    "accommodation": "sleeping",
                    "duration_hours": 5,
                },
            },
        )
        assert response.status_code == 422
        assert "rest_end_utc" in _detail(response)

    def test_reversed_roster_window_is_rejected(self):
        response = client.post(
            f"{BASE}/validate/roster",
            json={
                "appendix": "3",
                "roster_start_utc": "2026-03-27T00:00:00Z",
                "roster_end_utc": "2026-03-23T00:00:00Z",
                "events": [_fdp_event()],
            },
        )
        assert response.status_code == 422
        assert "roster_end_utc" in _detail(response)

    def test_out_of_order_events_are_rejected(self):
        response = client.post(
            f"{BASE}/validate/roster",
            json={
                "appendix": "3",
                "roster_start_utc": "2026-03-23T00:00:00Z",
                "roster_end_utc": "2026-03-27T00:00:00Z",
                "events": [
                    _fdp_event("2026-03-25T23:00:00Z", "2026-03-26T07:00:00Z"),
                    _fdp_event("2026-03-23T23:00:00Z", "2026-03-24T07:00:00Z"),
                ],
            },
        )
        assert response.status_code == 422
        assert "chronological" in _detail(response)

    def test_overlapping_fdps_are_rejected(self):
        response = client.post(
            f"{BASE}/validate/roster",
            json={
                "appendix": "3",
                "roster_start_utc": "2026-03-23T00:00:00Z",
                "roster_end_utc": "2026-03-27T00:00:00Z",
                "events": [
                    _fdp_event("2026-03-23T23:00:00Z", "2026-03-24T07:00:00Z"),
                    _fdp_event("2026-03-24T03:00:00Z", "2026-03-24T11:00:00Z"),
                ],
            },
        )
        assert response.status_code == 422
        assert "overlap" in _detail(response)

    def test_sequence_events_are_validated_too(self):
        response = client.post(
            f"{BASE}/validate/sequence",
            json={
                "appendix": "3",
                "events": [
                    {
                        "event_type": "off_duty",
                        "start_utc": "2026-03-25T08:00:00Z",
                        "end_utc": "2026-03-25T22:00:00Z",
                        "duration_hours": 99.0,
                        "location": "away",
                    }
                ],
            },
        )
        assert response.status_code == 422
        assert "duration_hours" in _detail(response)

    def test_prior_fdp_log_records_are_validated(self):
        response = client.post(
            f"{BASE}/validate/roster",
            json={
                "appendix": "3",
                "roster_start_utc": "2026-03-23T00:00:00Z",
                "roster_end_utc": "2026-03-25T00:00:00Z",
                "events": [_fdp_event()],
                "prior_fdp_log": [
                    {
                        "fdp_start_utc": "2026-03-20T10:00:00Z",
                        "fdp_end_utc": "2026-03-20T00:00:00Z",
                        "actual_flight_time_hours": 10,
                        "actual_duty_time_hours": 10,
                    }
                ],
            },
        )
        assert response.status_code == 422


class TestS8Invariant:
    """No valid=true response may carry a negative duration actual."""

    @pytest.mark.parametrize(
        "start,end",
        [
            ("2026-03-24T10:00:00Z", "2026-03-24T02:00:00Z"),
            ("2026-03-24T10:00:00Z", "2026-03-24T10:00:00Z"),
            ("2026-03-25T00:00:00Z", "2026-03-23T00:00:00Z"),
        ],
    )
    def test_no_valid_response_has_a_negative_duration(self, start, end):
        response = client.post(
            f"{BASE}/validate/fdp",
            json={
                "appendix": "3",
                "fdp_start_utc": start,
                "fdp_end_utc": end,
                "local_time_offset_hours": 8,
                "sectors": 2,
            },
        )
        if response.status_code != 200:
            return  # rejected outright, which is the intended behaviour
        body = response.json()
        negatives = [
            c for c in body["checks"] if c["actual"] is not None and c["actual"] < 0
        ]
        assert not (body["valid"] and negatives), (
            f"valid=true with negative actuals: {negatives}"
        )
