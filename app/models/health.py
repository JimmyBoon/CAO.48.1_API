"""
health.py — Pydantic response models for the /health endpoint.

These models define the shape of the health check response, including
API status, version, supported appendices, and available endpoints.
All fields include descriptions for clean OpenAPI spec generation.
"""

from pydantic import BaseModel, Field


class LegislationInfo(BaseModel):
    """Reference information for the underlying legislation."""

    title: str = Field(
        description="Full title of the Civil Aviation Order.",
        json_schema_extra={"examples": ["Civil Aviation Order 48.1 Instrument 2019"]},
    )
    compilation: str = Field(
        description="Federal Register of Legislation compilation identifier.",
        json_schema_extra={"examples": ["F2021C01239"]},
    )
    compilation_number: int = Field(
        description="Compilation number of the in-force version.",
        json_schema_extra={"examples": [3]},
    )


class AppendixStatus(BaseModel):
    """Status of a single CAO 48.1 appendix within the API."""

    id: str = Field(
        description="Appendix identifier as used in CAO 48.1.",
        json_schema_extra={"examples": ["3"]},
    )
    title: str = Field(
        description="Descriptive title of the appendix.",
        json_schema_extra={
            "examples": ["Multi-Pilot Operations Except Complex"]
        },
    )
    status: str = Field(
        description=(
            "Implementation status: 'available' if the appendix's validation "
            "logic is live, 'planned' if not yet implemented."
        ),
        json_schema_extra={"examples": ["planned"]},
    )


class EndpointsInfo(BaseModel):
    """Lists which API endpoints are currently available vs planned."""

    available: list[str] = Field(
        description="Endpoint paths that are live and accepting requests.",
        json_schema_extra={"examples": [["/health"]]},
    )
    planned: list[str] = Field(
        description="Endpoint paths that are defined in the spec but not yet implemented.",
        json_schema_extra={
            "examples": [
                [
                    "/sections",
                    "/sections/{section_id}",
                    "/validate/fdp",
                ]
            ]
        },
    )


class HealthResponse(BaseModel):
    """
    Health check response showing API status, version, supported appendices,
    and endpoint availability.

    This is the primary discovery endpoint for consumers to understand what
    the API supports and which features are currently live.
    """

    status: str = Field(
        description="API health status. 'healthy' indicates normal operation.",
        json_schema_extra={"examples": ["healthy"]},
    )
    version: str = Field(
        description="Semantic version of the API.",
        json_schema_extra={"examples": ["0.1.0"]},
    )
    api: str = Field(
        description="Display name of the API.",
        json_schema_extra={"examples": ["CAO 48.1 Compliance API"]},
    )
    description: str = Field(
        description="Brief description of the API's purpose.",
    )
    legislation: LegislationInfo = Field(
        description="Reference information for the underlying legislation.",
    )
    supported_appendices: list[AppendixStatus] = Field(
        description=(
            "List of CAO 48.1 appendices covered by this API, "
            "with their current implementation status."
        ),
    )
    endpoints: EndpointsInfo = Field(
        description="Available and planned API endpoints.",
    )
