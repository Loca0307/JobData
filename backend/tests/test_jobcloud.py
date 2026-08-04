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


def detail_fixture(source_id: str) -> str:
    return fixture("jobcloud_detail.html").replace(
        '"value": "job-1"',
        f'"value": "{source_id}"',
    )


def test_jobs_ch_paginates_enriches_and_preserves_raw_data():
    pages = {
        "https://www.jobs.ch/en/vacancies/?term=": fixture(
            "jobcloud_page_1.html"
        ),
        "https://www.jobs.ch/en/vacancies/detail/job-1/": detail_fixture(
            "job-1"
        ),
        "https://www.jobs.ch/en/vacancies/detail/job-2/": detail_fixture(
            "job-2"
        ),
        "https://www.jobs.ch/en/vacancies/?term=&page=2": fixture(
            "jobcloud_page_2.html"
        ),
        "https://www.jobs.ch/en/vacancies/detail/job-3/": detail_fixture(
            "job-3"
        ),
        "https://www.jobs.ch/en/vacancies/?term=&page=3": fixture(
            "jobcloud_empty.html"
        ),
    }
    client = FakeClient(pages)

    records = list(JobsChScraper(client_factory=lambda: client).scrape_all())

    assert [record.source_job_id for record in records] == [
        "job-1",
        "job-2",
        "job-3",
    ]
    assert client.urls == list(pages)
    job = records[0].normalized_job
    assert job.title == "Senior Data Engineer"
    assert job.company == "Example AG"
    assert job.location == "Example Street 1, 8000, Zürich, CH"
    assert job.country_code == "CH"
    assert job.description.startswith("Your role")
    assert job.employment_type == "Permanent position"
    assert job.remote_type == "remote"
    assert job.salary == "CHF 120000–140000 per year"
    assert str(job.apply_url) == "https://example.test/jobs/job-1/apply"
    assert records[0].raw_payload["listing"]["extraEvidence"] == {
        "keep": True
    }
    assert records[0].raw_payload["detail"]["skills"] == ["Python", "AWS"]


def test_repeated_page_stops_without_duplicate_records():
    listing = fixture("jobcloud_page_1.html")
    pages = {
        "https://www.jobs.ch/en/vacancies/?term=": listing,
        "https://www.jobs.ch/en/vacancies/detail/job-1/": detail_fixture(
            "job-1"
        ),
        "https://www.jobs.ch/en/vacancies/detail/job-2/": detail_fixture(
            "job-2"
        ),
        "https://www.jobs.ch/en/vacancies/?term=&page=2": listing,
    }
    client = FakeClient(pages)

    records = list(JobsChScraper(client_factory=lambda: client).scrape_all())

    assert [record.source_job_id for record in records] == ["job-1", "job-2"]


def test_jobup_builds_its_own_listing_and_detail_urls():
    state = {
        "vacancy": {
            "results": {
                "main": {"results": [{"id": "abc", "title": "Comptable"}]}
            }
        }
    }
    scraper = JobupChScraper()
    records = scraper._parse_listing(f"__INIT__ = {json.dumps(state)}")

    assert scraper._listing_url(2) == "https://www.jobup.ch/en/jobs/?page=2"
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
            "must be a list",
        ),
        (
            '__INIT__ = {"vacancy":{"results":{"main":{"results":[{}]}}}}',
            "no usable jobs",
        ),
    ],
)
def test_jobcloud_rejects_invalid_listing_data(html: str, message: str):
    with pytest.raises(ScrapeError, match=message):
        JobsChScraper()._parse_listing(html)


def test_page_limit_fails_instead_of_claiming_completion():
    client = FakeClient(
        {
            "https://www.jobs.ch/en/vacancies/?term=": fixture(
                "jobcloud_page_1.html"
            ),
            "https://www.jobs.ch/en/vacancies/detail/job-1/": detail_fixture(
                "job-1"
            ),
            "https://www.jobs.ch/en/vacancies/detail/job-2/": detail_fixture(
                "job-2"
            ),
        }
    )

    with pytest.raises(ScrapeError, match="before an empty page"):
        list(
            JobsChScraper(
                settings=Settings(SCRAPER_MAX_PAGES=1),
                client_factory=lambda: client,
            ).scrape_all()
        )


def test_detail_must_be_a_matching_job_posting():
    scraper = JobsChScraper()
    record = scraper._parse_listing(fixture("jobcloud_page_1.html"))[0]

    with pytest.raises(ScrapeError, match="JSON-LD is missing"):
        scraper._enrich_from_detail("<html></html>", record)
    with pytest.raises(ScrapeError, match="IDs do not match"):
        scraper._enrich_from_detail(detail_fixture("another-job"), record)
