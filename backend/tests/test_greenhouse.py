from pathlib import Path

import pytest

from app.scrapers.ats.greenhouse import GreenhouseScraper
from app.scrapers.ats.targets import GreenhouseTarget
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


def target() -> GreenhouseTarget:
    return GreenhouseTarget(
        id="example-greenhouse",
        company_name="Example Greenhouse AG",
        careers_url="https://example.test/careers",
        ats="greenhouse",
        board_token="example",
    )


def test_greenhouse_normalizes_deduplicates_and_preserves_raw_payload():
    body = (FIXTURES / "greenhouse_jobs.json").read_text()
    scraper = GreenhouseScraper(target())
    client = FakeClient({scraper.jobs_url: body})
    scraper = GreenhouseScraper(target(), client_factory=lambda: client)

    records = list(scraper.scrape_all())

    assert len(records) == 1
    assert client.urls == [scraper.jobs_url]
    job = records[0].normalized_job
    assert records[0].source_name == "company:example-greenhouse"
    assert records[0].source_job_id == "101"
    assert job.title == "Data Engineer"
    assert job.company == "Example Greenhouse AG"
    assert job.location == "Zürich, Switzerland"
    assert job.description == "Build reliable data pipelines."
    assert job.posting_date is None
    assert str(job.apply_url) == (
        "https://boards.greenhouse.io/example/jobs/101"
    )
    assert records[0].raw_payload["target"]["board_token"] == "example"
    assert records[0].raw_payload["job"]["metadata"][0]["value"] == "Data"


def test_greenhouse_accepts_empty_or_prospect_only_boards():
    scraper = GreenhouseScraper(target())

    assert scraper._parse_jobs('{"jobs": []}') == []
    assert scraper._parse_jobs(
        '{"jobs": [{"id": 1, "internal_job_id": null}]}'
    ) == []


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("not-json", "malformed"),
        ('{"jobs": {}}', "must be a list"),
        ('{"jobs": [{"internal_job_id": 2}]}', "no usable jobs"),
    ],
)
def test_greenhouse_rejects_malformed_or_unusable_payloads(body, message):
    with pytest.raises(ScrapeError, match=message):
        GreenhouseScraper(target())._parse_jobs(body)
