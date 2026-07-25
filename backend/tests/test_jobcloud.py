import json
from pathlib import Path

import pytest

from app.core.settings import Settings
from app.scrapers.base import ScrapeError
from app.scrapers.jobcloud import JobsChScraper, JobupChScraper

FIXTURES = Path(__file__).parent / "fixtures"


class FakeClient:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.urls: list[str] = []

    def get_text(self, url: str) -> str:
        self.urls.append(url)
        return self.pages[url]

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *_: object) -> None:
        pass


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_jobs_ch_scrapes_until_empty_without_filters_and_preserves_raw_payload():
    pages = {
        "https://www.jobs.ch/en/vacancies/": fixture("jobcloud_page_1.html"),
        "https://www.jobs.ch/en/vacancies/?page=2": fixture(
            "jobcloud_page_2.html"
        ),
        "https://www.jobs.ch/en/vacancies/?page=3": fixture(
            "jobcloud_empty.html"
        ),
    }
    client = FakeClient(pages)
    scraper = JobsChScraper(client_factory=lambda: client)

    records = list(scraper.scrape_all())

    assert [record.source_job_id for record in records] == [
        "job-1",
        "job-2",
        "job-3",
    ]
    assert client.urls == list(pages)
    assert records[0].normalized_job.title == "Data Engineer"
    assert records[0].normalized_job.company_name == "Example AG"
    assert records[0].normalized_job.raw_location_text == "Zürich"
    assert records[0].normalized_job.posted_at.isoformat() == (
        "2026-07-10T08:30:00+00:00"
    )
    assert records[0].raw_payload["extraEvidence"] == {"keep": True}
    assert records[1].normalized_job.posted_at is None


def test_repeated_page_terminates_collection_without_emitting_duplicates():
    repeated = fixture("jobcloud_page_1.html")
    pages = {
        "https://www.jobs.ch/en/vacancies/": repeated,
        "https://www.jobs.ch/en/vacancies/?page=2": repeated,
    }
    client = FakeClient(pages)

    records = list(JobsChScraper(client_factory=lambda: client).scrape_all())

    assert [record.source_job_id for record in records] == ["job-1", "job-2"]
    assert len(client.urls) == 2


def test_jobup_uses_its_unfiltered_listing_and_detail_paths():
    scraper = JobupChScraper()
    state = {
        "vacancy": {
            "results": {
                "main": {
                    "results": [{"id": "abc", "title": "Comptable"}]
                }
            }
        }
    }

    records = scraper._parse_listing(f"__INIT__ = {json.dumps(state)}")

    assert scraper._listing_url(1) == "https://www.jobup.ch/en/jobs/"
    assert str(records[0].normalized_job.source_url) == (
        "https://www.jobup.ch/en/jobs/detail/abc/"
    )


@pytest.mark.parametrize(
    ("html", "message"),
    [
        ("<html></html>", "marker is missing"),
        ("__INIT__ = {bad", "payload is malformed"),
        (
            '__INIT__ = {"vacancy":{"results":{"main":{"results":{}}}}}',
            "invalid shape",
        ),
        (
            '__INIT__ = {"vacancy":{"results":{"main":{"results":[{}]}}}}',
            "schema may have changed",
        ),
    ],
)
def test_jobcloud_rejects_untrustworthy_listing_payloads(html: str, message: str):
    with pytest.raises(ScrapeError, match=message):
        JobsChScraper()._parse_listing(html)


def test_page_safety_limit_fails_loudly_instead_of_claiming_completeness():
    page = fixture("jobcloud_page_1.html")
    client = FakeClient({"https://www.jobs.ch/en/vacancies/": page})
    settings = Settings(SCRAPER_MAX_PAGES=1)

    with pytest.raises(ScrapeError, match="before exhaustion"):
        list(
            JobsChScraper(
                settings=settings, client_factory=lambda: client
            ).scrape_all()
        )


def test_page_number_validation():
    with pytest.raises(ValueError, match="at least 1"):
        JobsChScraper()._listing_url(0)
