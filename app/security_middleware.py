
import logging
import os
import time
from collections import defaultdict, deque
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


logger = logging.getLogger("ats.security")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )

        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self' https://cdn.jsdelivr.net; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'"
        )

        response.headers["Cache-Control"] = (
            "no-store"
            if request.url.path.startswith(
                ("/dashboard", "/phase7", "/login")
            )
            else response.headers.get(
                "Cache-Control", "no-cache"
            )
        )

        if os.getenv("SESSION_HTTPS_ONLY", "false").lower() == "true":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000"
            )

        return response


class LoginRateLimitMiddleware(BaseHTTPMiddleware):
    """
    Development-only, in-memory login rate limiter.

    For production, replace this with a shared Redis-backed
    limiter and configure trusted reverse proxies.
    """

    def __init__(
        self,
        app,
        max_attempts=5,
        window_seconds=60,
    ):
        super().__init__(app)
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.attempts = defaultdict(deque)
        self.lock = Lock()

    async def dispatch(self, request, call_next):
        if (
            request.method != "POST"
            or request.url.path != "/login"
        ):
            return await call_next(request)

        client_ip = (
            request.client.host
            if request.client is not None
            else "unknown"
        )

        now = time.monotonic()

        with self.lock:
            history = self.attempts[client_ip]

            while history and (
                now - history[0] >= self.window_seconds
            ):
                history.popleft()

            if len(history) >= self.max_attempts:
                logger.warning(
                    "Browser login rate limit reached"
                )

                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": (
                            "Too many login attempts. "
                            "Please try again later."
                        )
                    },
                    headers={"Retry-After": str(self.window_seconds)},
                )

            history.append(now)

        return await call_next(request)
