"""
Tests for GET /guide endpoint (Phase 6).
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

PREFIX = "/api/v1/cao481"
pytestmark = pytest.mark.anyio


@pytest.fixture
def transport():
    return ASGITransport(app=app)


class TestGuideEndpoint:
    async def test_returns_200(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"{PREFIX}/guide")
        assert resp.status_code == 200

    async def test_top_level_keys_present(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"{PREFIX}/guide")
        data = resp.json()
        for key in ("title", "version", "api_base_path", "description",
                    "important_notes", "appendices", "quick_reference", "endpoints"):
            assert key in data, f"Missing top-level key: {key}"

    async def test_version_matches_health(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            guide_resp = await client.get(f"{PREFIX}/guide")
            health_resp = await client.get(f"{PREFIX}/health")
        assert guide_resp.json()["version"] == health_resp.json()["version"]

    async def test_endpoints_is_nonempty_list(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"{PREFIX}/guide")
        endpoints = resp.json()["endpoints"]
        assert isinstance(endpoints, list)
        assert len(endpoints) > 0

    async def test_each_endpoint_entry_has_required_fields(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"{PREFIX}/guide")
        for entry in resp.json()["endpoints"]:
            for field in ("path", "method", "group", "summary", "purpose",
                          "when_to_use", "when_not_to_use", "parameters", "common_mistakes"):
                assert field in entry, f"Endpoint {entry.get('path')} missing field: {field}"

    async def test_all_available_endpoints_documented(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            guide_resp = await client.get(f"{PREFIX}/guide")
            health_resp = await client.get(f"{PREFIX}/health")
        guide_paths = {e["path"] for e in guide_resp.json()["endpoints"]}
        available = health_resp.json()["endpoints"]["available"]
        # Strip path params to compare bare paths
        for ep in available:
            bare = ep.split("{")[0].rstrip("/") or ep
            assert any(
                g.split("{")[0].rstrip("/") == bare for g in guide_paths
            ), f"Endpoint {ep} is available but not documented in /guide"

    async def test_nine_appendices_listed(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"{PREFIX}/guide")
        appendices = resp.json()["appendices"]
        assert len(appendices) == 9
        ids = {a["id"] for a in appendices}
        assert ids == {"1", "2", "3", "4", "4A", "4B", "5", "5A", "6"}

    async def test_quick_reference_nonempty(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"{PREFIX}/guide")
        qr = resp.json()["quick_reference"]
        assert isinstance(qr, list)
        assert len(qr) > 0
        for item in qr:
            assert "task" in item
            assert "endpoint" in item

    async def test_important_notes_nonempty(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"{PREFIX}/guide")
        notes = resp.json()["important_notes"]
        assert isinstance(notes, list)
        assert len(notes) >= 4

    async def test_validate_roster_endpoint_documented(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"{PREFIX}/guide")
        paths = [e["path"] for e in resp.json()["endpoints"]]
        assert "/validate/roster" in paths

    async def test_validate_roster_has_example_request(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"{PREFIX}/guide")
        roster_entry = next(
            e for e in resp.json()["endpoints"] if e["path"] == "/validate/roster"
        )
        assert "example_request" in roster_entry
        assert "example_response_shape" in roster_entry
        assert len(roster_entry["common_mistakes"]) > 0

    async def test_api_base_path_is_correct(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"{PREFIX}/guide")
        assert resp.json()["api_base_path"] == "/api/v1/cao481"


class TestHealthAfterPhase6:
    async def test_guide_in_available_endpoints(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"{PREFIX}/health")
        assert "/guide" in resp.json()["endpoints"]["available"]

    async def test_version_is_040(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"{PREFIX}/health")
        assert resp.json()["version"] == "0.5.0"
