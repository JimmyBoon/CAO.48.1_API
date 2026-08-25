"""
Integration tests for the /validate/* endpoints (Phase 3).

POST /validate/fdp       — FDP validation
POST /validate/off-duty  — Off-duty period validation
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

API_PREFIX = "/api/v1/cao481"
APPENDICES = ["1", "2", "3", "4", "4A", "4B", "5", "5A", "6"]

# ─── Minimal valid bodies per appendix ────────────────────────────────
# FDP start = 0600 local (+8), 4h duration — safely within all limits.
# 0700 local at +8. Amended in Phase 5 (S10): this started 0600 local, which
# is before the 0700 boundary in Appendix 1 §2.1(a). That boundary is the
# earlier of morning civil twilight and 0700, and twilight needs a position
# this API is not given — so an earlier start leaves the check
# data_unavailable rather than passed. 0700 keeps every appendix exercising
# its FDP limit rather than Appendix 1's window rule.
_VALIDATE_FDP_BODIES = {
    appendix: {
        "appendix": appendix,
        "fdp_start_utc": "2026-03-28T23:00:00Z",
        "fdp_end_utc": "2026-03-29T03:00:00Z",   # 4h
        "local_time_offset_hours": 8,
        "sectors": 1,
    }
    for appendix in APPENDICES
}
# Appendix 2 requires acclimatisation input
_VALIDATE_FDP_BODIES["2"]["acclimatisation"] = {
    "state": "acclimatised",
    "acclimatised_time_offset_hours": 8.0,
}

# 6h preceding FDP, 14h actual ODP — well above any appendix minimum.
_VALIDATE_OD_BODIES = {
    appendix: {
        "appendix": appendix,
        "preceding_fdp": {
            "start_utc": "2026-03-28T22:00:00Z",
            "end_utc": "2026-03-29T04:00:00Z",
            "duration_hours": 6.0,
            "location": "away",
        },
        "actual_off_duty_hours": 14.0,
    }
    for appendix in APPENDICES
}


class TestValidateFdpEndpoint:
    """Tests for POST /validate/fdp."""

    @pytest.mark.anyio
    async def test_valid_fdp_returns_200_with_valid_true(self):
        """FDP exactly at limit — valid=True, no violations."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"{API_PREFIX}/validate/fdp",
                json={
                    "appendix": "3",
                    "fdp_start_utc": "2026-03-28T22:00:00Z",
                    "fdp_end_utc": "2026-03-29T10:00:00Z",   # 12h = limit
                    "local_time_offset_hours": 8,
                    "sectors": 3,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["valid"] is True
            assert data["violations"] == []
            assert data["appendix"] == "3"
            assert len(data["checks"]) > 0
            assert len(data["calculation_notes"]) > 0

    @pytest.mark.anyio
    async def test_fdp_exceeds_limit_returns_violation(self):
        """13h FDP against 12h limit — valid=False, violation with hard_limit."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"{API_PREFIX}/validate/fdp",
                json={
                    "appendix": "3",
                    "fdp_start_utc": "2026-03-28T22:00:00Z",
                    "fdp_end_utc": "2026-03-29T11:00:00Z",   # 13h
                    "local_time_offset_hours": 8,
                    "sectors": 3,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["valid"] is False
            assert len(data["violations"]) == 1
            v = data["violations"][0]
            assert v["check"] == "fdp_within_limit"
            assert v["severity"] == "hard_limit"
            assert v["actual"] == 13.0
            assert v["limit"] == 12.0

    @pytest.mark.anyio
    async def test_valid_extension_makes_fdp_valid(self):
        """13h FDP with 1h unforeseen extension — valid=True."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"{API_PREFIX}/validate/fdp",
                json={
                    "appendix": "3",
                    "fdp_start_utc": "2026-03-28T22:00:00Z",
                    "fdp_end_utc": "2026-03-29T11:00:00Z",   # 13h = 12h + 1h ext
                    "local_time_offset_hours": 8,
                    "sectors": 3,
                    "extension": {"type": "unforeseen", "hours_used": 1.0},
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["valid"] is True
            check_ids = {c["check"] for c in data["checks"]}
            assert "fdp_within_limit" in check_ids
            assert "extension_permitted" in check_ids

    @pytest.mark.anyio
    async def test_invalid_extension_type_violation(self):
        """'urgent' extension type invalid for Appendix 3 — extension_permitted fails."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"{API_PREFIX}/validate/fdp",
                json={
                    "appendix": "3",
                    "fdp_start_utc": "2026-03-28T22:00:00Z",
                    "fdp_end_utc": "2026-03-29T11:00:00Z",
                    "local_time_offset_hours": 8,
                    "sectors": 3,
                    "extension": {"type": "urgent", "hours_used": 1.0},
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["valid"] is False
            assert any(v["check"] == "extension_permitted" for v in data["violations"])

    @pytest.mark.anyio
    async def test_flight_time_violation(self):
        """Flight time exceeding per-FDP limit — valid=False."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"{API_PREFIX}/validate/fdp",
                json={
                    "appendix": "3",
                    "fdp_start_utc": "2026-03-28T22:00:00Z",
                    "fdp_end_utc": "2026-03-29T10:00:00Z",
                    "local_time_offset_hours": 8,
                    "sectors": 3,
                    "actual_flight_time_hours": 11.0,  # limit is 10.5h
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["valid"] is False
            ft_v = next(
                (v for v in data["violations"] if v["check"] == "flight_time_within_limit"),
                None,
            )
            assert ft_v is not None
            assert ft_v["actual"] == 11.0

    @pytest.mark.anyio
    async def test_all_appendices_within_limit(self):
        """All 9 appendices return 200 with valid=True for a 4h FDP."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for appendix in APPENDICES:
                resp = await client.post(
                    f"{API_PREFIX}/validate/fdp",
                    json=_VALIDATE_FDP_BODIES[appendix],
                )
                assert resp.status_code == 200, (
                    f"Appendix {appendix}: {resp.text}"
                )
                data = resp.json()
                assert data["valid"] is True, (
                    f"Appendix {appendix} expected valid=True, "
                    f"got violations={data['violations']}"
                )

    @pytest.mark.anyio
    async def test_missing_fdp_end_utc_returns_422(self):
        """fdp_end_utc is required — omitting it should give 422."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"{API_PREFIX}/validate/fdp",
                json={
                    "appendix": "3",
                    "fdp_start_utc": "2026-03-28T22:00:00Z",
                    # fdp_end_utc missing
                    "local_time_offset_hours": 8,
                    "sectors": 3,
                },
            )
            assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_invalid_appendix_returns_422(self):
        """Invalid appendix literal — Pydantic rejects it with 422."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"{API_PREFIX}/validate/fdp",
                json={
                    "appendix": "99",
                    "fdp_start_utc": "2026-03-28T22:00:00Z",
                    "fdp_end_utc": "2026-03-29T10:00:00Z",
                    "local_time_offset_hours": 8,
                    "sectors": 3,
                },
            )
            assert resp.status_code == 422


class TestValidateOffDutyEndpoint:
    """Tests for POST /validate/off-duty."""

    @pytest.mark.anyio
    async def test_valid_odp_returns_200_with_valid_true(self):
        """ODP meeting the minimum — valid=True, no violations."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"{API_PREFIX}/validate/off-duty",
                json={
                    "appendix": "3",
                    "preceding_fdp": {
                        "start_utc": "2026-03-28T22:00:00Z",
                        "end_utc": "2026-03-29T08:00:00Z",
                        "duration_hours": 10.0,
                        "location": "away",
                    },
                    "actual_off_duty_hours": 10.0,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["valid"] is True
            assert data["violations"] == []
            assert data["appendix"] == "3"
            assert len(data["checks"]) > 0

    @pytest.mark.anyio
    async def test_odp_below_minimum_returns_violation(self):
        """8h actual against 10h minimum (away) — valid=False."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"{API_PREFIX}/validate/off-duty",
                json={
                    "appendix": "3",
                    "preceding_fdp": {
                        "start_utc": "2026-03-28T22:00:00Z",
                        "end_utc": "2026-03-29T08:00:00Z",
                        "duration_hours": 10.0,
                        "location": "away",
                    },
                    "actual_off_duty_hours": 8.0,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["valid"] is False
            assert any(v["check"] == "odp_meets_minimum" for v in data["violations"])

    @pytest.mark.anyio
    async def test_reduction_claimed_eligible(self):
        """Reduction conditions met — reduction_conditions_met check passes."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"{API_PREFIX}/validate/off-duty",
                json={
                    "appendix": "3",
                    "preceding_fdp": {
                        "start_utc": "2026-03-28T22:00:00Z",
                        "end_utc": "2026-03-29T04:00:00Z",
                        "duration_hours": 6.0,
                        "location": "away",
                    },
                    "actual_off_duty_hours": 9.0,
                    "reduction_claimed": True,
                    "preceding_off_duty": {
                        "duration_hours": 13.0,
                        "included_local_night": True,
                    },
                    "following_off_duty_includes_local_night": True,
                    "following_off_duty_location": "away",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            red_check = next(
                (c for c in data["checks"] if c["check"] == "reduction_conditions_met"),
                None,
            )
            assert red_check is not None
            assert red_check["passed"] is True

    @pytest.mark.anyio
    async def test_all_appendices_valid_odp(self):
        """All 9 appendices return 200 with valid=True for a 14h ODP."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for appendix in APPENDICES:
                resp = await client.post(
                    f"{API_PREFIX}/validate/off-duty",
                    json=_VALIDATE_OD_BODIES[appendix],
                )
                assert resp.status_code == 200, (
                    f"Appendix {appendix}: {resp.text}"
                )
                data = resp.json()
                assert data["valid"] is True, (
                    f"Appendix {appendix} expected valid=True, "
                    f"got violations={data['violations']}"
                )

    @pytest.mark.anyio
    async def test_missing_actual_off_duty_hours_returns_422(self):
        """actual_off_duty_hours is required — omitting it gives 422."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"{API_PREFIX}/validate/off-duty",
                json={
                    "appendix": "3",
                    "preceding_fdp": {
                        "start_utc": "2026-03-28T22:00:00Z",
                        "end_utc": "2026-03-29T08:00:00Z",
                        "duration_hours": 10.0,
                        "location": "away",
                    },
                    # actual_off_duty_hours missing
                },
            )
            assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_invalid_appendix_returns_422(self):
        """Invalid appendix literal — Pydantic rejects it with 422."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"{API_PREFIX}/validate/off-duty",
                json={
                    "appendix": "99",
                    "preceding_fdp": {
                        "start_utc": "2026-03-28T22:00:00Z",
                        "end_utc": "2026-03-29T08:00:00Z",
                        "duration_hours": 10.0,
                        "location": "away",
                    },
                    "actual_off_duty_hours": 12.0,
                },
            )
            assert resp.status_code == 422


class TestHealthEndpointPhase3:
    """Verify that /health reflects Phase 3 endpoint status."""

    @pytest.mark.anyio
    async def test_validate_endpoints_in_available(self):
        """Both validate endpoints should appear in the available list."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"{API_PREFIX}/health")
            assert resp.status_code == 200
            data = resp.json()
            available = data["endpoints"]["available"]
            assert "/validate/fdp" in available
            assert "/validate/off-duty" in available

    @pytest.mark.anyio
    async def test_validate_endpoints_not_in_planned(self):
        """Both validate endpoints should not be in the planned list once live."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"{API_PREFIX}/health")
            data = resp.json()
            planned = data["endpoints"]["planned"]
            assert "/validate/fdp" not in planned
            assert "/validate/off-duty" not in planned
