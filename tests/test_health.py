"""
test_health.py — Tests for the /health endpoint and RapidAPI middleware.

Covers:
- Health endpoint response structure and content
- RapidAPI proxy secret validation in production mode
- Development mode bypass of proxy validation
- OpenAPI spec availability
"""

import pytest
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport

from app.main import app


# ─── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def api_prefix() -> str:
    """Return the API path prefix used by all endpoints."""
    return "/api/v1/cao481"


# ─── Health Endpoint Tests ─────────────────────────────────────────────

class TestHealthEndpoint:
    """Tests for GET /api/v1/cao481/health."""

    @pytest.mark.anyio
    async def test_health_returns_200(self, api_prefix: str):
        """Health endpoint should return 200 OK in development mode."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"{api_prefix}/health")

        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_health_response_structure(self, api_prefix: str):
        """Health response should contain all required top-level fields."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"{api_prefix}/health")

        data = response.json()

        # Top-level fields
        assert data["status"] == "healthy"
        assert "version" in data
        assert "api" in data
        assert "description" in data
        assert "legislation" in data
        assert "supported_appendices" in data
        assert "endpoints" in data

    @pytest.mark.anyio
    async def test_health_legislation_info(self, api_prefix: str):
        """Health response should include correct legislation reference."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"{api_prefix}/health")

        leg = response.json()["legislation"]
        assert leg["title"] == "Civil Aviation Order 48.1 Instrument 2019"
        assert leg["compilation"] == "F2021C01239"
        assert leg["compilation_number"] == 3

    @pytest.mark.anyio
    async def test_health_lists_all_nine_appendices(self, api_prefix: str):
        """Health response should list all 9 supported appendices (1–6)."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"{api_prefix}/health")

        appendices = response.json()["supported_appendices"]
        ids = [a["id"] for a in appendices]

        assert len(appendices) == 9
        assert ids == ["1", "2", "3", "4", "4A", "4B", "5", "5A", "6"]

    @pytest.mark.anyio
    async def test_health_appendix_fields(self, api_prefix: str):
        """Each appendix entry should have id, title, and status fields."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"{api_prefix}/health")

        for appendix in response.json()["supported_appendices"]:
            assert "id" in appendix
            assert "title" in appendix
            assert "status" in appendix
            assert appendix["status"] in ("available", "planned")

    @pytest.mark.anyio
    async def test_health_endpoints_includes_health(self, api_prefix: str):
        """The /health endpoint itself should be listed as available."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"{api_prefix}/health")

        endpoints = response.json()["endpoints"]
        assert "/health" in endpoints["available"]

    @pytest.mark.anyio
    async def test_health_planned_endpoints_not_empty(self, api_prefix: str):
        """There should be planned endpoints listed for future phases."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"{api_prefix}/health")

        planned = response.json()["endpoints"]["planned"]
        assert len(planned) > 0
        assert "/validate/roster" in planned


# ─── RapidAPI Middleware Tests ─────────────────────────────────────────

class TestRapidAPIMiddleware:
    """Tests for the RapidAPI proxy secret validation middleware."""

    @pytest.mark.anyio
    async def test_development_mode_allows_without_secret(self, api_prefix: str):
        """
        In development mode, requests without X-RapidAPI-Proxy-Secret
        should be allowed through.
        """
        with patch("app.middleware.settings") as mock_settings:
            mock_settings.environment = "development"
            mock_settings.rapidapi_proxy_secret = "test-secret"

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(f"{api_prefix}/health")

            assert response.status_code == 200

    @pytest.mark.anyio
    async def test_production_rejects_missing_secret(self, api_prefix: str):
        """
        In production mode, requests without X-RapidAPI-Proxy-Secret
        should receive 403 Forbidden.
        """
        with patch("app.middleware.settings") as mock_settings:
            mock_settings.environment = "production"
            mock_settings.rapidapi_proxy_secret = "test-secret-123"

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(f"{api_prefix}/health")

            assert response.status_code == 403
            assert response.json()["error"] == "forbidden"

    @pytest.mark.anyio
    async def test_production_rejects_wrong_secret(self, api_prefix: str):
        """
        In production mode, requests with an incorrect proxy secret
        should receive 403 Forbidden.
        """
        with patch("app.middleware.settings") as mock_settings:
            mock_settings.environment = "production"
            mock_settings.rapidapi_proxy_secret = "correct-secret"

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    f"{api_prefix}/health",
                    headers={"X-RapidAPI-Proxy-Secret": "wrong-secret"},
                )

            assert response.status_code == 403

    @pytest.mark.anyio
    async def test_production_accepts_valid_secret(self, api_prefix: str):
        """
        In production mode, requests with the correct proxy secret
        should pass through to the handler.
        """
        with patch("app.middleware.settings") as mock_settings:
            mock_settings.environment = "production"
            mock_settings.rapidapi_proxy_secret = "correct-secret"

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    f"{api_prefix}/health",
                    headers={"X-RapidAPI-Proxy-Secret": "correct-secret"},
                )

            assert response.status_code == 200
            assert response.json()["status"] == "healthy"


# ─── OpenAPI Spec Tests ────────────────────────────────────────────────

class TestOpenAPISpec:
    """Tests for the auto-generated OpenAPI specification."""

    @pytest.mark.anyio
    async def test_openapi_spec_available(self):
        """The OpenAPI spec should be served at /openapi.json."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/openapi.json")

        assert response.status_code == 200
        spec = response.json()
        assert "openapi" in spec
        assert "info" in spec
        assert "paths" in spec

    @pytest.mark.anyio
    async def test_openapi_spec_metadata(self):
        """The OpenAPI spec should contain correct API metadata for RapidAPI import."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/openapi.json")

        info = response.json()["info"]
        assert info["title"] == "CAO 48.1 Compliance API"
        assert "version" in info
        assert "description" in info
        assert "contact" in info

    @pytest.mark.anyio
    async def test_openapi_spec_has_health_endpoint(self):
        """The OpenAPI spec should include the /health endpoint."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/openapi.json")

        paths = response.json()["paths"]
        assert "/api/v1/cao481/health" in paths

    @pytest.mark.anyio
    async def test_openapi_spec_has_tags(self):
        """The OpenAPI spec should include tags for RapidAPI endpoint grouping."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/openapi.json")

        tags = response.json().get("tags", [])
        tag_names = [t["name"] for t in tags]
        assert "Health" in tag_names

    @pytest.mark.anyio
    async def test_docs_endpoint_available(self):
        """The interactive docs should be served at /docs."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/docs")

        assert response.status_code == 200
