"""
middleware.py — FastAPI middleware for RapidAPI integration.

Provides:
- Proxy secret validation (production only), fail-closed
- Request logging with RapidAPI consumer metadata

Hardening changes versus the original:
1. Fails CLOSED when the proxy secret is missing in production — an unset
   secret is a deployment error and must refuse traffic, not allow everyone.
2. Uses hmac.compare_digest for constant-time secret comparison, so response
   timing does not leak how many leading bytes of the secret a guesser got right.
3. Does NOT exempt the OpenAPI/docs routes from the secret check in production.
   RapidAPI only needs the spec once, at import time; leaving /docs and
   /openapi.json world-readable on the origin publishes a full endpoint map.
"""

import hmac
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings

logger = logging.getLogger(__name__)

# Documentation / spec routes. In development these are always open so you can
# browse Swagger locally. In production they are treated like any other route
# and require the proxy secret (see dispatch()).
_DOC_PATHS = ("/openapi.json", "/docs", "/redoc", "/api/v1/cao481/health")


class RapidAPIProxyMiddleware(BaseHTTPMiddleware):
    """
    Middleware to validate that requests originate from the RapidAPI Runtime.

    In production, every request must include an X-RapidAPI-Proxy-Secret header
    matching the secret configured in the RapidAPI Provider Dashboard. Requests
    without a valid secret receive 403 Forbidden. If no secret is configured at
    all, the service fails closed with 500 rather than admitting everyone.

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
            The HTTP response, a 403 if proxy secret validation fails, or a
            500 if the server is misconfigured (no secret set) in production.
        """
        is_production = settings.environment == "production"

        # ─── Docs / spec routes ───
        # Open in development for local browsing; locked in production so the
        # origin does not publish an interactive endpoint map to the world.
        if request.url.path in _DOC_PATHS and not is_production:
            return await call_next(request)

        # ─── Production: validate proxy secret (fail closed) ───
        if is_production:
            expected_secret = settings.rapidapi_proxy_secret or ""

            # FAIL CLOSED: a missing/empty configured secret is a deployment
            # error. Refuse all traffic rather than silently disabling the
            # only protection on the origin (an empty expected secret would
            # otherwise match an empty provided header).
            if not expected_secret:
                logger.error(
                    "RAPIDAPI_PROXY_SECRET is not set in production — refusing "
                    "all traffic until it is configured."
                )
                return JSONResponse(
                    status_code=500,
                    content={
                        "error": "server_misconfiguration",
                        "message": "Server is not correctly configured.",
                    },
                )

            provided_secret = request.headers.get("X-RapidAPI-Proxy-Secret", "")

            # Constant-time comparison to avoid leaking the secret via timing.
            if not hmac.compare_digest(provided_secret, expected_secret):
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