"""Base HTTP client with retry logic and rate limiting."""

from __future__ import annotations

import httpx

from ..config import Settings
from .rate_limiter import TokenBucketRateLimiter


class BaseAPIClient:
    """Base class for Apollo and Lusha API clients.

    Provides a shared httpx.AsyncClient, rate limiter, and configuration.
    Subclasses implement the API-specific logic.
    """

    def __init__(
        self,
        settings: Settings,
        rate_limiter: TokenBucketRateLimiter,
        base_url: str,
        headers: dict[str, str],
    ) -> None:
        self._settings = settings
        self._limiter = rate_limiter
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=httpx.Timeout(settings.http_timeout_seconds),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: object,
    ) -> httpx.Response:
        """Make a rate-limited HTTP request."""
        async with self._limiter:
            response = await self._client.request(method, path, **kwargs)
            response.raise_for_status()
            return response

    async def __aenter__(self) -> BaseAPIClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
