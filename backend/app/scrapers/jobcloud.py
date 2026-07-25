from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from app.core.settings import Settings, get_settings
from app.models.jobs import NormalizedJob, SourceRecord
from app.scrapers.base import BaseJobScraper, ScrapeError
from app.scrapers.http import RequestRateLimiter, ScraperHttpClient


class JobCloudScraper(BaseJobScraper):
    """Shared unfiltered listing adapter for JobCloud-backed boards."""

    parser_version = "jobcloud-listing-v1"
    base_url: str
    listing_path: str
    detail_path: str

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client_factory: Callable[[], ScraperHttpClient] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._rate_limiter = RequestRateLimiter(
            self.settings.scraper_requests_per_second
        )
        self._client_factory = client_factory or (
            lambda: ScraperHttpClient(self.settings, self._rate_limiter)
        )

    def scrape_all(self) -> Iterator[SourceRecord]:
        seen_ids: set[str] = set()
        with self._client_factory() as client:
            for page in range(1, self.settings.scraper_max_pages + 1):
                html = client.get_text(self._listing_url(page))
                records = self._parse_listing(html)
                if not records:
                    return

                new_records = [
                    record for record in records if record.source_job_id not in seen_ids
                ]
                if not new_records:
                    return
                for record in new_records:
                    seen_ids.add(record.source_job_id)
                    yield record
            raise ScrapeError(
                f"{self.source_name} reached SCRAPER_MAX_PAGES="
                f"{self.settings.scraper_max_pages} before exhaustion"
            )

    def _listing_url(self, page: int) -> str:
        if page < 1:
            raise ValueError("page must be at least 1")
        query = "" if page == 1 else f"?{urlencode({'page': page})}"
        return f"{self.base_url}{self.listing_path}{query}"

    def _parse_listing(self, html: str) -> list[SourceRecord]:
        marker = re.search(r"__INIT__\s*=\s*", html)
        if marker is None:
            raise ScrapeError(f"{self.source_name} listing payload marker is missing")
        try:
            state, _ = json.JSONDecoder().raw_decode(html, marker.end())
            results = state["vacancy"]["results"]["main"]["results"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ScrapeError(
                f"{self.source_name} listing payload is malformed"
            ) from exc
        if not isinstance(results, list):
            raise ScrapeError(f"{self.source_name} listing results have invalid shape")

        records = [
            record
            for summary in results
            if isinstance(summary, dict)
            and (record := self._normalize_summary(summary)) is not None
        ]
        if results and not records:
            raise ScrapeError(
                f"{self.source_name} listing has no usable records; "
                "schema may have changed"
            )
        return records

    def _normalize_summary(self, summary: dict[str, Any]) -> SourceRecord | None:
        source_job_id = summary.get("id")
        title = summary.get("title")
        if not source_job_id or not title:
            return None
        source_job_id = str(source_job_id)
        detail_url = f"{self.base_url}{self.detail_path}{source_job_id}/"
        company = summary.get("company")
        company_name = company.get("name") if isinstance(company, dict) else None
        normalized = NormalizedJob(
            source_name=self.source_name,
            source_job_id=source_job_id,
            source_url=detail_url,
            apply_url=detail_url,
            title=str(title),
            company_name=str(company_name) if company_name else None,
            raw_location_text=_optional_string(summary.get("place")),
            employment_type=_optional_string(summary.get("employmentType")),
            posted_at=_parse_datetime(summary.get("publicationDate")),
            parser_version=self.parser_version,
            raw_payload=summary,
        )
        return SourceRecord(
            source_name=self.source_name,
            source_job_id=source_job_id,
            raw_payload=summary,
            normalized_job=normalized,
        )


class JobsChScraper(JobCloudScraper):
    source_name = "jobs.ch"
    base_url = "https://www.jobs.ch"
    listing_path = "/en/vacancies/"
    detail_path = "/en/vacancies/detail/"


class JobupChScraper(JobCloudScraper):
    source_name = "jobup.ch"
    base_url = "https://www.jobup.ch"
    listing_path = "/en/jobs/"
    detail_path = "/en/jobs/detail/"


def _optional_string(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
