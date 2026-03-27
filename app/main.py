"""
main.py — CAO 48.1 Compliance API entry point.

A stateless REST API for validating flight crew duty periods against
the Australian Civil Aviation Order 48.1 Instrument 2019.

Phase 0: Health endpoint, RapidAPI middleware, OpenAPI spec generation.

Usage:
    # Local development
    uvicorn app.main:app --reload

    # Docker
    docker compose up
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.middleware import RapidAPIProxyMiddleware
from app.models.health import (
    AppendixStatus,
    EndpointsInfo,
    HealthResponse,
    LegislationInfo,
)

# ─── Logging ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Appendix definitions ──────────────────────────────────────────────
# Central registry of all appendices — status updated as features are built.
APPENDICES = [
    AppendixStatus(id="1", title="Basic Limits", status="planned"),
    AppendixStatus(
        id="2", title="Multi-Pilot Operations", status="planned"
    ),
    AppendixStatus(
        id="3",
        title="Multi-Pilot Operations Except Complex",
        status="planned",
    ),
    AppendixStatus(id="4", title="Any Operations", status="planned"),
    AppendixStatus(id="4A", title="Balloon Operations", status="planned"),
    AppendixStatus(
        id="4B",
        title="Medical Transport & Emergency Service Operations",
        status="planned",
    ),
    AppendixStatus(
        id="5",
        title="Aerial Work & Associated Flight Training",
        status="planned",
    ),
    AppendixStatus(
        id="5A", title="Daylight Aerial Work", status="planned"
    ),
    AppendixStatus(id="6", title="Flight Training", status="planned"),
]

# ─── Endpoint registry ─────────────────────────────────────────────────
# Tracks which endpoints are live vs planned. Update as phases are built.
AVAILABLE_ENDPOINTS = ["/health"]
PLANNED_ENDPOINTS = [
    "/sections",
    "/sections/{section_id}",
    "/limits/fdp-table/{appendix}",
    "/limits/cumulative/{appendix}",
    "/calculate/max-fdp",
    "/calculate/min-off-duty",
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
