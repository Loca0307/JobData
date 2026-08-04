from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from app.core.settings import Settings, get_settings
from app.core.swiss_territory import SWISS_COUNTRY_CODE
from app.models.jobs import NormalizedJob, SourceRecord
from app.scrapers.base import BaseJobScraper, ScrapeError
from app.scrapers.http import RequestRateLimiter, ScraperHttpClient


class SwissDevJobsScraper(BaseJobScraper):
    source_name = "swissdevjobs.ch"
    feed_url = "https://swissdevjobs.ch/rss"

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
        with self._client_factory() as client:
            for record in self._parse_feed(client.get_text(self.feed_url)):
                detail_html = client.get_text(
                    str(record.normalized_job.source_url)
                )
                yield self._enrich_from_detail(detail_html, record)

    def _parse_feed(self, xml: str) -> Iterator[SourceRecord]:
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise ScrapeError("SwissDevJobs RSS is malformed") from exc

        channel = root.find("./channel")
        if channel is None:
            raise ScrapeError("SwissDevJobs RSS channel is missing")

        seen_ids: set[str] = set()
        for item in channel.findall("item"):
            record = self._normalize(item)
            if record is None or record.source_job_id in seen_ids:
                continue
            seen_ids.add(record.source_job_id)
            yield record

    def _normalize(self, item: ET.Element) -> SourceRecord | None:
        raw = {child.tag: child.text for child in item}
        feed_title = _element_text(item, "title")
        link = _element_text(item, "link")
        if not feed_title or not link:
            return None

        source_url = _canonical_url(link)
        source_id = _element_text(item, "guid") or source_url
        title, company, title_salary = _parse_title(feed_title)
        description_html = _element_text(item, "description") or ""
        description = BeautifulSoup(
            description_html, "html.parser"
        ).get_text("\n", strip=True)

        raw["canonical_url"] = source_url
        job = NormalizedJob(
            title=title,
            company=company,
            description=description or None,
            requirements=_requirements(description_html),
            salary=_salary(description) or title_salary,
            source_website=self.source_name,
            source_url=source_url,
            apply_url=source_url,
            posting_date=_date(_element_text(item, "pubDate")),
            external_id=source_id,
        )
        return SourceRecord(raw_payload=raw, normalized_job=job)

    def _enrich_from_detail(
        self,
        html: str,
        feed_record: SourceRecord,
    ) -> SourceRecord:
        marker = re.search(r"window\.__detailedJob\s*=\s*", html)
        if marker is None:
            raise ScrapeError("SwissDevJobs detail payload is missing")
        try:
            detail, _ = json.JSONDecoder().raw_decode(html, marker.end())
        except json.JSONDecodeError as exc:
            raise ScrapeError("SwissDevJobs detail payload is malformed") from exc
        if not isinstance(detail, dict):
            raise ScrapeError("SwissDevJobs detail payload must be an object")

        source_slug = urlsplit(
            str(feed_record.normalized_job.source_url)
        ).path.rstrip("/").rsplit("/", 1)[-1]
        if detail.get("jobUrl") and detail["jobUrl"] != source_slug:
            raise ScrapeError("SwissDevJobs listing and detail IDs do not match")

        location = ", ".join(
            str(detail[field])
            for field in ("address", "postalCode", "actualCity")
            if detail.get(field)
        )
        workplace = str(detail.get("workplace", "")).casefold()
        remote_type = workplace if workplace in {"remote", "hybrid"} else None
        languages = detail.get("language")
        required_languages = (
            [str(item) for item in languages]
            if isinstance(languages, list)
            else [str(languages)] if languages else []
        )
        normalized = feed_record.normalized_job.model_copy(
            update={
                "title": str(detail.get("name") or feed_record.normalized_job.title),
                "company": detail.get("company")
                or feed_record.normalized_job.company,
                "location": location or None,
                # SwissDevJobs' public contract is explicitly Swiss vacancies;
                # unlike global ATS boards, its detail payload has no country.
                "country_code": SWISS_COUNTRY_CODE,
                "employment_type": detail.get("jobType"),
                "seniority": detail.get("expLevel"),
                "remote_type": remote_type,
                "required_languages": required_languages,
                "posting_date": _iso_date(detail.get("activeFrom"))
                or feed_record.normalized_job.posting_date,
            }
        )
        return SourceRecord(
            raw_payload={"rss": feed_record.raw_payload, "detail": detail},
            normalized_job=normalized,
        )


def _element_text(item: ET.Element, name: str) -> str | None:
    element = item.find(name)
    return element.text.strip() if element is not None and element.text else None


def _parse_title(value: str) -> tuple[str, str | None, str | None]:
    salary_match = re.search(r"\s*\[(CHF[^\]]+)\]\s*$", value, re.I)
    salary = salary_match.group(1).strip() if salary_match else None
    without_salary = value[: salary_match.start()] if salary_match else value
    title, separator, company = without_salary.rpartition(" @ ")
    if not separator:
        return without_salary.strip(), None, salary
    return title.strip(), company.strip() or None, salary


def _requirements(description_html: str) -> str | None:
    soup = BeautifulSoup(description_html, "html.parser")
    heading = soup.find(
        lambda tag: tag.name in {"b", "strong"}
        and tag.get_text(" ", strip=True).rstrip(":").casefold()
        == "requirements"
    )
    if heading is None:
        return None
    sibling = heading.find_next_sibling()
    return sibling.get_text(" ", strip=True) if sibling else None


def _salary(description: str) -> str | None:
    match = re.search(r"Salary:\s*(.+?)\s+per year", description, re.I)
    return match.group(1).strip() if match else None


def _canonical_url(value: str) -> str:
    parts = urlsplit(value.strip())
    query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_")
        ]
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def _iso_date(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
