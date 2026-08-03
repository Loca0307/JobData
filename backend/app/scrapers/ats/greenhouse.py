from __future__ import annotations

import html
import json
from collections.abc import Callable, Iterator
from typing import Any

from bs4 import BeautifulSoup

from app.core.settings import Settings, get_settings
from app.models.jobs import NormalizedJob, SourceRecord
from app.scrapers.ats.targets import GreenhouseTarget
from app.scrapers.base import BaseJobScraper, ScrapeError
from app.scrapers.http import RequestRateLimiter, ScraperHttpClient


class GreenhouseScraper(BaseJobScraper):
    """Collect one company's public Greenhouse job board."""

    def __init__(
        self,
        target: GreenhouseTarget,
        settings: Settings | None = None,
        *,
        client_factory: Callable[[], ScraperHttpClient] | None = None,
    ) -> None:
        self.target = target
        self.source_name = target.source_name
        self.settings = settings or get_settings()
        self._rate_limiter = RequestRateLimiter(
            self.settings.scraper_requests_per_second
        )
        self._client_factory = client_factory or (
            lambda: ScraperHttpClient(self.settings, self._rate_limiter)
        )

    @property
    def jobs_url(self) -> str:
        return (
            "https://boards-api.greenhouse.io/v1/boards/"
            f"{self.target.board_token}/jobs?content=true"
        )

    def scrape_all(self) -> Iterator[SourceRecord]:
        with self._client_factory() as client:
            yield from self._parse_jobs(client.get_text(self.jobs_url))

    def _parse_jobs(self, body: str) -> list[SourceRecord]:
        try:
            payload = json.loads(body)
            jobs = payload["jobs"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ScrapeError("Greenhouse jobs payload is malformed") from exc
        if not isinstance(jobs, list):
            raise ScrapeError("Greenhouse jobs must be a list")

        records: list[SourceRecord] = []
        seen_ids: set[str] = set()
        usable_candidates = 0
        for item in jobs:
            # Greenhouse represents general-interest prospect posts as jobs with
            # a null internal_job_id. They are intentionally not vacancies.
            if (
                isinstance(item, dict)
                and "internal_job_id" in item
                and item["internal_job_id"] is None
            ):
                continue
            usable_candidates += 1
            record = self._normalize(item) if isinstance(item, dict) else None
            if record is None or record.source_job_id in seen_ids:
                continue
            seen_ids.add(record.source_job_id)
            records.append(record)

        if usable_candidates and not records:
            raise ScrapeError("Greenhouse payload has no usable jobs")
        return records

    def _normalize(self, item: dict[str, Any]) -> SourceRecord | None:
        source_id = item.get("id")
        title = _text(item.get("title"))
        source_url = _text(item.get("absolute_url"))
        if source_id in (None, "") or not title or not source_url:
            return None

        location_data = item.get("location")
        location = (
            _text(location_data.get("name"))
            if isinstance(location_data, dict)
            else None
        )
        content = _text(item.get("content"))
        description = (
            BeautifulSoup(html.unescape(content), "html.parser").get_text(
                "\n", strip=True
            )
            if content
            else None
        )
        try:
            normalized = NormalizedJob(
                title=title,
                company=self.target.company_name,
                location=location,
                description=description,
                source_website=self.source_name,
                source_url=source_url,
                apply_url=source_url,
                external_id=str(source_id),
            )
        except ValueError:
            return None

        return SourceRecord(
            raw_payload={
                "target": self.target.model_dump(mode="json"),
                "job": item,
            },
            normalized_job=normalized,
        )


def _text(value: object) -> str | None:
    return str(value).strip() if value not in (None, "") else None
