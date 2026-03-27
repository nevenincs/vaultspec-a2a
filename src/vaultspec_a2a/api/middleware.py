"""HTTP middleware for the API layer.

Contains cache-control headers for static SPA assets (ADR-007 S5).
"""

import re

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse

__all__ = [
    "CacheControlMiddleware",
]

# React/Vite hashed immutable assets: /_app/immutable/** or /assets/**
_IMMUTABLE_PATTERN = re.compile(r"^/(_app/immutable|assets)/")
_CACHE_IMMUTABLE = "public, max-age=31536000, immutable"
_CACHE_HTML = "no-cache"


class CacheControlMiddleware(BaseHTTPMiddleware):
    """Set Cache-Control headers for static SPA assets (ADR-007 S5).

    - ``/_app/immutable/**`` or ``/assets/**`` (content-hashed JS/CSS): cache forever
    - HTML responses (``index.html``, SPA fallback): ``no-cache``
    """

    async def dispatch(
        self,
        request: StarletteRequest,
        call_next: RequestResponseEndpoint,
    ) -> StarletteResponse:
        response = await call_next(request)
        path = request.url.path
        if _IMMUTABLE_PATTERN.search(path):
            response.headers["Cache-Control"] = _CACHE_IMMUTABLE
        elif response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = _CACHE_HTML
        return response
