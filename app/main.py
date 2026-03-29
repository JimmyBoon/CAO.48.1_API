"""
main.py — CAO 48.1 Compliance API entry point.

A stateless REST API for validating flight crew duty periods against
the Australian Civil Aviation Order 48.1 Instrument 2019.

Phase 0+1: Health endpoint, regulatory content endpoints, RapidAPI middleware.

Usage:
    # Local development
    uvicorn app.main:app --reload

    # Docker
    docker compose up
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.middleware import RapidAPIProxyMiddleware
from app.parser import get_legislation, get_section, get_table_of_contents
from app.models.health import (
    AppendixStatus,
    EndpointsInfo,
    HealthResponse,
    LegislationInfo,
)
from app.models.sections import (
    GroupDetailResponse,
    SectionDetailResponse,
    TableOfContentsResponse,
)
from app.routes.limits import router as limits_router
from app.routes.calculate import router as calculate_router

# ─── Logging ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Appendix definitions ──────────────────────────────────────────────
# Central registry of all appendices — status updated as features are built.
APPENDICES = [
    AppendixStatus(id="1", title="Basic Limits", status="available"),
    AppendixStatus(
        id="2", title="Multi-Pilot Operations", status="available"
    ),
    AppendixStatus(
        id="3",
        title="Multi-Pilot Operations Except Complex",
        status="available",
    ),
    AppendixStatus(id="4", title="Any Operations", status="available"),
    AppendixStatus(id="4A", title="Balloon Operations", status="available"),
    AppendixStatus(
        id="4B",
        title="Medical Transport & Emergency Service Operations",
        status="available",
    ),
    AppendixStatus(
        id="5",
        title="Aerial Work & Associated Flight Training",
        status="available",
    ),
    AppendixStatus(
        id="5A", title="Daylight Aerial Work", status="available"
    ),
    AppendixStatus(id="6", title="Flight Training", status="available"),
]

# ─── Endpoint registry ─────────────────────────────────────────────────
# Tracks which endpoints are live vs planned. Update as phases are built.
AVAILABLE_ENDPOINTS = [
    "/health",
    "/sections",
    "/sections/{section_id}",
    "/limits/fdp-table/{appendix}",
    "/limits/cumulative/{appendix}",
    "/calculate/max-fdp",
    "/calculate/min-off-duty",
]
PLANNED_ENDPOINTS = [
    "/validate/fdp",
    "/validate/off-duty",
    "/validate/cumulative",
    "/validate/sequence",
    "/validate/roster",
]

# ─── Lifespan ──────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler — runs startup and shutdown logic.

    Logs the configuration on startup and warns if the proxy secret
    is missing in production mode.
    """
    logger.info(
        "Starting %s v%s in %s mode",
        settings.app_name,
        settings.app_version,
        settings.environment,
    )
    if settings.environment == "production" and not settings.rapidapi_proxy_secret:
        logger.warning(
            "RAPIDAPI_PROXY_SECRET is not set — all requests will be rejected "
            "in production mode!"
        )
    # Parse the CAO 48.1 legislation at startup
    leg = get_legislation()
    logger.info(
        "CAO 48.1 loaded: %d groups, %d sections",
        len(leg.groups),
        len(leg.section_index),
    )
    yield
    logger.info("Shutting down %s", settings.app_name)


# ─── FastAPI application ───────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    description=(
        "A stateless REST API for validating flight crew duty periods "
        "against the Australian Civil Aviation Order 48.1 Instrument 2019 "
        "(Compilation No. 3, F2021C01239).\n\n"
        "Covers Appendices 1 through 6 with validation (pass/fail with "
        "clause references), calculation (max FDP, min off-duty), and "
        "direct access to the legislative text.\n\n"
        "**Disclaimer:** This API is derived from CAO 48.1 and is "
        "provided for reference purposes only. It does not replace your "
        "operator's approved Fatigue Management Manual (FMM), a qualified "
        "fatigue risk management assessment, or professional regulatory "
        "advice."
    ),
    contact={
        "name": "James Boon",
        "url": "https://jamesboon.dev",
    },
    license_info={
        "name": "Proprietary",
    },
    openapi_tags=[
        {
            "name": "Health",
            "description": (
                "API status and discovery. Use the health endpoint to "
                "verify the API is running and discover available features."
            ),
        },
        {
            "name": "Regulatory Content",
            "description": (
                "Access the text of CAO 48.1 sections and appendices. "
                "Useful for understanding the rules behind validation results."
            ),
        },
        {
            "name": "Calculation",
            "description": (
                "Calculate maximum FDP limits and minimum off-duty periods "
                "based on operational parameters. Does not validate — just "
                "returns the applicable limits."
            ),
        },
        {
            "name": "Validation",
            "description": (
                "Validate duty periods, off-duty periods, cumulative limits, "
                "duty sequences, and full rosters against CAO 48.1 rules. "
                "Returns all violations found with clause references."
            ),
        },
    ],
    # RapidAPI imports the spec from /openapi.json
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─── Middleware ─────────────────────────────────────────────────────────
# CORS — allow RapidAPI test console and local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://rapidapi.com",
        "https://*.rapidapi.com",
        "http://localhost",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# RapidAPI proxy secret validation
app.add_middleware(RapidAPIProxyMiddleware)

# ─── API prefix router ─────────────────────────────────────────────────
# All endpoints live under /api/v1/cao481
API_PREFIX = "/api/v1/cao481"

# ─── Mount Phase 2 routers ────────────────────────────────────────────
app.include_router(limits_router, prefix=API_PREFIX)
app.include_router(calculate_router, prefix=API_PREFIX)


