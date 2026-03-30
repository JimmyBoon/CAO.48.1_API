"""
Route handler for the GET /guide endpoint.

Returns structured documentation for every API endpoint — purpose, parameters,
worked examples, and common mistakes — for LLM and integration consumption.
"""

from fastapi import APIRouter

from app.config import settings
from app.data.guide import GUIDE

router = APIRouter(tags=["Guide"])


@router.get(
    "/guide",
    summary="API usage guide",
    description=(
        "Returns a structured JSON document covering every endpoint: purpose, "
        "when to use it versus alternatives, the non-obvious parameter semantics, "
        "a worked example, and common integration mistakes.\n\n"
        "Call this endpoint **once at the start of a session** to orient an LLM or "
        "integration before making compliance calls. The response is stable between "
        "requests and may be cached for the duration of a session."
    ),
    responses={
        200: {"description": "Guide document returned successfully."},
    },
)
async def get_guide() -> dict:
    return {**GUIDE, "version": settings.app_version}
