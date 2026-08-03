import json

import pytest

from app.core.settings import Settings
from app.scrapers.base import BaseJobScraper
from app.scrapers.registry import (
    get_all_source_names,
    get_configured_scrapers,
)


def test_registry_exposes_exactly_the_implemented_sources():
    assert get_all_source_names() == (
        "jobs.ch",
        "jobup.ch",
        "swissdevjobs.ch",
        "company:scandit",
        "company:on-running",
        "company:rivr",
        "company:swissborg",
    )


def test_all_catalogued_sources_are_enabled_by_default():
    settings = Settings()

    scrapers = get_configured_scrapers(settings)

    assert [scraper.source_name for scraper in scrapers] == list(
        get_all_source_names(settings)
    )


def test_enabled_sources_are_configuration_driven():
    settings = Settings(
        SCRAPER_ENABLED_SOURCES="jobs.ch,swissdevjobs.ch",
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


def test_registry_expands_enabled_company_targets(tmp_path):
    catalog_path = tmp_path / "companies.json"
    catalog_path.write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "id": "example-greenhouse",
                        "company_name": "Example AG",
                        "careers_url": "https://example.test/careers",
                        "ats": "greenhouse",
                        "board_token": "example",
                    },
                    {
                        "id": "example-lever",
                        "company_name": "Example GmbH",
                        "careers_url": "https://example.test/jobs",
                        "ats": "lever",
                        "site": "example",
                        "region": "eu",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        SCRAPER_COMPANY_TARGETS_FILE=catalog_path,
        SCRAPER_ENABLED_SOURCES="jobs.ch,company:example-lever",
    )

    scrapers = get_configured_scrapers(settings)

    assert [scraper.source_name for scraper in scrapers] == [
        "jobs.ch",
        "company:example-lever",
    ]
    assert get_all_source_names(settings) == (
        "jobs.ch",
        "jobup.ch",
        "swissdevjobs.ch",
        "company:example-greenhouse",
        "company:example-lever",
    )


def test_unknown_enabled_company_target_fails_loudly(tmp_path):
    catalog_path = tmp_path / "companies.json"
    catalog_path.write_text('{"targets": []}', encoding="utf-8")
    settings = Settings(
        SCRAPER_COMPANY_TARGETS_FILE=catalog_path,
        SCRAPER_ENABLED_SOURCES="company:missing",
    )

    with pytest.raises(ValueError, match="company:missing"):
        get_configured_scrapers(settings)
