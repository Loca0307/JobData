from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import httpx

from app.analysis.demand_map import SwissLocation, resolve_swiss_location

_GEO_ADMIN_SEARCH_URL = "https://api3.geo.admin.ch/rest/services/api/SearchServer"
_NON_CITY_LOCATIONS = {
    "remote",
    "schweiz",
    "suisse",
    "switzerland",
    "valais",
    "vaud",
}
_COUNTRY_PARTS = {"ch", "schweiz", "suisse", "svizzera", "switzerland"}
_POSTAL_CODE = re.compile(r"^\d{4}$")
_POSTAL_CITY = re.compile(r"^(\d{4})\s+(.+)$")


@lru_cache(maxsize=2_048)
def resolve_cached_swiss_location(value: str) -> SwissLocation | None:
    """Resolve each distinct city once and retain the coordinate in memory."""
    known_location = resolve_swiss_location(value)
    if known_location is not None:
        return known_location

    query = _geocoding_query(value)
    if query is None:
        return None
    search_text, city = query
    try:
        response = httpx.get(
            _GEO_ADMIN_SEARCH_URL,
            params={
                "searchText": search_text,
                "type": "locations",
                # Address and municipality indexes understand Swiss postal
                # addresses. The broader gazetteer produced unsafe fuzzy
                # matches such as a street resolving to a border marker.
                "origins": "address,zipcode,gg25",
                "limit": 1,
            },
            timeout=2,
        )
        response.raise_for_status()
        results = response.json().get("results", [])
    except (httpx.HTTPError, TypeError, ValueError):
        return None
    if not results:
        return None

    attributes = results[0].get("attrs", {})
    latitude = attributes.get("lat")
    longitude = attributes.get("lon")
    if not isinstance(latitude, (int, float)) or not isinstance(
        longitude,
        (int, float),
    ):
        return None
    if not (45.7 <= latitude <= 47.9 and 5.8 <= longitude <= 10.7):
        return None

    label = _display_name(city)
    return SwissLocation(
        name=html.unescape(label),
        latitude=float(latitude),
        longitude=float(longitude),
    )


def resolve_cached_swiss_locations(
    values: Iterable[str],
) -> dict[str, SwissLocation | None]:
    """Resolve distinct city strings concurrently; individual results are cached."""
    unique_values = tuple(dict.fromkeys(values))
    if not unique_values:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(unique_values))) as executor:
        locations = executor.map(resolve_cached_swiss_location, unique_values)
        return dict(zip(unique_values, locations, strict=True))


def _geocoding_query(value: str) -> tuple[str, str] | None:
    """Return a precise Swiss search query and its city display name."""
    parts = [part.strip() for part in value.split(",") if part.strip()]
    while parts and parts[-1].casefold() in _COUNTRY_PARTS:
        parts.pop()
    if not parts:
        return None

    search_parts = [parts[0]]
    city = parts[0]
    for index, part in enumerate(parts):
        if _POSTAL_CODE.fullmatch(part) and index + 1 < len(parts):
            city = parts[index + 1]
            # Keep a preceding street when present: GeoAdmin can then return
            # the exact address rather than an arbitrary point in the town.
            search_parts = parts[: index + 2]
            break
        postal_city = _POSTAL_CITY.fullmatch(part)
        if postal_city:
            city = postal_city.group(2)
            search_parts = parts[: index + 1]
            break

    city = city.strip()
    # Concatenated locations are ambiguous and can produce misleading fuzzy
    # matches, for example "ZürichBendern" resolving to central Zürich.
    if re.search(r"[a-zäöüéèà][A-ZÄÖÜ]", city):
        return None
    if city.casefold() in _NON_CITY_LOCATIONS:
        return None
    return (" ".join(search_parts), city) if city else None


def _display_name(city: str) -> str:
    name = re.sub(r"\s+\([A-Z]{2}\)$", "", city).strip()
    name = re.sub(r"\s+[A-Z]{2}$", "", name).strip()
    return name.title() if name.isupper() else name
