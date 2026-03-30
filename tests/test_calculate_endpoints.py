"""
Integration tests for the /calculate/* endpoints (Phase 2).

POST /calculate/max-fdp
POST /calculate/min-off-duty
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

API_PREFIX = "/api/v1/cao481"


class TestMaxFdpEndpoint:
    """Tests for POST /calculate/max-fdp."""

    @pytest.mark.anyio
    async def test_basic_request(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"{API_PREFIX}/calculate/max-fdp",
                json={
                    "appendix": "3",
                    "fdp_start_utc": "2026-03-28T22:00:00Z",
                    "local_time_offset_hours": 8,
                    "sectors": 3,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["appendix"] == "3"
            assert data["base_max_fdp_hours"] == 12.0  # 0600 band, 1-3 sectors
            assert data["final_max_fdp_hours"] == 12.0
            assert data["max_extension_hours"] == 1.0
            assert data["absolute_max_with_extension_hours"] == 13.0
            assert data["flight_time_limit_hours"] == 10.5
            assert len(data["calculation_notes"]) > 0

    @pytest.mark.anyio
    async def test_with_split_duty(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"{API_PREFIX}/calculate/max-fdp",
                json={
                    "appendix": "3",
                    "fdp_start_utc": "2026-03-28T22:00:00Z",
                    "local_time_offset_hours": 8,
                    "sectors": 3,
                    "split_duty": {
                        "rest_start_utc": "2026-03-29T04:00:00Z",
                        "rest_end_utc": "2026-03-29T08:00:00Z",
                        "accommodation": "sleeping",
                        "duration_hours": 4,
                    },
                },
            )
            data = resp.json()
            assert data["final_max_fdp_hours"] == 16.0
            assert data["post_split_max_hours"] == 6.0
            assert len(data["adjustments"]) > 0
            assert data["adjustments"][0]["adjustment_hours"] == 4.0

    @pytest.mark.anyio
    async def test_spec_example(self):
        """Test the exact example from the specification."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"{API_PREFIX}/calculate/max-fdp",
                json={
                    "appendix": "3",
                    "fdp_start_utc": "2026-03-28T22:00:00Z",
                    "local_time_offset_hours": 8,
                    "sectors": 3,
                    "split_duty": {
                        "rest_start_utc": "2026-03-29T04:00:00Z",
                        "rest_end_utc": "2026-03-29T08:00:00Z",
                        "accommodation": "sleeping",
                        "duration_hours": 4,
                    },
                    "consecutive_early_starts": 2,
                    "consecutive_wocl_infringements": 1,
                },
            )
            data = resp.json()
            assert data["appendix"] == "3"
            assert data["base_max_fdp_hours"] == 12.0
            assert data["final_max_fdp_hours"] == 16.0
            assert data["flight_time_limit_hours"] == 10.5

    @pytest.mark.anyio
    async def test_invalid_appendix_returns_422(self):
        """Invalid appendix should return 422 (Pydantic validation)."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"{API_PREFIX}/calculate/max-fdp",
                json={
                    "appendix": "99",
                    "fdp_start_utc": "2026-03-28T22:00:00Z",
                    "local_time_offset_hours": 8,
                    "sectors": 3,
                },
            )
            assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_missing_required_field_returns_422(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"{API_PREFIX}/calculate/max-fdp",
                json={
                    "appendix": "3",
                    # missing fdp_start_utc
                    "local_time_offset_hours": 8,
                    "sectors": 3,
                },
            )
            assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_all_appendices(self):
        """All valid appendices should return 200."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for appendix in ["1", "2", "3", "4", "4A", "4B", "5", "5A", "6"]:
                body = {
                    "appendix": appendix,
                    "fdp_start_utc": "2026-03-28T02:00:00Z",
                    "local_time_offset_hours": 8,
                    "sectors": 2,
                }
                if appendix == "2":
                    body["acclimatisation"] = {
                        "state": "acclimatised",
                        "acclimatised_time_offset_hours": 8,
                    }
                resp = await client.post(f"{API_PREFIX}/calculate/max-fdp", json=body)
                assert resp.status_code == 200, f"Failed for appendix {appendix}: {resp.text}"

    @pytest.mark.anyio
    async def test_augmented_crew(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"{API_PREFIX}/calculate/max-fdp",
                json={
                    "appendix": "2",
                    "fdp_start_utc": "2026-03-28T00:00:00Z",
                    "local_time_offset_hours": 8,
                    "sectors": 3,
                    "acclimatisation": {
                        "state": "acclimatised",
                        "acclimatised_time_offset_hours": 8,
                    },
                    "augmented_crew": {
                        "additional_fcms": 1,
                        "rest_facility_class": "class_1",
                    },
                },
            )
            data = resp.json()
            assert data["base_max_fdp_hours"] == 16.0
            assert data["flight_time_limit_hours"] is None


