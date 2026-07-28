import httpx
import pytest
import respx

from app.core.settings import Settings
from app.scrapers.http import RequestRateLimiter, ScraperHttpClient


class NoopLimiter:
    def wait(self) -> None:
        pass


def test_rate_limiter_spaces_request_starts():
    times = iter([0.0, 0.25])
    sleeps: list[float] = []
    limiter = RequestRateLimiter(
        2,
        sleeper=sleeps.append,
        clock=lambda: next(times),
    )

    limiter.wait()
    limiter.wait()

    assert sleeps == [0.25]


@respx.mock
def test_http_client_retries_throttling_and_honors_retry_after():
    route = respx.get("https://example.test/jobs").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(200, text="ok"),
        ]
    )
    sleeps: list[float] = []

    with ScraperHttpClient(
        Settings(SCRAPER_MAX_RETRIES=1),
        NoopLimiter(),  # type: ignore[arg-type]
        sleeper=sleeps.append,
    ) as client:
        result = client.get_text("https://example.test/jobs")

    assert result == "ok"
    assert route.call_count == 2
    assert sleeps == [2.0]


@respx.mock
def test_http_client_does_not_retry_a_permanent_error():
    route = respx.get("https://example.test/jobs").mock(
        return_value=httpx.Response(404)
    )

    with ScraperHttpClient(
        Settings(),
        NoopLimiter(),  # type: ignore[arg-type]
        sleeper=lambda _: None,
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            client.get_text("https://example.test/jobs")

    assert route.call_count == 1
