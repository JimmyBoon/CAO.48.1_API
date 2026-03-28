"""
Tests for the /limits/* endpoints (Phase 2).

GET /limits/fdp-table/{appendix}
GET /limits/cumulative/{appendix}
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

API_PREFIX = "/api/v1/cao481"


@pytest.fixture
def api_prefix():
    return API_PREFIX


# ═══════════════════════════════════════════════════════════════════════
# FDP Table Endpoint
# ═══════════════════════════════════════════════════════════════════════

class TestFdpTableEndpoint:
    """Tests for GET /limits/fdp-table/{appendix}."""

    @pytest.mark.anyio
    async def test_valid_appendix_returns_200(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for appendix in ["1", "2", "3", "4", "4A", "4B", "5", "5A", "6"]:
                resp = await client.get(f"{API_PREFIX}/limits/fdp-table/{appendix}")
                assert resp.status_code == 200, f"Failed for appendix {appendix}"

    @pytest.mark.anyio
    async def test_invalid_appendix_returns_404(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"{API_PREFIX}/limits/fdp-table/99")
            assert resp.status_code == 404
            data = resp.json()
            assert data["error"] == "not_found"
            assert "valid_appendices" in data

    @pytest.mark.anyio
    async def test_response_structure(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"{API_PREFIX}/limits/fdp-table/3")
            data = resp.json()
            assert data["appendix"] == "3"
            assert data["table_id"] == "Table 2.1"
            assert data["lookup_key"] == "local_time_and_sectors"
            assert data["flight_time_limit_hours"] == 10.5
            assert len(data["rows"]) == 7
            assert data["split_duty_cap_hours"] == 16.0
            assert data["post_split_max_hours"] == 6.0

    @pytest.mark.anyio
    async def test_appendix_3_row_values(self):
        """Spot-check Appendix 3, 0700-1259 band, 1-3 sectors = 13h."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"{API_PREFIX}/limits/fdp-table/3")
            data = resp.json()
            # Find the 0700-1259 row
            row = next(r for r in data["rows"] if r["time_band"] == "0700-1259")
            assert row["sectors"]["1-3"] == 13.0
            assert row["sectors"]["8+"] == 10.5

    @pytest.mark.anyio
    async def test_appendix_1_simple_table(self):
        """Appendix 1 has a simple table with 'all' sector key."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"{API_PREFIX}/limits/fdp-table/1")
            data = resp.json()
            assert data["appendix"] == "1"
            for row in data["rows"]:
                assert "all" in row["sectors"]

    @pytest.mark.anyio
    async def test_appendix_6_flight_time_limit(self):
        """Appendix 6 has a 7h flight time limit."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"{API_PREFIX}/limits/fdp-table/6")
            data = resp.json()
            assert data["flight_time_limit_hours"] == 7.0

    @pytest.mark.anyio
    async def test_appendix_4b_crew_type_columns(self):
        """Appendix 4B has single_pilot, multi_1_2, multi_3+ columns."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"{API_PREFIX}/limits/fdp-table/4B")
            data = resp.json()
            row = data["rows"][0]
            assert "single_pilot" in row["sectors"]
            assert "multi_1_2" in row["sectors"]
            assert "multi_3+" in row["sectors"]

    @pytest.mark.anyio
    async def test_appendix_case_insensitive(self):
        """Appendix ID should be case-insensitive."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"{API_PREFIX}/limits/fdp-table/4b")
            assert resp.status_code == 200
            assert resp.json()["appendix"] == "4B"

    @pytest.mark.anyio
    async def test_appendix_5a_no_split_duty(self):
        """Appendix 5A has no split duty provisions."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"{API_PREFIX}/limits/fdp-table/5A")
            data = resp.json()
            assert data["split_duty_cap_hours"] is None
            assert data["post_split_max_hours"] is None


# ═══════════════════════════════════════════════════════════════════════
# Cumulative Limits Endpoint
# ═══════════════════════════════════════════════════════════════════════

class TestCumulativeLimitsEndpoint:
    """Tests for GET /limits/cumulative/{appendix}."""

    @pytest.mark.anyio
    async def test_valid_appendix_returns_200(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for appendix in ["1", "2", "3", "4", "4A", "4B", "5", "5A", "6"]:
                resp = await client.get(f"{API_PREFIX}/limits/cumulative/{appendix}")
                assert resp.status_code == 200, f"Failed for appendix {appendix}"

    @pytest.mark.anyio
    async def test_invalid_appendix_returns_404(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"{API_PREFIX}/limits/cumulative/invalid")
            assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_appendix_3_structure(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"{API_PREFIX}/limits/cumulative/3")
            data = resp.json()
            assert data["appendix"] == "3"
            assert data["flight_time"]["period_28d_hours"] == 100
            assert data["flight_time"]["period_365d_hours"] == 1000
            assert data["duty_time"]["period_168h_hours"] == 60
            assert data["duty_time"]["period_336h_hours"] == 100
            assert data["recovery"]["period_168h_block"]["min_hours"] == 36
            assert data["recovery"]["period_168h_block"]["local_nights"] == 2
            assert data["recovery"]["period_28d_days_off"] == 6

    @pytest.mark.anyio
    async def test_appendix_5_unique_limits(self):
        """Appendix 5 has unique flight time limits (168h, 90d, reset)."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"{API_PREFIX}/limits/cumulative/5")
            data = resp.json()
            assert data["flight_time"]["period_168h_hours"] == 50
            assert data["flight_time"]["period_28d_hours"] == 170
            assert data["flight_time"]["period_90d_hours"] == 450
            assert data["flight_time"]["period_365d_hours"] == 1200
            assert data["flight_time"]["reset_after_days_off"] == 5

    @pytest.mark.anyio
    async def test_appendix_4a_balloon_limits(self):
        """Appendix 4A has lower flight time limits (50h/28d)."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"{API_PREFIX}/limits/cumulative/4A")
            data = resp.json()
            assert data["flight_time"]["period_28d_hours"] == 50
            assert data["duty_time"]["period_168h_hours"] == 45
            assert data["duty_time"]["period_336h_hours"] == 84
