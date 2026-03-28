"""
test_sections.py — Tests for the regulatory content endpoints and parser.

Covers:
- Parser correctly loads and indexes the legislation
- GET /sections returns a valid table of contents
- GET /sections/{id} returns correct sections for various lookup patterns
- 404 handling for unknown sections
"""

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.parser import get_legislation, get_section, get_table_of_contents


# ─── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def api_prefix() -> str:
    """Return the API path prefix."""
    return "/api/v1/cao481"


@pytest.fixture
def legislation():
    """Return the parsed legislation singleton."""
    return get_legislation()


# ─── Parser Unit Tests ─────────────────────────────────────────────────

class TestParser:
    """Tests for the CAO 48.1 markdown parser."""

    def test_legislation_has_title(self, legislation):
        """The parsed legislation should have the correct document title."""
        assert "Civil Aviation Order 48.1" in legislation.title

    def test_legislation_has_groups(self, legislation):
        """The legislation should contain Parts and Appendices."""
        assert len(legislation.groups) > 0

        group_ids = [g.id for g in legislation.groups]
        assert "PART 1" in group_ids
        assert "PART 2" in group_ids
        assert "PART 3" in group_ids
        assert "APPENDIX 1" in group_ids
        assert "APPENDIX 2" in group_ids
        assert "APPENDIX 3" in group_ids
        assert "APPENDIX 7" in group_ids

    def test_legislation_has_compound_appendix_ids(self, legislation):
        """Appendices with compound IDs (4A, 4B, 5A) should be parsed correctly."""
        group_ids = [g.id for g in legislation.groups]
        assert "APPENDIX 4A" in group_ids
        assert "APPENDIX 4B" in group_ids
        assert "APPENDIX 5A" in group_ids

    def test_appendix_3_has_sections(self, legislation):
        """Appendix 3 should contain its constituent sections."""
        group = legislation.group_index["APPENDIX 3"]
        assert len(group.sections) > 0

        sec_numbers = [s.section_number for s in group.sections]
        assert "1" in sec_numbers  # Sleep opportunity
        assert "2" in sec_numbers  # FDP and flight time limits
        assert "8" in sec_numbers  # Off-duty periods

    def test_section_lookup_by_appendix_section(self, legislation):
        """Looking up 'APPENDIX 3.2' should return the FDP limits section."""
        result = get_section(legislation, "APPENDIX 3.2")
        assert result is not None
        assert result["section_id"] == "APPENDIX 3.2"
        assert "FDP" in result["title"]
        assert result["parent_id"] == "APPENDIX 3"
        assert len(result["text"]) > 0

    def test_section_lookup_by_part_section(self, legislation):
        """Looking up '6' should return the Definitions section."""
        result = get_section(legislation, "6")
        assert result is not None
        assert result["section_id"] == "6"
        assert "Definitions" in result["title"]
        assert len(result["text"]) > 0

    def test_group_lookup(self, legislation):
        """Looking up 'APPENDIX 1' should return the group with its sections."""
        result = get_section(legislation, "APPENDIX 1")
        assert result is not None
        assert result["section_id"] == "APPENDIX 1"
        assert "sections" in result
        assert len(result["sections"]) > 0

    def test_lookup_case_insensitive(self, legislation):
        """Lookups should be case-insensitive."""
        result_upper = get_section(legislation, "APPENDIX 3.2")
        result_lower = get_section(legislation, "appendix 3.2")
        assert result_upper is not None
        assert result_lower is not None
        assert result_upper["section_id"] == result_lower["section_id"]

    def test_lookup_unknown_returns_none(self, legislation):
        """Looking up a non-existent section should return None."""
        result = get_section(legislation, "APPENDIX 99")
        assert result is None

    def test_table_of_contents(self, legislation):
        """The table of contents should list all groups with sections."""
        toc = get_table_of_contents(legislation)
        assert "Civil Aviation Order 48.1" in toc["title"]
        assert len(toc["groups"]) > 0

        # Check that each group has an id, title, type, and sections
        for group in toc["groups"]:
            assert "id" in group
            assert "title" in group
            assert "type" in group
            assert group["type"] in ("part", "appendix")
            assert "sections" in group

    def test_section_text_contains_clauses(self, legislation):
        """Section body text should contain the actual regulatory clauses."""
        result = get_section(legislation, "APPENDIX 1.1")
        assert result is not None
        # Appendix 1 section 1 is about sleep opportunity
        assert "sleep opportunity" in result["text"].lower()

    def test_definitions_section_is_substantial(self, legislation):
        """Section 6 (Definitions) should be a large section."""
        result = get_section(legislation, "6")
        assert result is not None
        # Definitions is one of the longest sections
        assert len(result["text"]) > 1000


