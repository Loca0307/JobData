from __future__ import annotations

from app.core.settings import Settings, get_settings
from app.scrapers.ats.greenhouse import GreenhouseScraper
from app.scrapers.ats.lever import LeverScraper
from app.scrapers.ats.targets import (
    GreenhouseTarget,
    LeverTarget,
    load_company_target_catalog,
)
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
    catalog = load_company_target_catalog(settings.scraper_company_targets_file)
    company_targets = {target.source_name: target for target in catalog.targets}
    known_sources = set(SOURCE_TYPES) | company_targets.keys()
    unknown = set(settings.enabled_source_names) - known_sources
    if unknown:
        raise ValueError(
            "Unknown SCRAPER_ENABLED_SOURCES values: "
            + ", ".join(sorted(unknown))
        )
    scrapers: list[BaseJobScraper] = [
        scraper_type(settings)
        for name, scraper_type in SOURCE_TYPES.items()
        if name in settings.enabled_source_names
    ]
    for target in catalog.targets:
        if target.source_name not in settings.enabled_source_names:
            continue
        if isinstance(target, GreenhouseTarget):
            scrapers.append(GreenhouseScraper(target, settings))
        elif isinstance(target, LeverTarget):
            scrapers.append(LeverScraper(target, settings))
    return scrapers


def get_all_source_names(settings: Settings | None = None) -> tuple[str, ...]:
    settings = settings or get_settings()
    catalog = load_company_target_catalog(settings.scraper_company_targets_file)
    return (*SOURCE_TYPES, *(target.source_name for target in catalog.targets))
