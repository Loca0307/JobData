from __future__ import annotations

from app.core.settings import Settings, get_settings
from app.scrapers.base import BaseJobScraper
from app.scrapers.jobcloud import JobsChScraper, JobupChScraper
from app.scrapers.swissdevjobs import SwissDevJobsScraper

SOURCE_TYPES: dict[str, type[BaseJobScraper]] = {
    "jobs.ch": JobsChScraper,
    "jobup.ch": JobupChScraper,
    "swissdevjobs.ch": SwissDevJobsScraper,
}


def get_configured_scrapers(
    settings: Settings | None = None,
) -> list[BaseJobScraper]:
    """Build every enabled adapter registered by the application."""
    settings = settings or get_settings()
    unknown = set(settings.enabled_source_names) - SOURCE_TYPES.keys()
    if unknown:
        raise ValueError(
            "Unknown SCRAPER_ENABLED_SOURCES values: "
            + ", ".join(sorted(unknown))
        )
    return [
        scraper_type(settings)
        for name, scraper_type in SOURCE_TYPES.items()
        if name in settings.enabled_source_names
    ]


def get_all_source_names() -> tuple[str, ...]:
    return tuple(SOURCE_TYPES)
