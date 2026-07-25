import pytest

from app.core.settings import Settings
from app.scrapers.base import BaseJobScraper
from app.scrapers.registry import (
    get_all_source_names,
    get_blocked_sources,
    get_configured_scrapers,
)


def test_registry_exposes_exactly_the_implemented_sources():
    assert get_all_source_names() == (
        "jobs.ch",
        "jobup.ch",
        "swissdevjobs.ch",
    )


def test_sources_are_disabled_until_operator_confirms_permission():
    settings = Settings()

    assert get_configured_scrapers(settings) == []
    assert set(get_blocked_sources(settings)) == set(get_all_source_names())


def test_authorized_sources_are_configuration_driven():
    settings = Settings(
        SCRAPER_ENABLED_SOURCES="jobs.ch,swissdevjobs.ch",
        JOBS_CH_SCRAPING_AUTHORIZED=True,
        SWISSDEVJOBS_CH_SCRAPING_AUTHORIZED=True,
    )

    scrapers = get_configured_scrapers(settings)

    assert [scraper.source_name for scraper in scrapers] == [
        "jobs.ch",
        "swissdevjobs.ch",
    ]
    assert all(isinstance(scraper, BaseJobScraper) for scraper in scrapers)


def test_unknown_source_configuration_fails_loudly():
    settings = Settings(SCRAPER_ENABLED_SOURCES="jobs.ch,typo.example")

    with pytest.raises(ValueError, match="typo.example"):
        get_configured_scrapers(settings)
