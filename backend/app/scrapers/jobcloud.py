from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from app.core.settings import Settings, get_settings
from app.models.jobs import NormalizedJob, SourceRecord
from app.scrapers.base import BaseJobScraper, ScrapeError
from app.scrapers.http import RequestRateLimiter, ScraperHttpClient


class JobCloudScraper(BaseJobScraper):
    """Read listing pages used by jobs.ch and jobup.ch."""

    base_url: str
    listing_path: str
    detail_path: str
    listing_query: tuple[tuple[str, str], ...] = ()

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
                records = self._parse_listing(
                    client.get_text(self._listing_url(page))
                )
                if not records:
                    return

                found_new_job = False
                for record in records:
                    if record.source_job_id in seen_ids:
                        continue
                    seen_ids.add(record.source_job_id)
                    found_new_job = True
                    detail = client.get_text(
                        str(record.normalized_job.source_url)
                    )
                    yield self._enrich_from_detail(detail, record)

                if not found_new_job:
                    return

        raise ScrapeError(
            f"{self.source_name} reached SCRAPER_MAX_PAGES before an empty page"
        )

    def _listing_url(self, page: int) -> str:
        if page < 1:
            raise ValueError("page must be at least 1")
        query: dict[str, str | int] = dict(self.listing_query)
        if page > 1:
            query["page"] = page
        suffix = f"?{urlencode(query)}" if query else ""
        return f"{self.base_url}{self.listing_path}{suffix}"

    def _parse_listing(self, html: str) -> list[SourceRecord]:
        marker = re.search(r"__INIT__\s*=\s*", html)
        if marker is None:
            raise ScrapeError(f"{self.source_name} listing marker is missing")

        try:
            state, _ = json.JSONDecoder().raw_decode(html, marker.end())
            results = state["vacancy"]["results"]["main"]["results"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ScrapeError(
                f"{self.source_name} listing payload is malformed"
            ) from exc

        if not isinstance(results, list):
            raise ScrapeError(f"{self.source_name} listing results must be a list")

        records = [
            record
            for item in results
            if isinstance(item, dict)
            and (record := self._normalize(item)) is not None
        ]
        if results and not records:
            raise ScrapeError(f"{self.source_name} listing has no usable jobs")
        return records

    def _normalize(self, item: dict[str, Any]) -> SourceRecord | None:
        source_id = item.get("id")
        title = item.get("title")
        if not source_id or not title:
            return None

        source_id = str(source_id)
        source_url = f"{self.base_url}{self.detail_path}{source_id}/"
        company = item.get("company")
        company_name = company.get("name") if isinstance(company, dict) else None

        job = NormalizedJob(
            title=str(title),
            company=_text(company_name),
            location=_text(item.get("place")),
            employment_type=_text(item.get("employmentType")),
            source_website=self.source_name,
            source_url=source_url,
            apply_url=source_url,
            posting_date=_date(item.get("initialPublicationDate"))
            or _date(item.get("publicationDate")),
            external_id=source_id,
        )
        return SourceRecord(raw_payload=item, normalized_job=job)

    def _enrich_from_detail(
        self,
        html: str,
        listing_record: SourceRecord,
    ) -> SourceRecord:
        detail = _job_posting(html)
        identifier = _dictionary(detail.get("identifier")).get("value")
        if identifier and str(identifier) != listing_record.source_job_id:
            raise ScrapeError("JobCloud listing and detail IDs do not match")

        address = _dictionary(
            _dictionary(detail.get("jobLocation")).get("address")
        )
        location = ", ".join(
            str(address[field])
            for field in (
                "streetAddress",
                "postalCode",
                "addressLocality",
                "addressRegion",
                "addressCountry",
            )
            if address.get(field)
        )
        description_html = _text(detail.get("description"))
        description = (
            BeautifulSoup(description_html, "html.parser").get_text(
                "\n", strip=True
            )
            if description_html
            else None
        )
        organization = _dictionary(detail.get("hiringOrganization"))
        normalized = listing_record.normalized_job.model_copy(
            update={
                "title": _text(detail.get("title"))
                or listing_record.normalized_job.title,
                "company": listing_record.normalized_job.company
                or _text(organization.get("name")),
                "location": location or listing_record.normalized_job.location,
                "description": description,
                "employment_type": _text(detail.get("employmentType"))
                or listing_record.normalized_job.employment_type,
                "remote_type": (
                    "remote"
                    if detail.get("jobLocationType") == "TELECOMMUTE"
                    else None
                ),
                "salary": _salary(detail.get("baseSalary")),
                "apply_url": _apply_url(detail)
                or listing_record.normalized_job.apply_url,
                "posting_date": _date(detail.get("datePosted"))
                or listing_record.normalized_job.posting_date,
            }
        )
        return SourceRecord(
            raw_payload={
                "listing": listing_record.raw_payload,
                "detail": detail,
            },
            normalized_job=normalized,
        )


class JobsChScraper(JobCloudScraper):
    source_name = "jobs.ch"
    base_url = "https://www.jobs.ch"
    listing_path = "/en/vacancies/"
    detail_path = "/en/vacancies/detail/"
    listing_query = (("term", ""),)


class JobupChScraper(JobCloudScraper):
    source_name = "jobup.ch"
    base_url = "https://www.jobup.ch"
    listing_path = "/en/jobs/"
    detail_path = "/en/jobs/detail/"


def _text(value: object) -> str | None:
    return str(value).strip() if value not in (None, "") else None


def _date(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _dictionary(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _job_posting(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            payload = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
                return candidate
            if isinstance(candidate, dict):
                for item in candidate.get("@graph", []):
                    if isinstance(item, dict) and item.get("@type") == "JobPosting":
                        return item
    raise ScrapeError("JobCloud detail JobPosting JSON-LD is missing")


def _salary(value: object) -> str | None:
    salary = _dictionary(value)
    amount = _dictionary(salary.get("value"))
    minimum = amount.get("minValue")
    maximum = amount.get("maxValue")
    if not isinstance(minimum, (int, float)) and not isinstance(
        maximum, (int, float)
    ):
        return None
    number = (
        f"{minimum:g}–{maximum:g}"
        if minimum is not None and maximum is not None
        else f"{minimum if minimum is not None else maximum:g}"
    )
    currency = f"{salary.get('currency')} " if salary.get("currency") else ""
    period = f" per {str(amount['unitText']).lower()}" if amount.get("unitText") else ""
    return f"{currency}{number}{period}"


def _apply_url(detail: dict[str, Any]) -> str | None:
    action = _dictionary(detail.get("potentialAction"))
    target = _dictionary(action.get("target"))
    return _text(target.get("urlTemplate"))
