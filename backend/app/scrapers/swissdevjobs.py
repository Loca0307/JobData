from __future__ import annotations

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
    parser_version = "swissdevjobs-rss-v1"

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
        yield from self._parse_feed(xml)

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
        responsibilities = _section_text(soup, "Responsibilities")
        technologies = _section_text(soup, "Technologies")
        more = _section_text(soup, "More")
        salary = _salary_from_description(soup) or title_salary
        description = " ".join(
            part for part in (responsibilities, technologies, more) if part
        ) or soup.get_text(" ", strip=True)

        raw["canonical_url"] = canonical_url
        normalized = NormalizedJob(
            source_name=self.source_name,
            source_job_id=source_job_id,
            source_url=canonical_url,
            apply_url=canonical_url,
            title=title,
            company_name=company,
            description=description or None,
            responsibilities=responsibilities,
            requirements=requirements,
            salary_raw=salary,
            posted_at=_parse_date(_element_text(item, "pubDate")),
            parser_version=self.parser_version,
            raw_payload=raw,
        )
        return SourceRecord(
            source_name=self.source_name,
            source_job_id=source_job_id,
            raw_payload=raw,
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
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
