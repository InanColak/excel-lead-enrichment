"""Retry decorator with exponential backoff for API calls."""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any, Callable, Sequence

import httpx

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = (429, 500, 502, 503, 504)


def with_retry(
    max_attempts: int = 3,
    backoff_base: float = 2.0,
    retryable_status_codes: Sequence[int] = RETRYABLE_STATUS_CODES,
) -> Callable:
    """Decorator that retries async functions on transient HTTP errors.

    On a 429 response, respects the Retry-After header if present.
    Other retryable errors use exponential backoff.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    if status not in retryable_status_codes or attempt == max_attempts:
                        raise

                    last_exc = exc
                    if status == 429:
                        retry_after = exc.response.headers.get("Retry-After")
                        wait = float(retry_after) if retry_after else backoff_base**attempt
                    else:
                        wait = backoff_base**attempt

                    logger.warning(
                        "Retrying %s (attempt %d/%d) after %.1fs — HTTP %d",
                        func.__name__,
                        attempt,
                        max_attempts,
                        wait,
                        status,
                    )
                    await asyncio.sleep(wait)

                except (httpx.TimeoutException, httpx.ConnectError) as exc:
                    if attempt == max_attempts:
                        raise
                    last_exc = exc
                    wait = backoff_base**attempt
                    logger.warning(
                        "Retrying %s (attempt %d/%d) after %.1fs — %s",
                        func.__name__,
                        attempt,
                        max_attempts,
                        wait,
                        type(exc).__name__,
                    )
                    await asyncio.sleep(wait)

            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator
