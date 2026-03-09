import logging
import time
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from api.metrics import REQUEST_LATENCY

logger = logging.getLogger(__name__)


class GlobalErrorHandler(BaseHTTPMiddleware):
    """Catch unhandled exceptions and return consistent JSON errors."""

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            user_email = request.headers.get("X-User-Email", "unknown")
            logger.exception(
                "Unhandled error on %s %s",
                request.method,
                request.url.path,
                extra={"user_email": user_email},
            )
            return JSONResponse(
                status_code=500,
                content={"error": "internal_server_error", "detail": str(exc)},
            )


class RateLimiter(BaseHTTPMiddleware):
    """Simple in-memory sliding window rate limiter.

    Limits are per-path-prefix, per-client (identified by X-User-Email header).
    Production should use Redis-backed rate limiting.
    """

    def __init__(self, app: FastAPI, limits: dict[str, tuple[int, int]] | None = None):
        """
        limits: dict mapping path prefix to (max_requests, window_seconds)
        Example: {"/ingest/jobs": (10, 60)} means 10 requests per 60 seconds.
        """
        super().__init__(app)
        self.limits = limits or {}
        self._windows: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        for prefix, (max_req, window_sec) in self.limits.items():
            if request.url.path.startswith(prefix) and request.method in ("POST", "PUT", "PATCH"):
                client_id = request.headers.get(
                    "X-User-Email", request.client.host if request.client else "unknown"
                )
                key = f"{prefix}:{client_id}"
                now = time.time()

                # Clean old entries
                self._windows[key] = [t for t in self._windows[key] if t > now - window_sec]

                if len(self._windows[key]) >= max_req:
                    return JSONResponse(
                        status_code=429,
                        content={
                            "error": "rate_limited",
                            "detail": f"Max {max_req} requests per {window_sec}s",
                        },
                    )

                self._windows[key].append(now)

        return await call_next(request)


class RequestLogger(BaseHTTPMiddleware):
    """Log request method, path, status, and duration."""

    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration_ms = (time.time() - start) * 1000

        if request.url.path not in ("/health", "/metrics"):
            REQUEST_LATENCY.labels(method=request.method, path=request.url.path).observe(
                duration_ms / 1000
            )
            user_email = request.headers.get("X-User-Email", "unknown")
            logger.info(
                "%s %s -> %d (%.1fms)",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
                extra={"user_email": user_email, "duration_ms": round(duration_ms, 1)},
            )

        return response
