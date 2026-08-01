from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from app.analysis.demand_map import normalize_search_text

_CATALOG_PATH = Path(__file__).parent / "data" / "job_title_aliases.json"
_EXPECTED_LANGUAGES = {"de", "en", "fr", "it"}
_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class JobTitleAliasGroup:
    """One reviewed job family and the English terms added for searching."""

    key: str
    english_terms: tuple[str, ...]
    aliases: tuple[str, ...]


@cache
def load_title_alias_groups(
    path: Path = _CATALOG_PATH,
) -> tuple[JobTitleAliasGroup, ...]:
    """Load and validate the small bundled catalog once per process."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Job-title alias catalog must be a JSON list")

    groups: list[JobTitleAliasGroup] = []
    seen_keys: set[str] = set()
    alias_owners: dict[str, str] = {}
    for raw_group in payload:
        if not isinstance(raw_group, dict):
            raise ValueError("Every job-title alias group must be an object")
        unexpected = set(raw_group) - {"key", "english_terms", "aliases"}
        if unexpected:
            raise ValueError(f"Unexpected alias fields: {sorted(unexpected)}")

        key = raw_group.get("key")
        if not isinstance(key, str) or not _KEY_PATTERN.fullmatch(key):
            raise ValueError(f"Invalid job-title alias key: {key!r}")
        if key in seen_keys:
            raise ValueError(f"Duplicate job-title alias key: {key}")
        seen_keys.add(key)

        english_terms = _string_list(raw_group.get("english_terms"), key)
        aliases_by_language = raw_group.get("aliases")
        if not isinstance(aliases_by_language, dict):
            raise ValueError(f"Aliases for {key} must be grouped by language")
        if set(aliases_by_language) != _EXPECTED_LANGUAGES:
            raise ValueError(
                f"Aliases for {key} must contain exactly de, en, fr, and it"
            )

        normalized_aliases: set[str] = set()
        for language in sorted(_EXPECTED_LANGUAGES):
            for alias in _string_list(aliases_by_language[language], key):
                normalized = normalize_search_text(alias)
                if not normalized:
                    raise ValueError(f"Alias for {key} normalizes to empty text")
                owner = alias_owners.get(normalized)
                if owner is not None and owner != key:
                    raise ValueError(
                        f"Alias {alias!r} is shared by {owner} and {key}"
                    )
                alias_owners[normalized] = key
                normalized_aliases.add(normalized)

        groups.append(
            JobTitleAliasGroup(
                key=key,
                english_terms=tuple(english_terms),
                aliases=tuple(sorted(normalized_aliases)),
            )
        )
    return tuple(groups)


def expand_search_title(title: str) -> str:
    """Append English terms for whole aliases found in the original title."""
    normalized_title = f" {normalize_search_text(title)} "
    matched_terms: list[str] = []
    for group in load_title_alias_groups():
        if any(f" {alias} " in normalized_title for alias in group.aliases):
            matched_terms.extend(group.english_terms)

    # Keep the source title first for literal fallback and provenance clarity.
    additions = " ".join(dict.fromkeys(matched_terms))
    return f"{title} {additions}" if additions else title


def _string_list(value: Any, group_key: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        raise ValueError(f"Alias values for {group_key} must be non-empty strings")
    return [item.strip() for item in value]