# ─── Health endpoint ───────────────────────────────────────────────────
@app.get(
    f"{API_PREFIX}/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="API health check and feature discovery",
    description=(
        "Returns the API status, version, supported CAO 48.1 appendices, "
        "and which endpoints are currently available vs planned. Use this "
        "endpoint to verify the API is operational and to discover what "
        "features are live."
    ),
    responses={
        200: {
            "description": "API is healthy and operational.",
            "content": {
                "application/json": {
                    "example": {
                        "status": "healthy",
                        "version": "0.1.0",
                        "api": "CAO 48.1 Compliance API",
                        "description": (
                            "Stateless REST API for validating flight "
                            "crew duty periods against Australian "
                            "Civil Aviation Order 48.1 Instrument 2019"
                        ),
                        "legislation": {
                            "title": (
                                "Civil Aviation Order 48.1 "
                                "Instrument 2019"
                            ),
                            "compilation": "F2021C01239",
                            "compilation_number": 3,
                        },
                        "supported_appendices": [
                            {
                                "id": "3",
                                "title": (
                                    "Multi-Pilot Operations "
                                    "Except Complex"
                                ),
                                "status": "planned",
                            }
                        ],
                        "endpoints": {
                            "available": ["/health"],
                            "planned": ["/sections", "/validate/fdp"],
                        },
                    }
                }
            },
        },
        403: {
            "description": "Forbidden — invalid or missing RapidAPI proxy secret.",
            "content": {
                "application/json": {
                    "example": {
                        "error": "forbidden",
                        "message": "Invalid or missing RapidAPI proxy secret.",
                    }
                }
            },
        },
    },
)
async def health_check() -> HealthResponse:
    """
    Return API health status, version, and feature availability.

    This endpoint serves two purposes:
    1. **Health check** — returns 200 with status 'healthy' if the API
       is running correctly.
    2. **Feature discovery** — lists all supported CAO 48.1 appendices
       and their implementation status, plus which endpoints are live
       vs planned.
    """
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
        api=settings.app_name,
        description=(
            "Stateless REST API for validating flight crew duty periods "
            "against Australian Civil Aviation Order 48.1 Instrument 2019"
        ),
        legislation=LegislationInfo(
            title="Civil Aviation Order 48.1 Instrument 2019",
            compilation="F2021C01239",
            compilation_number=3,
        ),
        supported_appendices=APPENDICES,
        endpoints=EndpointsInfo(
            available=AVAILABLE_ENDPOINTS,
            planned=PLANNED_ENDPOINTS,
        ),
    )


# ─── Regulatory Content: Table of Contents ─────────────────────────────
@app.get(
    f"{API_PREFIX}/sections",
    response_model=TableOfContentsResponse,
    tags=["Regulatory Content"],
    summary="Table of contents for CAO 48.1",
    description=(
        "Returns the full table of contents for CAO 48.1 Instrument 2019, "
        "listing all Parts and Appendices with their constituent sections. "
        "Each section includes an ID that can be used with the "
        "`GET /sections/{section_id}` endpoint to retrieve the full text."
    ),
)
async def list_sections() -> TableOfContentsResponse:
    """
    Return the full table of contents for CAO 48.1.

    Lists all Parts (1–3) and Appendices (1–7) with their
    constituent sections. Each section entry includes an ID
    for use with the section detail endpoint.
    """
    legislation = get_legislation()
    toc = get_table_of_contents(legislation)
    return TableOfContentsResponse(**toc)


# ─── Regulatory Content: Section Detail ────────────────────────────────
@app.get(
    f"{API_PREFIX}/sections/{{section_id}}",
    response_model=SectionDetailResponse | GroupDetailResponse,
    tags=["Regulatory Content"],
    summary="Get a specific section or appendix of CAO 48.1",
    description=(
        "Returns the full text of a specific section or group from "
        "CAO 48.1 Instrument 2019.\n\n"
        "**Supported lookup patterns:**\n\n"
        "- `PART 1`, `PART 2`, `PART 3` — returns the Part with a "
        "list of its sections\n"
        "- `APPENDIX 1`, `APPENDIX 2`, ..., `APPENDIX 7` — returns "
        "the Appendix with a list of its sections\n"
        "- `6`, `7`, `14` — returns an individual section from the Parts "
        "(e.g. section 6 is Definitions)\n"
        "- `APPENDIX 3.2`, `APPENDIX 1.4` — returns a specific "
        "section within an Appendix\n\n"
        "Use `GET /sections` to discover available section IDs."
    ),
    responses={
        200: {"description": "Section or group found and returned."},
        404: {
            "description": "Section not found.",
            "content": {
                "application/json": {
                    "example": {
                        "error": "not_found",
                        "message": "Section 'APPENDIX 99' not found.",
                        "hint": "Use GET /sections to see available section IDs.",
                    }
                }
            },
        },
    },
)
async def get_section_detail(
    section_id: str = Path(
        description=(
            "Section identifier. Examples: 'PART 1', 'APPENDIX 3', "
            "'6', 'APPENDIX 3.2'."
        ),
        examples=["APPENDIX 3", "APPENDIX 3.2", "6"],
    ),
):
    """
    Return the full text of a specific section or group from CAO 48.1.

    Accepts group-level IDs (PART X, APPENDIX X) which return a list
    of sections within the group, or section-level IDs (APPENDIX X.N, N)
    which return the full body text of that section.
    """
    legislation = get_legislation()
    result = get_section(legislation, section_id)

    if result is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": "not_found",
                "message": f"Section '{section_id}' not found.",
                "hint": "Use GET /sections to see available section IDs.",
            },
        )

    # Determine if this is a group or section response
    if "sections" in result:
        # Group-level response
        return GroupDetailResponse(**result)
    else:
        # Section-level response
        return SectionDetailResponse(**result)
