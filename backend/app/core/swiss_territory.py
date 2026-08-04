from __future__ import annotations

import re
import unicodedata

SWISS_COUNTRY_CODE = "CH"

_SWISS_COUNTRY_NAMES = {
    "ch",
    "che",
    "schweiz",
    "suisse",
    "svizzera",
    "svizra",
    "switzerland",
}

# ATS location fields are often only a city or canton, without a country code.
# This deliberately small reviewed list covers Switzerland's cantons and its
# main employment centres. Unknown locations are rejected by ingestion rather
# than guessed, so adding a place here is an explicit coverage decision.
_SWISS_PLACE_NAMES = {
    "aargau",
    "aarau",
    "alpnach",
    "appenzell ausserrhoden",
    "appenzell innerrhoden",
    "baden",
    "basel",
    "basel landschaft",
    "basel stadt",
    "bellinzona",
    "bern",
    "berne",
    "biel",
    "bienne",
    "chur",
    "coire",
    "degersheim",
    "domat ems",
    "fribourg",
    "freiburg",
    "geneva",
    "geneve",
    "genf",
    "glarus",
    "graubunden",
    "grand lancy",
    "jura",
    "la chaux de fonds",
    "lausanne",
    "lucerne",
    "lugano",
    "luzern",
    "neuchatel",
    "nidwalden",
    "obwalden",
    "schaffhausen",
    "schwyz",
    "sion",
    "sitten",
    "solothurn",
    "st gallen",
    "sankt gallen",
    "thun",
    "thurgau",
    "ticino",
    "uri",
    "valais",
    "vaud",
    "winterthur",
    "zug",
    "zurich",
}


def country_code_from_evidence(
    location: str | None,
    *,
    structured_country: object | None = None,
) -> str | None:
    """Return an ISO country code without guessing an unknown ATS location.

    Structured country data takes precedence. If a source publishes a country
    value that is not a recognizable ISO code or Swiss name, the record stays
    unclassified instead of falling back to a possibly conflicting city name.
    """
    if structured_country not in (None, ""):
        return normalize_country_code(structured_country)
    return infer_swiss_country_code(location)


def normalize_country_code(value: object) -> str | None:
    """Normalize a structured two-letter code or a Swiss country name."""
    text = str(value).strip()
    normalized = _normalize_words(text)
    if normalized in _SWISS_COUNTRY_NAMES:
        return SWISS_COUNTRY_CODE
    if len(text) == 2 and text.isalpha():
        return text.upper()
    return None


def infer_swiss_country_code(location: str | None) -> str | None:
    """Identify high-confidence Swiss country or place evidence in text."""
    normalized = _normalize_words(location or "")
    if not normalized:
        return None
    padded = f" {normalized} "
    evidence = _SWISS_COUNTRY_NAMES | _SWISS_PLACE_NAMES
    if any(f" {name} " in padded for name in evidence):
        return SWISS_COUNTRY_CODE
    return None


def _normalize_words(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[^\W_]+", without_accents, re.UNICODE))