# ─── API Endpoint Tests ───────────────────────────────────────────────

class TestSectionsEndpoint:
    """Tests for GET /sections."""

    @pytest.mark.anyio
    async def test_sections_returns_200(self, api_prefix: str):
        """The /sections endpoint should return 200 OK."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"{api_prefix}/sections")

        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_sections_response_structure(self, api_prefix: str):
        """The response should contain title, compilation, groups, and disclaimer."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"{api_prefix}/sections")

        data = response.json()
        assert "title" in data
        assert "compilation" in data
        assert "groups" in data
        assert "disclaimer" in data

    @pytest.mark.anyio
    async def test_sections_contains_all_appendices(self, api_prefix: str):
        """The table of contents should list all 9 appendices (1–7 incl. 4A, 4B, 5A)."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"{api_prefix}/sections")

        groups = response.json()["groups"]
        appendix_ids = [
            g["id"] for g in groups if g["type"] == "appendix"
        ]
        for app_id in ["APPENDIX 1", "APPENDIX 2", "APPENDIX 3", "APPENDIX 4",
                        "APPENDIX 4A", "APPENDIX 4B", "APPENDIX 5",
                        "APPENDIX 5A", "APPENDIX 6", "APPENDIX 7"]:
            assert app_id in appendix_ids, f"Missing {app_id}"


class TestSectionDetailEndpoint:
    """Tests for GET /sections/{section_id}."""

    @pytest.mark.anyio
    async def test_group_lookup(self, api_prefix: str):
        """Looking up an appendix should return group detail with sections list."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"{api_prefix}/sections/APPENDIX 3")

        assert response.status_code == 200
        data = response.json()
        assert data["section_id"] == "APPENDIX 3"
        assert "sections" in data
        assert len(data["sections"]) > 0
        assert "disclaimer" in data

    @pytest.mark.anyio
    async def test_section_lookup(self, api_prefix: str):
        """Looking up a specific section should return the section text."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"{api_prefix}/sections/APPENDIX 3.2")

        assert response.status_code == 200
        data = response.json()
        assert data["section_id"] == "APPENDIX 3.2"
        assert "text" in data
        assert len(data["text"]) > 0
        assert data["parent_id"] == "APPENDIX 3"
        assert "disclaimer" in data

    @pytest.mark.anyio
    async def test_part_section_lookup(self, api_prefix: str):
        """Looking up a part-level section number should return the section."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"{api_prefix}/sections/6")

        assert response.status_code == 200
        data = response.json()
        assert data["section_id"] == "6"
        assert "Definitions" in data["title"]
        assert "text" in data

    @pytest.mark.anyio
    async def test_not_found(self, api_prefix: str):
        """Looking up a non-existent section should return 404."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"{api_prefix}/sections/APPENDIX 99")

        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "not_found"
        assert "hint" in data

    @pytest.mark.anyio
    async def test_case_insensitive_lookup(self, api_prefix: str):
        """Section lookups should be case-insensitive."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"{api_prefix}/sections/appendix 3.2")

        assert response.status_code == 200
        data = response.json()
        assert data["section_id"] == "APPENDIX 3.2"

    @pytest.mark.anyio
    async def test_compound_appendix_lookup(self, api_prefix: str):
        """Looking up compound appendix IDs (4A, 4B, 5A) should work."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"{api_prefix}/sections/APPENDIX 4B")

        assert response.status_code == 200
        data = response.json()
        assert data["section_id"] == "APPENDIX 4B"
        assert "sections" in data


class TestHealthEndpointUpdated:
    """Verify the health endpoint reflects Phase 1 changes."""

    @pytest.mark.anyio
    async def test_health_shows_section_endpoints_available(self, api_prefix: str):
        """The health endpoint should now list /sections as available."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"{api_prefix}/health")

        endpoints = response.json()["endpoints"]
        assert "/sections" in endpoints["available"]
        assert "/sections/{section_id}" in endpoints["available"]

    @pytest.mark.anyio
    async def test_health_sections_not_in_planned(self, api_prefix: str):
        """Section endpoints should no longer appear in the planned list."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"{api_prefix}/health")

        planned = response.json()["endpoints"]["planned"]
        assert "/sections" not in planned
        assert "/sections/{section_id}" not in planned
