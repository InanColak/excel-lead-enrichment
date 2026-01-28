"""Async token-bucket rate limiter with per-API configuration."""

from __future__ import annotations

import asyncio
import time


class TokenBucketRateLimiter:
    """Rate limiter using the token-bucket algorithm.

    Usage::

        limiter = TokenBucketRateLimiter(rate=50, per=60.0)  # 50 requests per 60s
        async with limiter:
            await make_api_call()
    """

    def __init__(self, rate: int, per: float = 60.0, burst: int | None = None) -> None:
        self.rate = rate
        self.per = per
        self.burst = burst or rate
        self._tokens = float(self.burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a token is available, then consume it."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(
                self.burst,
                self._tokens + elapsed * (self.rate / self.per),
            )
            self._last_refill = now

            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) * (self.per / self.rate)
                await asyncio.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0

    async def __aenter__(self) -> TokenBucketRateLimiter:
        await self.acquire()
        return self

    async def __aexit__(self, *args: object) -> None:
        pass