class TestMinOffDutyEndpoint:
    """Tests for POST /calculate/min-off-duty."""

    @pytest.mark.anyio
    async def test_basic_request(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"{API_PREFIX}/calculate/min-off-duty",
                json={
                    "appendix": "3",
                    "preceding_fdp": {
                        "start_utc": "2026-03-28T22:00:00Z",
                        "end_utc": "2026-03-29T08:30:00Z",
                        "duration_hours": 10.5,
                        "post_fdp_duty_hours": 0.5,
                        "location": "away",
                    },
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["appendix"] == "3"
            assert data["fdp_plus_post_duty_hours"] == 11.0
            assert data["base_min_odp_hours"] == 10.0  # away, <=12h

    @pytest.mark.anyio
    async def test_spec_example(self):
        """Test the exact example from the specification."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"{API_PREFIX}/calculate/min-off-duty",
                json={
                    "appendix": "3",
                    "preceding_fdp": {
                        "start_utc": "2026-03-28T22:00:00Z",
                        "end_utc": "2026-03-29T08:30:00Z",
                        "duration_hours": 10.5,
                        "post_fdp_duty_hours": 0.5,
                        "location": "away",
                        "split_duty": {
                            "duration_hours": 4,
                            "accommodation": "sleeping",
                            "overlaps_2300_0529": False,
                        },
                    },
                    "preceding_off_duty": {
                        "duration_hours": 13,
                        "included_local_night": True,
                    },
                    "following_off_duty_location": "away",
                    "following_off_duty_includes_local_night": True,
                },
            )
            data = resp.json()
            assert data["appendix"] == "3"
            assert data["fdp_plus_post_duty_hours"] == 11.0
            assert data["split_duty_credit_hours"] == 2.0
            assert data["reduction_applicable"] is not None
            assert data["reduction_applicable"]["eligible"] is True
            assert data["reduction_applicable"]["reduced_min_odp_hours"] == 9.0

    @pytest.mark.anyio
    async def test_invalid_appendix_returns_422(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"{API_PREFIX}/calculate/min-off-duty",
                json={
                    "appendix": "99",
                    "preceding_fdp": {
                        "start_utc": "2026-03-28T22:00:00Z",
                        "end_utc": "2026-03-29T08:00:00Z",
                        "duration_hours": 10.0,
                        "location": "away",
                    },
                },
            )
            assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_all_appendices(self):
        """All valid appendices should return 200."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for appendix in ["1", "2", "3", "4", "4A", "4B", "5", "5A", "6"]:
                resp = await client.post(
                    f"{API_PREFIX}/calculate/min-off-duty",
                    json={
                        "appendix": appendix,
                        "preceding_fdp": {
                            "start_utc": "2026-03-28T22:00:00Z",
                            "end_utc": "2026-03-29T08:00:00Z",
                            "duration_hours": 10.0,
                            "location": "away",
                        },
                    },
                )
                assert resp.status_code == 200, f"Failed for appendix {appendix}: {resp.text}"

    @pytest.mark.anyio
    async def test_calculation_notes_present(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"{API_PREFIX}/calculate/min-off-duty",
                json={
                    "appendix": "3",
                    "preceding_fdp": {
                        "start_utc": "2026-03-28T22:00:00Z",
                        "end_utc": "2026-03-29T08:00:00Z",
                        "duration_hours": 10.0,
                        "location": "away",
                    },
                },
            )
            data = resp.json()
            assert len(data["calculation_notes"]) > 0


class TestHealthEndpointPhase2:
    """Verify health endpoint updated for Phase 2."""

    @pytest.mark.anyio
    async def test_phase2_endpoints_available(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"{API_PREFIX}/health")
            data = resp.json()
            available = data["endpoints"]["available"]
            assert "/limits/fdp-table/{appendix}" in available
            assert "/limits/cumulative/{appendix}" in available
            assert "/calculate/max-fdp" in available
            assert "/calculate/min-off-duty" in available

    @pytest.mark.anyio
    async def test_phase2_endpoints_not_in_planned(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"{API_PREFIX}/health")
            data = resp.json()
            planned = data["endpoints"]["planned"]
            assert "/limits/fdp-table/{appendix}" not in planned
            assert "/limits/cumulative/{appendix}" not in planned
            assert "/calculate/max-fdp" not in planned
            assert "/calculate/min-off-duty" not in planned

    @pytest.mark.anyio
    async def test_version_bumped(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"{API_PREFIX}/health")
            data = resp.json()
            assert data["version"] == "0.4.0"
