import json
from pathlib import Path

import pytest

from app.core.settings import Settings
from app.scrapers.ats.lever import PAGE_SIZE, LeverScraper
from app.scrapers.ats.targets import LeverTarget
from app.scrapers.base import ScrapeError

FIXTURES = Path(__file__).parent / "fixtures"


class FakeClient:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.urls: list[str] = []

    def get_text(self, url: str) -> str:
        self.urls.append(url)
        return self.pages[url]

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        pass


def target(region: str = "eu") -> LeverTarget:
    return LeverTarget(
        id="example-lever",
        company_name="Example Lever AG",
        careers_url="https://example.test/jobs",
        ats="lever",
        site="example",
        region=region,
    )


def posting(source_id: str) -> dict[str, object]:
    return {
        "id": source_id,
        "text": f"Job {source_id}",
        "hostedUrl": f"https://jobs.lever.co/example/{source_id}",
    }


def test_lever_normalizes_fields_and_preserves_raw_payload():
    scraper = LeverScraper(target())
    body = (FIXTURES / "lever_jobs.json").read_text()
    client = FakeClient({scraper._page_url(0): body})
    scraper = LeverScraper(target(), client_factory=lambda: client)

    records = list(scraper.scrape_all())

    assert [record.source_job_id for record in records] == [
        "lever-1",
        "lever-2",
    ]
    job = records[0].normalized_job
    assert records[0].source_name == "company:example-lever"
    assert job.company == "Example Lever AG"
    assert job.location == "Zürich, Remote - Switzerland"
    assert job.description == "Build and operate the platform."
    assert job.requirements == "Python\nAWS"
    assert job.employment_type == "Full-time"
    assert job.remote_type == "hybrid"
    assert job.salary == "CHF 120000–140000 per year"
    assert records[0].raw_payload["job"]["country"] == "CH"
    assert records[0].raw_payload["target"]["region"] == "eu"


def test_lever_builds_global_and_eu_urls():
    assert LeverScraper(target("global"))._page_url(0).startswith(
        "https://api.lever.co/v0/postings/example?"
    )
    assert LeverScraper(target("eu"))._page_url(1).startswith(
        "https://api.eu.lever.co/v0/postings/example?"
    )
    assert "skip=100" in LeverScraper(target())._page_url(1)


def test_lever_paginates_and_deduplicates_overlapping_ids():
    scraper = LeverScraper(target())
    first_page = [posting(str(index)) for index in range(PAGE_SIZE)]
    second_page = [posting("99"), posting("100")]
    client = FakeClient(
        {
            scraper._page_url(0): json.dumps(first_page),
            scraper._page_url(1): json.dumps(second_page),
        }
    )
    scraper = LeverScraper(target(), client_factory=lambda: client)

    records = list(scraper.scrape_all())

    assert len(records) == 101
    assert records[-1].source_job_id == "100"


def test_lever_repeated_page_fails_loudly():
    scraper = LeverScraper(target())
    page = json.dumps([posting(str(index)) for index in range(PAGE_SIZE)])
    client = FakeClient(
        {scraper._page_url(0): page, scraper._page_url(1): page}
    )

    with pytest.raises(ScrapeError, match="repeated page"):
        list(LeverScraper(target(), client_factory=lambda: client).scrape_all())


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("not-json", "malformed"),
        ('{"jobs": []}', "must be a list"),
        ("[1, 2]", "contain no objects"),
    ],
)
def test_lever_rejects_malformed_payloads(body, message):
    with pytest.raises(ScrapeError, match=message):
        LeverScraper(target())._parse_page(body)


def test_lever_page_limit_fails_loudly():
    scraper = LeverScraper(target(), settings=Settings(SCRAPER_MAX_PAGES=1))
    page = json.dumps([posting(str(index)) for index in range(PAGE_SIZE)])
    client = FakeClient({scraper._page_url(0): page})

    with pytest.raises(ScrapeError, match="SCRAPER_MAX_PAGES"):
        list(
            LeverScraper(
                target(),
                settings=Settings(SCRAPER_MAX_PAGES=1),
                client_factory=lambda: client,
            ).scrape_all()
        )
