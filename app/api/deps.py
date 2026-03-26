"""FastAPI dependencies — database session provider, API key auth, and rate limiting."""

import time
from collections.abc import AsyncGenerator

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.models.base import get_db_session

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session for request-scoped dependency injection."""
    async for session in get_db_session():
        yield session


async def verify_api_key(
    api_key: str | None = Security(api_key_header),
) -> bool:
    """Validate the X-API-Key header against the configured secret."""
    if api_key is None or api_key != settings.secret_key:
        raise HTTPException(
            status_code=403,
            detail="Invalid or missing API key",
        )
    return True


class RateLimiter:
    """In-memory per-IP sliding-window rate limiter."""

    def __init__(
        self,
        max_requests: int = 60,
        window_seconds: int = 60,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = {}

    async def __call__(self, request: Request) -> None:
        client_ip = (
            request.client.host if request.client else "unknown"
        )
        now = time.time()
        cutoff = now - self.window_seconds

        if client_ip not in self._requests:
            self._requests[client_ip] = []

        self._requests[client_ip] = [
            ts
            for ts in self._requests[client_ip]
            if ts > cutoff
        ]

        if len(self._requests[client_ip]) >= self.max_requests:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
            )

        self._requests[client_ip].append(now)


rate_limiter = RateLimiter(max_requests=60, window_seconds=60)
