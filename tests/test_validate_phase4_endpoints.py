"""
tests/test_validate_phase4_endpoints.py — HTTP endpoint tests for Phase 4.

Tests POST /validate/cumulative and POST /validate/sequence endpoints.
Uses httpx.AsyncClient against the FastAPI test transport.
"""

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app

BASE = "http://test"
PREFIX = "/api/v1/cao481"


@pytest.fixture
def transport():
    return ASGITransport(app=app)


# ═══════════════════════════════════════════════════════════════════════
# POST /validate/cumulative
# ═══════════════════════════════════════════════════════════════════════

class TestValidateCumulativeEndpoint:

    @pytest.mark.anyio
    async def test_valid_summary_all_under_limits(self, transport):
        async with AsyncClient(transport=transport, base_url=BASE) as client:
            resp = await client.post(
                f"{PREFIX}/validate/cumulative",
                json={
                    "appendix": "3",
                    "as_of_utc": "2026-03-20T00:00:00Z",
                    "summary": {
                        "flight_time_28d_hours": 80.0,
                        "flight_time_365d_hours": 800.0,
                        "duty_time_168h_hours": 50.0,
                        "duty_time_336h_hours": 90.0,
                        "recovery_36h_block_in_168h": True,
                        "days_off_in_28d": 7,
                    },
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["appendix"] == "3"
        assert isinstance(data["checks"], list)
        assert data["violations"] == []

    @pytest.mark.anyio
    async def test_flight_time_28d_exceeded_returns_violation(self, transport):
        async with AsyncClient(transport=transport, base_url=BASE) as client:
            resp = await client.post(
                f"{PREFIX}/validate/cumulative",
                json={
                    "appendix": "3",
                    "as_of_utc": "2026-03-20T00:00:00Z",
                    "summary": {
                        "flight_time_28d_hours": 105.0,
                        "flight_time_365d_hours": 800.0,
                        "duty_time_168h_hours": 50.0,
                        "duty_time_336h_hours": 90.0,
                        "recovery_36h_block_in_168h": True,
                        "days_off_in_28d": 7,
                    },
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        violation_checks = [v["check"] for v in data["violations"]]
        assert "flight_time_28d" in violation_checks

    @pytest.mark.anyio
    async def test_requires_log_or_summary(self, transport):
        async with AsyncClient(transport=transport, base_url=BASE) as client:
            resp = await client.post(
                f"{PREFIX}/validate/cumulative",
                json={
                    "appendix": "3",
                    "as_of_utc": "2026-03-20T00:00:00Z",
                    # Neither fdp_log nor summary provided
                },
            )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_fdp_log_computes_windows(self, transport):
        async with AsyncClient(transport=transport, base_url=BASE) as client:
            resp = await client.post(
                f"{PREFIX}/validate/cumulative",
                json={
                    "appendix": "3",
                    "as_of_utc": "2026-03-20T00:00:00Z",
                    "fdp_log": [
                        {
                            "fdp_start_utc": "2026-03-10T22:00:00Z",
                            "fdp_end_utc": "2026-03-11T08:00:00Z",
                            "actual_flight_time_hours": 8.0,
                            "actual_duty_time_hours": 10.0,
                            "local_time_offset_hours": 10.0,
                        },
                        {
                            "fdp_start_utc": "2026-03-12T22:00:00Z",
                            "fdp_end_utc": "2026-03-13T08:00:00Z",
                            "actual_flight_time_hours": 7.5,
                            "actual_duty_time_hours": 9.5,
                            "local_time_offset_hours": 10.0,
                        },
                    ],
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["appendix"] == "3"
        checks_by_id = {c["check"]: c for c in data["checks"]}
        if "flight_time_28d" in checks_by_id:
            assert checks_by_id["flight_time_28d"]["actual"] == pytest.approx(15.5)

    @pytest.mark.anyio
    async def test_unknown_appendix_returns_422(self, transport):
        async with AsyncClient(transport=transport, base_url=BASE) as client:
            resp = await client.post(
                f"{PREFIX}/validate/cumulative",
                json={
                    "appendix": "99",
                    "as_of_utc": "2026-03-20T00:00:00Z",
                    "summary": {"flight_time_28d_hours": 50.0},
                },
            )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_appendix_4a_specific_limits(self, transport):
        """Appendix 4A has 50h/28d flight time limit (not 100h)."""
        async with AsyncClient(transport=transport, base_url=BASE) as client:
            resp = await client.post(
                f"{PREFIX}/validate/cumulative",
                json={
                    "appendix": "4A",
                    "as_of_utc": "2026-03-20T00:00:00Z",
                    "summary": {
                        "flight_time_28d_hours": 55.0,
                        "duty_time_168h_hours": 40.0,
                        "duty_time_336h_hours": 75.0,
                        "days_off_in_384h": 3,
                    },
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert any(v["check"] == "flight_time_28d" for v in data["violations"])

    @pytest.mark.anyio
    async def test_appendix_1_passes(self, transport):
        async with AsyncClient(transport=transport, base_url=BASE) as client:
            resp = await client.post(
                f"{PREFIX}/validate/cumulative",
                json={
                    "appendix": "1",
                    "as_of_utc": "2026-03-20T00:00:00Z",
                    "summary": {
                        "flight_time_28d_hours": 90.0,
                        "flight_time_365d_hours": 900.0,
                        "recovery_36h_block_in_168h": True,
                        "days_off_in_28d": 7,
                    },
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True

    @pytest.mark.anyio
    async def test_response_schema_shape(self, transport):
        """Verify required keys are present and typed correctly."""
        async with AsyncClient(transport=transport, base_url=BASE) as client:
            resp = await client.post(
                f"{PREFIX}/validate/cumulative",
                json={
                    "appendix": "3",
                    "as_of_utc": "2026-03-20T00:00:00Z",
                    "summary": {"flight_time_28d_hours": 50.0},
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "valid" in data
        assert "appendix" in data
        assert "violations" in data
        assert "checks" in data
        assert "warnings" in data
        assert "calculation_notes" in data
        assert isinstance(data["valid"], bool)
        assert isinstance(data["violations"], list)
        assert isinstance(data["checks"], list)


# ═══════════════════════════════════════════════════════════════════════
# POST /validate/sequence
# ═══════════════════════════════════════════════════════════════════════

_TWO_FDP_SEQUENCE = {
    "appendix": "3",
    "events": [
        {
            "event_type": "fdp",
            "fdp_start_utc": "2026-03-24T22:00:00Z",
            "fdp_end_utc": "2026-03-25T08:00:00Z",
            "actual_flight_time_hours": 7.5,
            "actual_duty_time_hours": 10.0,
            "local_time_offset_hours": 10.0,
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
            "actual_flight_time_hours": 7.5,
            "actual_duty_time_hours": 10.0,
            "local_time_offset_hours": 10.0,
            "sectors": 3,
        },
    ],
}


class TestValidateSequenceEndpoint:

    @pytest.mark.anyio
    async def test_valid_two_fdp_sequence(self, transport):
        async with AsyncClient(transport=transport, base_url=BASE) as client:
            resp = await client.post(
                f"{PREFIX}/validate/sequence",
                json=_TWO_FDP_SEQUENCE,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["appendix"] == "3"
        assert isinstance(data["valid"], bool)
        check_ids = [c["check"] for c in data["checks"]]
        assert any(ci.startswith("fdp1_") for ci in check_ids)
        assert any(ci.startswith("fdp2_") for ci in check_ids)
        assert any(ci.startswith("odp1_") for ci in check_ids)
        assert any(ci.startswith("cumulative_") for ci in check_ids)

    @pytest.mark.anyio
    async def test_empty_events_rejected(self, transport):
        async with AsyncClient(transport=transport, base_url=BASE) as client:
            resp = await client.post(
                f"{PREFIX}/validate/sequence",
                json={"appendix": "3", "events": []},
            )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_fdp_too_long_produces_violation(self, transport):
        """An 18h FDP starting at 0900 local should fail the FDP limit check."""
        async with AsyncClient(transport=transport, base_url=BASE) as client:
            resp = await client.post(
                f"{PREFIX}/validate/sequence",
                json={
                    "appendix": "3",
                    "events": [
                        {
                            "event_type": "fdp",
                            "fdp_start_utc": "2026-03-24T23:00:00Z",  # 0900 local
                            "fdp_end_utc": "2026-03-25T17:00:00Z",    # 18h later
                            "actual_flight_time_hours": 10.0,
                            "actual_duty_time_hours": 18.0,
                            "local_time_offset_hours": 10.0,
                            "sectors": 3,
                        },
                    ],
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert any("fdp_within_limit" in v["check"] for v in data["violations"])

    @pytest.mark.anyio
    async def test_unknown_appendix_returns_422(self, transport):
        async with AsyncClient(transport=transport, base_url=BASE) as client:
            resp = await client.post(
                f"{PREFIX}/validate/sequence",
                json={
                    "appendix": "99",
                    "events": [
                        {
                            "event_type": "fdp",
                            "fdp_start_utc": "2026-03-24T22:00:00Z",
                            "fdp_end_utc": "2026-03-25T08:00:00Z",
                            "actual_flight_time_hours": 7.5,
                            "actual_duty_time_hours": 10.0,
                            "local_time_offset_hours": 10.0,
                            "sectors": 3,
                        },
                    ],
                },
            )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_wocl_check_appears_on_4th_infringing_fdp(self, transport):
        """After 3 WOCL FDPs without a LN, 4th should include a §13.2 check."""
        # Local 2300+10 = 1300Z; crosses WOCL
        wocl_fdp = lambda d: {
            "event_type": "fdp",
            "fdp_start_utc": f"2026-03-{d:02d}T13:00:00Z",
            "fdp_end_utc": f"2026-03-{d:02d}T21:00:00Z",
            "actual_flight_time_hours": 5.0,
            "actual_duty_time_hours": 8.0,
            "local_time_offset_hours": 10.0,
            "sectors": 2,
        }
        short_odp = lambda d: {
            "event_type": "off_duty",
            "start_utc": f"2026-03-{d:02d}T21:00:00Z",
            "end_utc": f"2026-03-{d+1:02d}T07:00:00Z",
            "duration_hours": 10.0,
            "location": "away",
        }
        events = [
            wocl_fdp(22), short_odp(22),
            wocl_fdp(23), short_odp(23),
            wocl_fdp(24), short_odp(24),
            wocl_fdp(25),  # 4th
        ]
        async with AsyncClient(transport=transport, base_url=BASE) as client:
            resp = await client.post(
                f"{PREFIX}/validate/sequence",
                json={"appendix": "3", "events": events},
            )
        assert resp.status_code == 200
        data = resp.json()
        violation_checks = [v["check"] for v in data["violations"]]
        assert any("wocl_local_night_required" in vc for vc in violation_checks)

    @pytest.mark.anyio
    async def test_removed_fields_are_silently_ignored_not_rejected(self, transport):
        """
        crosses_wocl and includes_local_night were removed from the off_duty/fdp
        event schemas (both are now always computed server-side). A caller still
        sending them — including lying in the caller's favour — must get a 200
        with the correct, derived result, not a 422 and not a bypassed check.
        """
        wocl_fdp = lambda d: {
            "event_type": "fdp",
            "fdp_start_utc": f"2026-03-{d:02d}T13:00:00Z",
            "fdp_end_utc": f"2026-03-{d:02d}T21:00:00Z",
            "actual_flight_time_hours": 5.0,
            "actual_duty_time_hours": 8.0,
            "local_time_offset_hours": 10.0,
            "sectors": 2,
            "crosses_wocl": False,  # lie: this FDP genuinely crosses WOCL
        }
        short_odp = lambda d: {
            "event_type": "off_duty",
            "start_utc": f"2026-03-{d:02d}T21:00:00Z",
            "end_utc": f"2026-03-{d+1:02d}T07:00:00Z",
            "duration_hours": 10.0,
            "location": "away",
            "includes_local_night": True,  # lie: this ODP does not span a full local night
        }
        events = [
            wocl_fdp(22), short_odp(22),
            wocl_fdp(23), short_odp(23),
            wocl_fdp(24), short_odp(24),
            wocl_fdp(25),
        ]
        async with AsyncClient(transport=transport, base_url=BASE) as client:
            resp = await client.post(
                f"{PREFIX}/validate/sequence",
                json={"appendix": "3", "events": events},
            )
        assert resp.status_code == 200
        data = resp.json()
        violation_checks = [v["check"] for v in data["violations"]]
        assert any("wocl_local_night_required" in vc for vc in violation_checks)

    @pytest.mark.anyio
    async def test_response_schema_shape(self, transport):
        async with AsyncClient(transport=transport, base_url=BASE) as client:
            resp = await client.post(
                f"{PREFIX}/validate/sequence",
                json=_TWO_FDP_SEQUENCE,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "valid" in data
        assert "appendix" in data
        assert "violations" in data
        assert "checks" in data
        assert "warnings" in data
        assert "calculation_notes" in data

    @pytest.mark.anyio
    async def test_single_fdp_sequence(self, transport):
        async with AsyncClient(transport=transport, base_url=BASE) as client:
            resp = await client.post(
                f"{PREFIX}/validate/sequence",
                json={
                    "appendix": "3",
                    "events": [
                        {
                            "event_type": "fdp",
                            "fdp_start_utc": "2026-03-24T22:00:00Z",
                            "fdp_end_utc": "2026-03-25T08:00:00Z",
                            "actual_flight_time_hours": 7.5,
                            "actual_duty_time_hours": 10.0,
                            "local_time_offset_hours": 10.0,
                            "sectors": 3,
                        },
                    ],
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["appendix"] == "3"

    @pytest.mark.anyio
    async def test_discriminator_rejects_unknown_event_type(self, transport):
        async with AsyncClient(transport=transport, base_url=BASE) as client:
            resp = await client.post(
                f"{PREFIX}/validate/sequence",
                json={
                    "appendix": "3",
                    "events": [
                        {
                            "event_type": "standby",  # invalid
                            "start_utc": "2026-03-24T22:00:00Z",
                        },
                    ],
                },
            )
        assert resp.status_code == 422
