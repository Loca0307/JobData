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
    """Shared unfiltered listing adapter for JobCloud-backed boards."""

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
                    detail_html = client.get_text(
                        str(record.normalized_job.source_url)
                    )
                    yield self._parse_detail(detail_html, record)
            raise ScrapeError(
                f"{self.source_name} reached SCRAPER_MAX_PAGES="
                f"{self.settings.scraper_max_pages} before exhaustion"
            )

    def _listing_url(self, page: int) -> str:
        if page < 1:
            raise ValueError("page must be at least 1")
        query_params: dict[str, str | int] = dict(self.listing_query)
        if page > 1:
            query_params["page"] = page
        query = f"?{urlencode(query_params)}" if query_params else ""
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
            title=str(title),
            company=str(company_name) if company_name else None,
            location=_optional_string(summary.get("place")),
            employment_type=_optional_string(summary.get("employmentType")),
            source_website=self.source_name,
            source_url=detail_url,
            apply_url=detail_url,
            posting_date=_parse_datetime(summary.get("initialPublicationDate"))
            or _parse_datetime(summary.get("publicationDate")),
            external_id=source_job_id,
        )
        return SourceRecord(
            raw_payload=summary,
            normalized_job=normalized,
        )

    def _parse_detail(
        self,
        html: str,
        listing_record: SourceRecord,
    ) -> SourceRecord:
        detail = _job_posting_json_ld(html)
        detail_id = _property_value(detail.get("identifier"), "value")
        if detail_id and str(detail_id) != listing_record.source_job_id:
            raise ScrapeError(
                f"{self.source_name} detail identifier does not match "
                f"{listing_record.source_job_id}"
            )

        listing = listing_record.raw_payload
        addresses = _job_addresses(detail.get("jobLocation"))
        locations = _unique_strings(
            _format_address(address) for address in addresses
        )
        if not locations:
            locations = _listing_locations(listing.get("locations"))
        location = (
            "; ".join(locations)
            or listing_record.normalized_job.location
        )

        minimum, maximum, currency, period = _salary(
            detail.get("baseSalary")
        )
        salary = _salary_text(
            minimum,
            maximum,
            currency,
            period,
        )
        description_html = _optional_string(detail.get("description"))
        description = _html_text(description_html)
        requirements = _joined_string(
            detail.get("qualifications")
        ) or _description_section(description_html)
        employment_type = _joined_string(detail.get("employmentType"))
        languages = _string_list(
            listing.get("languageSkills"),
            dict_keys=("name", "language", "languageCode", "label"),
        )
        remote_type = _remote_type(detail.get("jobLocationType"))
        fallback_apply_url = listing_record.normalized_job.apply_url
        apply_url = _apply_url(detail) or (
            str(fallback_apply_url) if fallback_apply_url else None
        )
        organization = detail.get("hiringOrganization")
        detail_company = (
            _optional_string(organization.get("name"))
            if isinstance(organization, dict)
            else None
        )

        raw_payload = {
            "listing": listing,
            "detail": {
                "json_ld": detail,
            },
        }
        normalized_data = listing_record.normalized_job.model_dump()
        normalized_data.update(
            {
                "apply_url": apply_url,
                "title": _optional_string(detail.get("title"))
                or listing_record.normalized_job.title,
                "company": listing_record.normalized_job.company
                or detail_company,
                "location": location,
                "description": description,
                "requirements": requirements,
                "employment_type": employment_type
                or listing_record.normalized_job.employment_type,
                "remote_type": remote_type,
                "salary": salary,
                "required_languages": languages,
                "posting_date": _parse_datetime(
                    listing.get("initialPublicationDate")
                )
                or _parse_datetime(detail.get("datePosted"))
                or listing_record.normalized_job.posting_date,
            }
        )
        normalized = NormalizedJob.model_validate(normalized_data)
        return SourceRecord(
            raw_payload=raw_payload,
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


def _optional_string(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _job_posting_json_ld(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            value = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = value if isinstance(value, list) else [value]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            graph = candidate.get("@graph")
            graph_candidates = graph if isinstance(graph, list) else [candidate]
            for graph_candidate in graph_candidates:
                if not isinstance(graph_candidate, dict):
                    continue
                schema_type = graph_candidate.get("@type")
                schema_types = (
                    schema_type
                    if isinstance(schema_type, list)
                    else [schema_type]
                )
                if "JobPosting" in schema_types:
                    return graph_candidate
    raise ScrapeError("JobCloud detail JobPosting JSON-LD is missing")


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _property_value(value: object, key: str) -> str | None:
    if not isinstance(value, dict):
        return None
    return _optional_string(value.get(key))


def _job_addresses(value: object) -> list[dict[str, Any]]:
    locations = value if isinstance(value, list) else [value]
    return [
        address
        for location in locations
        if isinstance(location, dict)
        and isinstance((address := location.get("address")), dict)
    ]


def _format_address(address: dict[str, Any]) -> str | None:
    street = _optional_string(address.get("streetAddress"))
    postal_code = _optional_string(address.get("postalCode"))
    locality = _optional_string(address.get("addressLocality"))
    region = _optional_string(address.get("addressRegion"))
    country = _optional_string(address.get("addressCountry"))
    postal_locality = " ".join(
        part for part in (postal_code, locality or region) if part
    )
    distinct_region = region if locality and region != locality else None
    return ", ".join(
        part
        for part in (street, postal_locality, distinct_region, country)
        if part
    ) or None


def _listing_locations(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return _unique_strings(
        _format_address(
            {
                "streetAddress": location.get("street"),
                "postalCode": location.get("postalCode"),
                "addressLocality": location.get("city")
                or location.get("place"),
                "addressRegion": location.get("cantonCode"),
                "addressCountry": location.get("countryCode"),
            }
        )
        for location in value
        if isinstance(location, dict)
    )


def _salary(
    value: object,
) -> tuple[int | float | None, int | float | None, str | None, str | None]:
    salary = _mapping(value)
    quantitative = _mapping(salary.get("value"))
    exact = _number(quantitative.get("value"))
    minimum = _number(quantitative.get("minValue"))
    maximum = _number(quantitative.get("maxValue"))
    if exact is not None:
        minimum = minimum if minimum is not None else exact
        maximum = maximum if maximum is not None else exact
    currency = _optional_string(salary.get("currency"))
    period = _optional_string(quantitative.get("unitText"))
    return minimum, maximum, currency, period


def _number(value: object) -> int | float | None:
    return (
        value
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else None
    )


def _salary_text(
    minimum: int | float | None,
    maximum: int | float | None,
    currency: str | None,
    period: str | None,
) -> str | None:
    if minimum is None and maximum is None:
        return None
    amount = (
        f"{minimum:g}–{maximum:g}"
        if minimum is not None
        and maximum is not None
        and minimum != maximum
        else f"{minimum if minimum is not None else maximum:g}"
    )
    prefix = f"{currency} " if currency else ""
    suffix = f" per {period.lower()}" if period else ""
    return f"{prefix}{amount}{suffix}"


def _html_text(value: str | None) -> str | None:
    if not value:
        return None
    text = BeautifulSoup(value, "html.parser").get_text("\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines) or None


_REQUIREMENT_HEADINGS = {
    "about you",
    "qualifications",
    "requirements",
    "skills",
    "what you bring",
    "your profile",
    "anforderungen",
    "das bringen sie mit",
    "das bringst du mit",
    "dein profil",
    "ihr profil",
    "profil",
    "qualifikationen",
    "competences",
    "compétences",
    "exigences",
    "profil recherche",
    "profil recherché",
    "votre profil",
    "competenze",
    "il tuo profilo",
    "profilo",
    "requisiti",
}
_SECTION_HEADINGS = _REQUIREMENT_HEADINGS | {
    "responsibilities",
    "tasks",
    "your responsibilities",
    "your role",
    "your tasks",
    "your mission",
    "aufgaben",
    "deine aufgaben",
    "deine rolle bei uns",
    "ihr wirkungsbereich",
    "ihre aufgaben",
    "mission",
    "missions",
    "responsabilites",
    "responsabilités",
    "vos missions",
    "votre mission",
    "compiti",
    "il tuo ruolo",
    "mansioni",
    "responsabilita",
    "responsabilità",
}


def _description_section(description_html: str | None) -> str | None:
    if not description_html:
        return None
    soup = BeautifulSoup(description_html, "html.parser")
    for heading in soup.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "strong", "b"]
    ):
        if (
            _normalized_heading(heading.get_text(" ", strip=True))
            not in _REQUIREMENT_HEADINGS
        ):
            continue
        anchor = heading
        if (
            heading.name in {"strong", "b"}
            and heading.parent
            and heading.parent.name in {"p", "div"}
            and heading.parent.get_text(" ", strip=True)
            == heading.get_text(" ", strip=True)
        ):
            anchor = heading.parent
        parts: list[str] = []
        for sibling in anchor.next_siblings:
            if _starts_description_section(sibling):
                break
            if not hasattr(sibling, "get_text"):
                text = str(sibling).strip()
            else:
                text = sibling.get_text(" ", strip=True)
            if text:
                parts.append(text)
        return "\n".join(parts) or None
    return None


def _starts_description_section(value: object) -> bool:
    name = getattr(value, "name", None)
    if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return True
    candidates = []
    if name in {"strong", "b"}:
        candidates.append(value)
    elif hasattr(value, "find_all"):
        candidates.extend(value.find_all(["strong", "b"], recursive=False))
    return any(
        _normalized_heading(candidate.get_text(" ", strip=True))
        in _SECTION_HEADINGS
        for candidate in candidates
    )


def _normalized_heading(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" :.-").casefold()


def _joined_string(value: object) -> str | None:
    if isinstance(value, list):
        values = _unique_strings(_optional_string(item) for item in value)
        return ", ".join(values) or None
    return _optional_string(value)


def _string_list(
    value: object,
    *,
    dict_keys: tuple[str, ...] = ("name", "value", "label"),
) -> list[str]:
    values = value if isinstance(value, list) else [value]
    strings: list[str | None] = []
    for item in values:
        if isinstance(item, dict):
            strings.append(
                next(
                    (
                        text
                        for key in dict_keys
                        if (text := _optional_string(item.get(key)))
                    ),
                    None,
                )
            )
        else:
            strings.append(_optional_string(item))
    return _unique_strings(strings)


def _unique_strings(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _remote_type(value: object) -> str | None:
    values = value if isinstance(value, list) else [value]
    normalized = {
        str(item).strip().casefold()
        for item in values
        if item not in (None, "")
    }
    if normalized & {"telecommute", "remote"}:
        return "remote"
    return None


def _apply_url(detail: dict[str, Any]) -> str | None:
    action = _mapping(detail.get("potentialAction"))
    target = action.get("target")
    targets = target if isinstance(target, list) else [target]
    for candidate in targets:
        if isinstance(candidate, dict):
            url = _valid_http_url(candidate.get("urlTemplate"))
            if url:
                return url
        else:
            url = _valid_http_url(candidate)
            if url:
                return url
    return None


def _valid_http_url(value: object) -> str | None:
    text = _optional_string(value)
    return text if text and re.match(r"^https?://[^/]+", text, re.I) else None
