from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.core.settings import Settings, get_settings
from app.scrapers.base import BaseJobScraper
from app.scrapers.jobcloud import JobsChScraper, JobupChScraper
from app.scrapers.swissdevjobs import SwissDevJobsScraper


@dataclass(frozen=True)
class SourceRegistration:
    source_name: str
    factory: Callable[[Settings], BaseJobScraper]
    authorization_url: str


SOURCE_REGISTRY = (
    SourceRegistration(
        "jobs.ch",
        lambda settings: JobsChScraper(settings),
        "https://www.jobs.ch/en/terms/",
    ),
    SourceRegistration(
        "jobup.ch",
        lambda settings: JobupChScraper(settings),
        "https://www.jobs.ch/en/terms/",
    ),
    SourceRegistration(
        "swissdevjobs.ch",
        lambda settings: SwissDevJobsScraper(settings),
        "https://static.swissdevjobs.ch/documents/Terms-And-Conditions-2025.pdf",
    ),
)


def get_configured_scrapers(
    settings: Settings | None = None,
) -> list[BaseJobScraper]:
    """Build enabled adapters only after explicit operator authorization."""
    settings = settings or get_settings()
    unknown = set(settings.enabled_source_names) - {
        registration.source_name for registration in SOURCE_REGISTRY
    }
    if unknown:
        raise ValueError(
            "Unknown SCRAPER_ENABLED_SOURCES values: "
            + ", ".join(sorted(unknown))
        )
    return [
        registration.factory(settings)
        for registration in SOURCE_REGISTRY
        if registration.source_name in settings.enabled_source_names
        and settings.source_is_authorized(registration.source_name)
    ]


def get_blocked_sources(
    settings: Settings | None = None,
) -> dict[str, str]:
    settings = settings or get_settings()
    return {
        registration.source_name: registration.authorization_url
        for registration in SOURCE_REGISTRY
        if registration.source_name in settings.enabled_source_names
        and not settings.source_is_authorized(registration.source_name)
    }


def get_all_source_names() -> tuple[str, ...]:
    return tuple(registration.source_name for registration in SOURCE_REGISTRY)
