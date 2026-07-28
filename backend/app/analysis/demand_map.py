from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

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


# This compact gazetteer covers the main Swiss employment centres without
# introducing a geocoding service, API key, or network dependency.
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
    SwissLocation("Biel/Bienne", 47.1368, 7.2468, ("biel", "bienne")),
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
)


def title_terms(value: str) -> tuple[str, ...]:
    """Return bounded, normalized title words used as DynamoDB query keys."""
    terms = {
        _normalize_text(term)
        for term in _WORD_PATTERN.findall(value)
        if len(term) >= 2
    }
    return tuple(sorted(terms, key=lambda term: (-len(term), term)))[:_MAX_INDEX_TERMS]


def build_demand_map(
    role: str,
    jobs: Iterable[IndexedJobLocation],
    *,
    is_truncated: bool = False,
) -> DemandMapResult:
    """Aggregate matching indexed jobs into recognized Swiss map points."""
    required_terms = set(title_terms(role))
    location_counts: Counter[SwissLocation] = Counter()
    matching_jobs = 0
    unmapped_jobs = 0

    for job in jobs:
        if not required_terms.issubset(title_terms(job.title)):
            continue
        matching_jobs += 1
        location = resolve_swiss_location(job.location)
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


def resolve_swiss_location(value: str) -> SwissLocation | None:
    """Match common free-text job locations to a known Swiss city."""
    normalized = f" {_normalize_text(value)} "
    for location in _SWISS_LOCATIONS:
        names = (location.name, *location.aliases)
        if any(f" {_normalize_text(name)} " in normalized for name in names):
            return location
    return None


def _normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    ascii_like = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(_WORD_PATTERN.findall(ascii_like))
