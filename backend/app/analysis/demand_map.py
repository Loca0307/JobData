from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from app.analysis.models import (
    DemandMapPoint,
    DemandMapResult,
    IndexedJobLocation,
)

_WORD_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
_MAX_INDEX_TERMS = 12


@dataclass(frozen=True)
class SwissLocation:
    name: str
    latitude: float
    longitude: float
    aliases: tuple[str, ...] = ()


# Common employment centres are resolved locally before the geocoding fallback.
_SWISS_LOCATIONS = (
    SwissLocation("Zürich", 47.3769, 8.5417, ("zurich",)),
    SwissLocation("Geneva", 46.2044, 6.1432, ("geneve", "genf")),
    SwissLocation("Basel", 47.5596, 7.5886),
    SwissLocation("Lausanne", 46.5197, 6.6323),
    SwissLocation("Bern", 46.9480, 7.4474, ("berne",)),
    SwissLocation("Winterthur", 47.4988, 8.7241),
    SwissLocation("Luzern", 47.0502, 8.3093, ("lucerne",)),
    SwissLocation("St. Gallen", 47.4245, 9.3767, ("st gallen", "sankt gallen")),
    SwissLocation("Lugano", 46.0037, 8.9511),
    SwissLocation(
        "Biel/Bienne",
        47.1368,
        7.2468,
        ("biel", "bienne", "bielbienne"),
    ),
    SwissLocation("Thun", 46.7580, 7.6280),
    SwissLocation("Fribourg", 46.8065, 7.1619, ("freiburg",)),
    SwissLocation("La Chaux-de-Fonds", 47.1035, 6.8328),
    SwissLocation("Schaffhausen", 47.6969, 8.6350),
    SwissLocation("Chur", 46.8508, 9.5320, ("coire",)),
    SwissLocation("Neuchâtel", 46.9896, 6.9293, ("neuchatel",)),
    SwissLocation("Sion", 46.2331, 7.3606, ("sitten",)),
    SwissLocation("Zug", 47.1662, 8.5155),
    SwissLocation("Aarau", 47.3904, 8.0457),
    SwissLocation("Solothurn", 47.2088, 7.5323),
    SwissLocation("Bellinzona", 46.1950, 9.0222),
    SwissLocation("Baden", 47.4738, 8.3072),
    SwissLocation("Domat/Ems", 46.8347, 9.4503),
    SwissLocation("Grand-Lancy", 46.1780, 6.1220),
    SwissLocation("Degersheim", 47.3740, 9.1970),
    SwissLocation("Alpnach", 46.9420, 8.2730),
)


def title_terms(value: str) -> tuple[str, ...]:
    """Return bounded, normalized title words used as DynamoDB query keys."""
    terms = {
        normalize_search_text(term)
        for term in _WORD_PATTERN.findall(value)
        if len(term) >= 2
    }
    return tuple(sorted(terms, key=lambda term: (-len(term), term)))[:_MAX_INDEX_TERMS]


def build_demand_map(
    role: str,
    jobs: Iterable[IndexedJobLocation],
    *,
    is_truncated: bool = False,
    location_resolver: Callable[[str], SwissLocation | None] | None = None,
) -> DemandMapResult:
    """Aggregate matching indexed jobs into recognized Swiss map points."""
    required_terms = title_terms(role)
    location_counts: Counter[SwissLocation] = Counter()
    matching_jobs = 0
    unmapped_jobs = 0
    resolver = location_resolver or resolve_swiss_location

    for job in jobs:
        if not _role_matches_title(
            required_terms,
            title_terms(job.search_title or job.title),
        ):
            continue
        matching_jobs += 1
        location = resolver(job.location)
        if location is None:
            unmapped_jobs += 1
            continue
        location_counts[location] += 1

    points = [
        DemandMapPoint(
            name=location.name,
            latitude=location.latitude,
            longitude=location.longitude,
            job_count=count,
        )
        for location, count in sorted(
            location_counts.items(),
            key=lambda item: (-item[1], item[0].name),
        )
    ]
    mapped_jobs = sum(point.job_count for point in points)
    return DemandMapResult(
        role=role.strip(),
        matching_jobs=matching_jobs,
        mapped_jobs=mapped_jobs,
        unmapped_jobs=unmapped_jobs,
        is_truncated=is_truncated,
        points=points,
    )


def matches_role(role: str, title: str) -> bool:
    """Return whether every requested role word matches a title word."""
    return _role_matches_title(title_terms(role), title_terms(title))


def resolve_swiss_location(value: str) -> SwissLocation | None:
    """Match common free-text job locations to a known Swiss city."""
    normalized = f" {normalize_search_text(value)} "
    for location in _SWISS_LOCATIONS:
        names = (location.name, *location.aliases)
        if any(
            f" {normalize_search_text(name)} " in normalized for name in names
        ):
            return location
    return None


def recover_location(raw_payload: dict[str, Any]) -> str | None:
    """Recover a location retained by older records before normalization."""
    listing = raw_payload.get("listing")
    listing = listing if isinstance(listing, dict) else raw_payload
    place = listing.get("place")
    if isinstance(place, str) and place.strip():
        return place.strip()

    detail = raw_payload.get("detail")
    if not isinstance(detail, dict):
        return None

    # JobCloud detail payloads use schema.org JobPosting addresses.
    job_location = detail.get("jobLocation")
    if isinstance(job_location, list):
        job_location = next(
            (item for item in job_location if isinstance(item, dict)),
            {},
        )
    if isinstance(job_location, dict):
        address = job_location.get("address")
        if isinstance(address, dict):
            location = _join_location_fields(
                address,
                ("postalCode", "addressLocality", "addressRegion"),
            )
            if location:
                return location

    # SwissDevJobs detail payloads keep these fields at the top level.
    return _join_location_fields(
        detail,
        ("address", "postalCode", "actualCity"),
    )


def normalize_search_text(value: str) -> str:
    """Normalize user queries, job titles, and aliases identically."""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    ascii_like = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(_WORD_PATTERN.findall(ascii_like))


def _join_location_fields(
    payload: dict[str, Any],
    fields: tuple[str, ...],
) -> str | None:
    values = [
        str(payload[field]).strip()
        for field in fields
        if payload.get(field)
    ]
    return ", ".join(values) or None


def _role_matches_title(
    required_terms: tuple[str, ...],
    job_terms: tuple[str, ...],
) -> bool:
    return all(
        any(job_term.startswith(required_term) for job_term in job_terms)
        for required_term in required_terms
    )
