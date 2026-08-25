"""
HTTP endpoint tests for POST /validate/roster (Phase 5).

Uses httpx.AsyncClient with ASGITransport to test the FastAPI app directly.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

PREFIX = "/api/v1/cao481"
pytestmark = pytest.mark.anyio


# ─── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def transport():
    return ASGITransport(app=app)


# ─── Helpers ─────────────────────────────────────────────────────────

def _two_fdp_payload(appendix: str = "3") -> dict:
    return {
        "appendix": appendix,
        "roster_start_utc": "2026-03-24T00:00:00Z",
        "roster_end_utc": "2026-03-27T00:00:00Z",
        "events": [
            {
                "event_type": "fdp",
                "fdp_start_utc": "2026-03-24T22:00:00Z",
                "fdp_end_utc": "2026-03-25T08:00:00Z",
                "actual_flight_time_hours": 7.5,
                "actual_duty_time_hours": 10.0,
                "local_time_offset_hours": 8.0,
                "sectors": 3,
            },
            {
                "event_type": "off_duty",
                "start_utc": "2026-03-25T08:00:00Z",
                "end_utc": "2026-03-25T22:00:00Z",
                "duration_hours": 14.0,
                "location": "away",
            },
            {
                "event_type": "fdp",
                "fdp_start_utc": "2026-03-25T22:00:00Z",
                "fdp_end_utc": "2026-03-26T08:00:00Z",
                "actual_flight_time_hours": 8.0,
                "actual_duty_time_hours": 10.0,
                "local_time_offset_hours": 8.0,
                "sectors": 3,
            },
        ],
    }


# ─── Tests ───────────────────────────────────────────────────────────

class TestValidateRosterEndpoint:
    async def test_valid_roster_returns_200(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/validate/roster", json=_two_fdp_payload())
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert body["summary"]["total_violations"] == 0
        # Phase 5 (S9): no prior history, so the cumulative windows are
        # data_unavailable — reported, not treated as a breach.
        assert body["summary"]["checks_skipped"] > 0

    async def test_response_schema_shape(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/validate/roster", json=_two_fdp_payload())
        data = resp.json()
        assert resp.status_code == 200
        for key in ("valid", "appendix", "roster_start_utc", "roster_end_utc",
                     "summary", "fdp_results", "odp_results", "sequence_checks",
                     "sequence_violations", "cumulative_result", "all_violations", "warnings"):
            assert key in data, f"Missing key: {key}"

    async def test_summary_schema_shape(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/validate/roster", json=_two_fdp_payload())
        s = resp.json()["summary"]
        for key in ("total_fdps", "total_off_duty_periods", "total_rest_days",
                     "total_flight_time_hours", "total_duty_time_hours",
                     "fdp_violations", "odp_violations", "sequence_violations",
                     "cumulative_violations", "total_violations"):
            assert key in s, f"Missing summary key: {key}"

    async def test_fdp_results_populated(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/validate/roster", json=_two_fdp_payload())
        data = resp.json()
        assert len(data["fdp_results"]) == 2
        for item in data["fdp_results"]:
            assert "fdp_number" in item
            assert "valid" in item
            assert "violations" in item
            assert "checks" in item

    async def test_odp_results_populated(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/validate/roster", json=_two_fdp_payload())
        data = resp.json()
        assert len(data["odp_results"]) == 1
        odp = data["odp_results"][0]
        assert odp["valid"] is True
        assert odp["odp_number"] == 1

    async def test_computed_crosses_wocl_and_includes_local_night_in_response(self, transport):
        """
        crosses_wocl (per FDP) and includes_local_night (per ODP) are no longer
        request fields — confirm they're present as computed values on
        fdp_results / odp_results instead, matching the events' real timestamps
        (0900 local FDPs don't cross WOCL; the 14h off-duty period 2200-1200
        local fully spans a local night).
        """
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/validate/roster", json=_two_fdp_payload())
        data = resp.json()
        assert data["fdp_results"][0]["crosses_wocl"] is False
        assert data["fdp_results"][1]["crosses_wocl"] is False
        assert data["odp_results"][0]["includes_local_night"] is True

    async def test_includes_local_night_boundary_ends_at_0500_is_true(self, transport):
        """Off-duty period ending exactly 0500 local fully spans 2200-0500 (§6.1) —
        the boundary is inclusive."""
        payload = {
            "appendix": "3",
            "roster_start_utc": "2026-03-24T00:00:00Z",
            "roster_end_utc": "2026-03-27T00:00:00Z",
            "events": [
                {
                    "event_type": "fdp",
                    "fdp_start_utc": "2026-03-24T22:00:00Z",  # local 0600
                    "fdp_end_utc": "2026-03-25T05:00:00Z",     # local 1300
                    "actual_flight_time_hours": 5.0,
                    "actual_duty_time_hours": 7.0,
                    "local_time_offset_hours": 8.0,
                    "sectors": 2,
                },
                {
                    "event_type": "off_duty",
                    "start_utc": "2026-03-25T05:00:00Z",       # local 1300
                    "end_utc": "2026-03-25T21:00:00Z",          # local 0500 next day
                    "duration_hours": 16.0,
                    "location": "away",
                },
            ],
        }
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/validate/roster", json=payload)
        data = resp.json()
        assert data["odp_results"][0]["includes_local_night"] is True

    async def test_includes_local_night_boundary_ends_at_0459_is_false(self, transport):
        """Off-duty period ending one minute earlier, at 0459 local, falls one
        minute short of fully spanning 2200-0500 — must not count."""
        payload = {
            "appendix": "3",
            "roster_start_utc": "2026-03-24T00:00:00Z",
            "roster_end_utc": "2026-03-27T00:00:00Z",
            "events": [
                {
                    "event_type": "fdp",
                    "fdp_start_utc": "2026-03-24T22:00:00Z",
                    "fdp_end_utc": "2026-03-25T05:00:00Z",
                    "actual_flight_time_hours": 5.0,
                    "actual_duty_time_hours": 7.0,
                    "local_time_offset_hours": 8.0,
                    "sectors": 2,
                },
                {
                    "event_type": "off_duty",
                    "start_utc": "2026-03-25T05:00:00Z",
                    "end_utc": "2026-03-25T20:59:00Z",          # local 0459 next day
                    "duration_hours": 15.98,
                    "location": "away",
                },
            ],
        }
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/validate/roster", json=payload)
        data = resp.json()
        assert data["odp_results"][0]["includes_local_night"] is False

    async def test_fdp_violation_appears_in_response(self, transport):
        payload = {
            "appendix": "3",
            "roster_start_utc": "2026-03-24T00:00:00Z",
            "roster_end_utc": "2026-03-25T00:00:00Z",
            "events": [
                {
                    "event_type": "fdp",
                    "fdp_start_utc": "2026-03-24T07:00:00Z",
                    "fdp_end_utc": "2026-03-24T22:00:00Z",  # 15 hours — too long
                    "actual_flight_time_hours": 12.0,
                    "actual_duty_time_hours": 15.0,
                    "local_time_offset_hours": 8.0,
                    "sectors": 2,
                }
            ],
        }
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/validate/roster", json=payload)
        data = resp.json()
        assert resp.status_code == 200
        assert data["valid"] is False
        assert len(data["all_violations"]) > 0
        assert data["fdp_results"][0]["valid"] is False

    async def test_odp_violation_appears_in_response(self, transport):
        payload = {
            "appendix": "3",
            "roster_start_utc": "2026-03-24T00:00:00Z",
            "roster_end_utc": "2026-03-25T00:00:00Z",
            "events": [
                {
                    "event_type": "fdp",
                    "fdp_start_utc": "2026-03-24T22:00:00Z",
                    "fdp_end_utc": "2026-03-25T08:00:00Z",
                    "actual_flight_time_hours": 7.5,
                    "actual_duty_time_hours": 10.0,
                    "local_time_offset_hours": 8.0,
                    "sectors": 3,
                },
                {
                    "event_type": "off_duty",
                    "start_utc": "2026-03-25T08:00:00Z",
                    "end_utc": "2026-03-25T16:00:00Z",
                    "duration_hours": 8.0,  # too short
                    "location": "away",
                },
            ],
        }
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/validate/roster", json=payload)
        data = resp.json()
        assert resp.status_code == 200
        assert data["valid"] is False
        assert data["odp_results"][0]["valid"] is False

    async def test_unknown_appendix_returns_422(self, transport):
        payload = {**_two_fdp_payload(), "appendix": "Z"}
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/validate/roster", json=payload)
        assert resp.status_code == 422

    async def test_missing_events_returns_422(self, transport):
        payload = {
            "appendix": "3",
            "roster_start_utc": "2026-03-24T00:00:00Z",
            "roster_end_utc": "2026-03-27T00:00:00Z",
        }
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/validate/roster", json=payload)
        assert resp.status_code == 422

    async def test_empty_events_returns_422(self, transport):
        payload = {
            "appendix": "3",
            "roster_start_utc": "2026-03-24T00:00:00Z",
            "roster_end_utc": "2026-03-27T00:00:00Z",
            "events": [],
        }
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/validate/roster", json=payload)
        assert resp.status_code == 422

    async def test_rest_day_event_accepted(self, transport):
        payload = {
            "appendix": "3",
            "roster_start_utc": "2026-03-24T00:00:00Z",
            "roster_end_utc": "2026-03-27T00:00:00Z",
            "events": [
                {
                    "event_type": "fdp",
                    "fdp_start_utc": "2026-03-24T22:00:00Z",
                    "fdp_end_utc": "2026-03-25T08:00:00Z",
                    "actual_flight_time_hours": 7.5,
                    "actual_duty_time_hours": 10.0,
                    "local_time_offset_hours": 8.0,
                    "sectors": 3,
                },
                {
                    "event_type": "rest_day",
                    "start_utc": "2026-03-25T10:00:00Z",
                    "end_utc": "2026-03-26T10:00:00Z",
                    "count": 1,
                },
            ],
        }
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/validate/roster", json=payload)
        assert resp.status_code == 200
        assert resp.json()["summary"]["total_rest_days"] == 1

    async def test_prior_fdp_log_accepted(self, transport):
        payload = {
            **_two_fdp_payload(),
            "prior_fdp_log": [
                {
                    "fdp_start_utc": "2026-03-10T22:00:00Z",
                    "fdp_end_utc": "2026-03-11T08:00:00Z",
                    "actual_flight_time_hours": 8.0,
                    "actual_duty_time_hours": 10.0,
                    "local_time_offset_hours": 8.0,
                }
            ],
        }
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/validate/roster", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "cumulative_result" in data
        assert isinstance(data["cumulative_result"], dict)

    async def test_wocl_check_appears_in_sequence_violations(self, transport):
        """4 consecutive WOCL FDPs without local-night ODP → §13.2 violation."""
        events = []
        for i in range(4):
            events.append({
                "event_type": "fdp",
                "fdp_start_utc": f"2026-03-{20+i:02d}T02:00:00Z",
                "fdp_end_utc": f"2026-03-{20+i:02d}T08:00:00Z",
                "actual_flight_time_hours": 5.0,
                "actual_duty_time_hours": 6.5,
                "local_time_offset_hours": 0.0,
                "sectors": 2,
            })
            if i < 3:
                events.append({
                    "event_type": "off_duty",
                    "start_utc": f"2026-03-{20+i:02d}T08:00:00Z",
                    "end_utc": f"2026-03-{20+i+1:02d}T02:00:00Z",
                    "duration_hours": 18.0,
                    "following_includes_local_night": False,
                    "location": "away",
                })
        payload = {
            "appendix": "3",
            "roster_start_utc": "2026-03-20T00:00:00Z",
            "roster_end_utc": "2026-03-24T00:00:00Z",
            "events": events,
        }
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/validate/roster", json=payload)
        data = resp.json()
        assert resp.status_code == 200
        assert data["summary"]["sequence_violations"] >= 1
        assert any("wocl" in v["check"] for v in data["sequence_violations"])

    async def test_all_violations_aggregated(self, transport):
        """all_violations must contain both FDP and ODP violations."""
        payload = {
            "appendix": "3",
            "roster_start_utc": "2026-03-24T00:00:00Z",
            "roster_end_utc": "2026-03-25T00:00:00Z",
            "events": [
                {
                    "event_type": "fdp",
                    "fdp_start_utc": "2026-03-24T07:00:00Z",
                    "fdp_end_utc": "2026-03-24T22:00:00Z",  # 15h — too long
                    "actual_flight_time_hours": 12.0,
                    "actual_duty_time_hours": 15.0,
                    "local_time_offset_hours": 8.0,
                    "sectors": 2,
                },
                {
                    "event_type": "off_duty",
                    "start_utc": "2026-03-24T22:00:00Z",
                    "end_utc": "2026-03-25T06:00:00Z",
                    "duration_hours": 8.0,  # too short
                    "location": "away",
                },
            ],
        }
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/validate/roster", json=payload)
        data = resp.json()
        assert len(data["all_violations"]) >= 2


class TestHealthAfterPhase5:
    async def test_roster_in_available_endpoints(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"{PREFIX}/health")
        data = resp.json()
        assert "/validate/roster" in data["endpoints"]["available"]

    async def test_roster_not_in_planned(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"{PREFIX}/health")
        data = resp.json()
        assert "/validate/roster" not in data["endpoints"]["planned"]

    async def test_version_is_050(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"{PREFIX}/health")
        assert resp.json()["version"] == "0.5.0"
