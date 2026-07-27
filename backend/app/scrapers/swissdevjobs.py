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
            xml = client.get_text(self.feed_url)
            for record in self._parse_feed(xml):
                detail_html = client.get_text(
                    str(record.normalized_job.source_url)
                )
                yield self._parse_detail(detail_html, record)

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
            record = self._parse_item(item)
            if record is None or record.source_job_id in seen_ids:
                continue
            seen_ids.add(record.source_job_id)
            yield record

    def _parse_item(self, item: ET.Element) -> SourceRecord | None:
        raw = {
            child.tag: child.text
            for child in item
        }
        feed_title = _element_text(item, "title")
        link = _element_text(item, "link")
        if not feed_title or not link:
            return None

        canonical_url = _canonical_url(link)
        source_job_id = _element_text(item, "guid") or canonical_url
        title, company, title_salary = _parse_title(feed_title)
        description_html = _element_text(item, "description") or ""
        soup = BeautifulSoup(description_html, "html.parser")
        requirements = _section_text(soup, "Requirements")
        salary = _salary_from_description(soup) or title_salary
        description = soup.get_text("\n", strip=True)

        raw["canonical_url"] = canonical_url
        normalized = NormalizedJob(
            title=title,
            company=company,
            description=description or None,
            requirements=requirements,
            salary=salary,
            source_website=self.source_name,
            source_url=canonical_url,
            apply_url=canonical_url,
            posting_date=_parse_date(_element_text(item, "pubDate")),
            external_id=source_job_id,
        )
        return SourceRecord(
            raw_payload=raw,
            normalized_job=normalized,
        )

    def _parse_detail(
        self,
        html: str,
        feed_record: SourceRecord,
    ) -> SourceRecord:
        detail = _detailed_job(html)
        detail_slug = _optional_string(detail.get("jobUrl"))
        source_slug = urlsplit(
            str(feed_record.normalized_job.source_url)
        ).path.rstrip("/").rsplit("/", 1)[-1]
        if detail_slug and detail_slug != source_slug:
            raise ScrapeError(
                "SwissDevJobs detail slug does not match "
                f"{feed_record.source_job_id}"
            )

        raw_payload = {
            "rss": feed_record.raw_payload,
            "detail": detail,
        }
        normalized_data = feed_record.normalized_job.model_dump()
        normalized_data.update(
            {
                "title": _optional_string(detail.get("name"))
                or feed_record.normalized_job.title,
                "company": _optional_string(detail.get("company"))
                or feed_record.normalized_job.company,
                "location": _detail_location(detail),
                "employment_type": _optional_string(detail.get("jobType")),
                "seniority": _optional_string(detail.get("expLevel")),
                "remote_type": _remote_type(detail.get("workplace")),
                "required_languages": _string_list(
                    detail.get("language")
                ),
                "posting_date": _parse_date(
                    _optional_string(detail.get("activeFrom"))
                )
                or feed_record.normalized_job.posting_date,
            }
        )
        normalized = NormalizedJob.model_validate(normalized_data)
        return SourceRecord(
            raw_payload=raw_payload,
            normalized_job=normalized,
        )


def _element_text(item: ET.Element, name: str) -> str | None:
    element = item.find(name)
    return element.text.strip() if element is not None and element.text else None


def _parse_title(value: str) -> tuple[str, str | None, str | None]:
    salary_match = re.search(r"\s*\[(CHF[^\]]+)\]\s*$", value, re.I)
    salary = salary_match.group(1).strip() if salary_match else None
    without_salary = value[: salary_match.start()].strip() if salary_match else value
    title, separator, company = without_salary.rpartition(" @ ")
    if not separator:
        return without_salary.strip(), None, salary
    return title.strip(), company.strip() or None, salary


def _section_text(soup: BeautifulSoup, name: str) -> str | None:
    heading = soup.find(
        lambda tag: tag.name in {"b", "strong"}
        and tag.get_text(" ", strip=True).rstrip(":").casefold() == name.casefold()
    )
    if heading is None:
        return None
    parts: list[str] = []
    for sibling in heading.next_siblings:
        if getattr(sibling, "name", None) in {"b", "strong"}:
            break
        text = (
            sibling.get_text(" ", strip=True)
            if hasattr(sibling, "get_text")
            else str(sibling).strip()
        )
        if text:
            parts.append(text)
    return " ".join(parts) or None


def _salary_from_description(soup: BeautifulSoup) -> str | None:
    match = re.search(
        r"Salary:\s*(.+?)\s+per year(?:\s|$)",
        soup.get_text(" ", strip=True),
        re.I,
    )
    return match.group(1).strip() if match else None


def _canonical_url(value: str) -> str:
    parts = urlsplit(value.strip())
    query = urlencode(
        [
            (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        ]
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def _detailed_job(html: str) -> dict[str, object]:
    marker = re.search(r"window\.__detailedJob\s*=\s*", html)
    if marker is None:
        raise ScrapeError("SwissDevJobs detail payload marker is missing")
    try:
        value, _ = json.JSONDecoder().raw_decode(html, marker.end())
    except (json.JSONDecodeError, TypeError) as exc:
        raise ScrapeError("SwissDevJobs detail payload is malformed") from exc
    if not isinstance(value, dict):
        raise ScrapeError("SwissDevJobs detail payload has invalid shape")
    return value


def _optional_string(value: object) -> str | None:
    return str(value).strip() if value not in (None, "") else None


def _detail_location(detail: dict[str, object]) -> str | None:
    address = _optional_string(detail.get("address"))
    postal_code = _optional_string(detail.get("postalCode"))
    city = _optional_string(detail.get("actualCity"))
    postal_city = " ".join(
        part for part in (postal_code, city) if part
    )
    return ", ".join(
        part for part in (address, postal_city) if part
    ) or None


def _string_list(value: object) -> list[str]:
    values = value if isinstance(value, list) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _optional_string(item)
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        result.append(text)
    return result


def _remote_type(value: object) -> str | None:
    text = (_optional_string(value) or "").casefold()
    if text in {"remote", "fully remote", "home office"}:
        return "remote"
    if text in {"hybrid", "hybrid remote"}:
        return "hybrid"
    if text in {"office", "on-site", "onsite"}:
        return "on-site"
    return None
