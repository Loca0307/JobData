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


SOURCE_REGISTRY = (
    SourceRegistration(
        "jobs.ch",
        lambda settings: JobsChScraper(settings),
    ),
    SourceRegistration(
        "jobup.ch",
        lambda settings: JobupChScraper(settings),
    ),
    SourceRegistration(
        "swissdevjobs.ch",
        lambda settings: SwissDevJobsScraper(settings),
    ),
)


def get_configured_scrapers(
    settings: Settings | None = None,
) -> list[BaseJobScraper]:
    """Build every enabled adapter registered by the application."""
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
    ]


def get_all_source_names() -> tuple[str, ...]:
    return tuple(registration.source_name for registration in SOURCE_REGISTRY)
