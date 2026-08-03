from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from app.core.settings import Settings, get_settings
from app.models.jobs import NormalizedJob, SourceRecord
from app.scrapers.ats.targets import LeverTarget
from app.scrapers.base import BaseJobScraper, ScrapeError
from app.scrapers.http import RequestRateLimiter, ScraperHttpClient

PAGE_SIZE = 100


class LeverScraper(BaseJobScraper):
    """Collect one company's public Lever postings with bounded pagination."""

    def __init__(
        self,
        target: LeverTarget,
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

    def _page_url(self, page: int) -> str:
        host = "api.eu.lever.co" if self.target.region == "eu" else "api.lever.co"
        query = urlencode(
            {"mode": "json", "skip": page * PAGE_SIZE, "limit": PAGE_SIZE}
        )
        return f"https://{host}/v0/postings/{self.target.site}?{query}"

    def scrape_all(self) -> Iterator[SourceRecord]:
        seen_ids: set[str] = set()
        page_signatures: set[tuple[str, ...]] = set()
        with self._client_factory() as client:
            for page in range(self.settings.scraper_max_pages):
                items = self._parse_page(client.get_text(self._page_url(page)))
                if not items:
                    return

                signature = tuple(
                    str(item.get("id")) for item in items if item.get("id")
                )
                if signature in page_signatures:
                    raise ScrapeError("Lever returned a repeated page")
                page_signatures.add(signature)

                records = [
                    record
                    for item in items
                    if (record := self._normalize(item)) is not None
                ]
                if items and not records:
                    raise ScrapeError("Lever payload has no usable jobs")
                for record in records:
                    if record.source_job_id in seen_ids:
                        continue
                    seen_ids.add(record.source_job_id)
                    yield record

                if len(items) < PAGE_SIZE:
                    return

        raise ScrapeError(
            "Lever reached SCRAPER_MAX_PAGES before the final page"
        )

    def _parse_page(self, body: str) -> list[dict[str, Any]]:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ScrapeError("Lever jobs payload is malformed") from exc
        if not isinstance(payload, list):
            raise ScrapeError("Lever jobs must be a list")
        if payload and not any(isinstance(item, dict) for item in payload):
            raise ScrapeError("Lever jobs contain no objects")
        return [item for item in payload if isinstance(item, dict)]

    def _normalize(self, item: dict[str, Any]) -> SourceRecord | None:
        source_id = item.get("id")
        title = _text(item.get("text"))
        source_url = _text(item.get("hostedUrl"))
        if source_id in (None, "") or not title or not source_url:
            return None

        categories = item.get("categories")
        categories = categories if isinstance(categories, dict) else {}
        locations = categories.get("allLocations")
        location = _locations(locations) or _text(categories.get("location"))
        description = _text(item.get("descriptionPlain")) or _html_text(
            item.get("description")
        )
        try:
            normalized = NormalizedJob(
                title=title,
                company=self.target.company_name,
                location=location,
                description=description,
                requirements=_requirements(item.get("lists")),
                employment_type=_text(categories.get("commitment")),
                remote_type=_workplace_type(item.get("workplaceType")),
                salary=_salary(item),
                source_website=self.source_name,
                source_url=source_url,
                apply_url=_text(item.get("applyUrl")),
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


def _html_text(value: object) -> str | None:
    text = _text(value)
    if not text:
        return None
    return BeautifulSoup(text, "html.parser").get_text("\n", strip=True)


def _locations(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    unique = list(dict.fromkeys(text for item in value if (text := _text(item))))
    return ", ".join(unique) or None


def _requirements(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    for section in value:
        if not isinstance(section, dict):
            continue
        label = _text(section.get("text"))
        if label and label.rstrip(":").casefold() == "requirements":
            return _html_text(section.get("content"))
    return None


def _workplace_type(value: object) -> str | None:
    workplace = _text(value)
    return workplace if workplace in {"remote", "hybrid", "on-site"} else None


def _salary(item: dict[str, Any]) -> str | None:
    description = _text(item.get("salaryDescriptionPlain"))
    if description:
        return description
    salary = item.get("salaryRange")
    if not isinstance(salary, dict):
        return None
    minimum = salary.get("min")
    maximum = salary.get("max")
    if not isinstance(minimum, (int, float)) and not isinstance(
        maximum, (int, float)
    ):
        return None
    if minimum is not None and maximum is not None:
        amount = f"{minimum:g}\u2013{maximum:g}"
    else:
        amount = f"{minimum if minimum is not None else maximum:g}"
    currency = f"{salary['currency']} " if salary.get("currency") else ""
    interval = f" per {salary['interval']}" if salary.get("interval") else ""
    return f"{currency}{amount}{interval}"
