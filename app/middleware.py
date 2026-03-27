"""
middleware.py — FastAPI middleware for RapidAPI integration.

Provides:
- Proxy secret validation (production only)
- Request logging with RapidAPI consumer metadata
"""

import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings

logger = logging.getLogger(__name__)


class RapidAPIProxyMiddleware(BaseHTTPMiddleware):
    """
    Middleware to validate that requests originate from the RapidAPI Runtime.

    In production, every request must include an X-RapidAPI-Proxy-Secret header
    matching the secret configured in the RapidAPI Provider Dashboard. Requests
    without a valid secret receive 403 Forbidden.

    In development mode (ENVIRONMENT=development), validation is skipped
    to allow direct local testing without routing through RapidAPI.

    Additionally logs the RapidAPI consumer metadata (user, subscription tier)
    for observability.
    """

    async def dispatch(self, request: Request, call_next):
        """
        Process each incoming request through RapidAPI validation.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or route handler in the chain.

        Returns:
            The HTTP response, or a 403 error if proxy secret validation fails.
        """
        # ─── Skip validation for OpenAPI docs endpoints ───
        # These need to be accessible for RapidAPI to fetch the spec
        if request.url.path in ("/openapi.json", "/docs", "/redoc"):
            return await call_next(request)

        # ─── Production: validate proxy secret ───
        if settings.environment == "production":
            proxy_secret = request.headers.get("X-RapidAPI-Proxy-Secret", "")
            if proxy_secret != settings.rapidapi_proxy_secret:
                logger.warning(
                    "Rejected request — invalid or missing X-RapidAPI-Proxy-Secret "
                    "from %s",
                    request.client.host if request.client else "unknown",
                )
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": "forbidden",
                        "message": "Invalid or missing RapidAPI proxy secret.",
                    },
                )

        # ─── Log RapidAPI consumer metadata ───
        rapidapi_user = request.headers.get("X-RapidAPI-User", "direct")
        rapidapi_subscription = request.headers.get(
            "X-RapidAPI-Subscription", "none"
        )
        logger.info(
            "%s %s — user=%s subscription=%s",
            request.method,
            request.url.path,
            rapidapi_user,
            rapidapi_subscription,
        )

        # ─── Continue to route handler ───
        response = await call_next(request)
        return response
