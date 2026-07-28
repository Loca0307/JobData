from __future__ import annotations

import threading
import time
from collections.abc import Callable

import httpx

from app.core.settings import Settings


class RequestRateLimiter:
    """Space request starts for every client that shares this limiter."""

    def __init__(
        self,
        requests_per_second: float,
        *,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._interval = 1 / requests_per_second
        self._sleep = sleeper
        self._clock = clock
        self._next_request_at = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        # The lock prevents concurrent workers from reserving the same slot.
        with self._lock:
            now = self._clock()
            delay = max(0.0, self._next_request_at - now)
            self._next_request_at = max(now, self._next_request_at) + self._interval
        if delay:
            self._sleep(delay)


class ScraperHttpClient:
    """Small GET-only client shared by the teaching scrapers."""

    def __init__(
        self,
        settings: Settings,
        rate_limiter: RequestRateLimiter,
        *,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._rate_limiter = rate_limiter
        self._sleep = sleeper
        self._client = httpx.Client(
            headers={"User-Agent": settings.effective_user_agent},
            timeout=httpx.Timeout(
                connect=settings.scraper_connect_timeout_seconds,
                read=settings.scraper_read_timeout_seconds,
                write=settings.scraper_read_timeout_seconds,
                pool=settings.scraper_connect_timeout_seconds,
            ),
            follow_redirects=True,
            max_redirects=5,
        )

    def get_text(self, url: str) -> str:
        for attempt in range(self._settings.scraper_max_retries + 1):
            self._rate_limiter.wait()
            try:
                response = self._client.get(url)
                response.raise_for_status()
                return response.text
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == self._settings.scraper_max_retries:
                    raise
            except httpx.HTTPStatusError as exc:
                retryable = exc.response.status_code in {429, 500, 502, 503, 504}
                if not retryable or attempt == self._settings.scraper_max_retries:
                    raise
                retry_after = exc.response.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    self._sleep(float(retry_after))
                    continue

            backoff = self._settings.scraper_retry_backoff_seconds * (2**attempt)
            self._sleep(backoff)

        raise AssertionError("retry loop terminated unexpectedly")
    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ScraperHttpClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
