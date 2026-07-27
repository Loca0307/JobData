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


def detail_fixture(source_job_id: str) -> str:
    return fixture("jobcloud_detail.html").replace(
        '"value": "job-1"',
        f'"value": "{source_job_id}"',
    )


def test_jobs_ch_scrapes_until_empty_without_filters_and_preserves_raw_payload():
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
    scraper = JobsChScraper(client_factory=lambda: client)

    records = list(scraper.scrape_all())

    assert [record.source_job_id for record in records] == [
        "job-1",
        "job-2",
        "job-3",
    ]
    assert client.urls == list(pages)
    job = records[0].normalized_job
    assert job.title == "Senior Data Engineer"
    assert job.company == "Example AG"
    assert job.location == "Example Street 1, 8000 Zürich, CH"
    assert job.description == (
        "Your role\nBuild reliable data platforms.\n"
        "Your profile\nFive years of Python experience."
    )
    assert job.requirements == "Five years of Python experience."
    assert job.employment_type == "Permanent position"
    assert job.remote_type == "remote"
    assert job.salary == "CHF 120000–140000 per year"
    assert job.required_languages == []
    assert job.source_website == "jobs.ch"
    assert job.external_id == "job-1"
    assert str(job.apply_url) == "https://example.test/jobs/job-1/apply"
    assert job.posting_date.isoformat() == (
        "2026-07-10T08:30:00+00:00"
    )
    assert records[0].raw_payload["listing"]["extraEvidence"] == {
        "keep": True
    }
    detail = records[0].raw_payload["detail"]["json_ld"]
    assert detail["@type"] == "JobPosting"
    assert detail["skills"] == ["Python", "AWS"]
    assert detail["jobBenefits"] == ["Flexible hours", "Pension"]


def test_repeated_page_terminates_collection_without_emitting_duplicates():
    repeated = fixture("jobcloud_page_1.html")
    pages = {
        "https://www.jobs.ch/en/vacancies/?term=": repeated,
        "https://www.jobs.ch/en/vacancies/detail/job-1/": detail_fixture(
            "job-1"
        ),
        "https://www.jobs.ch/en/vacancies/detail/job-2/": detail_fixture(
            "job-2"
        ),
        "https://www.jobs.ch/en/vacancies/?term=&page=2": repeated,
    }
    client = FakeClient(pages)

    records = list(JobsChScraper(client_factory=lambda: client).scrape_all())

    assert [record.source_job_id for record in records] == ["job-1", "job-2"]
    assert client.urls == list(pages)


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
    client = FakeClient(
        {
            "https://www.jobs.ch/en/vacancies/?term=": page,
            "https://www.jobs.ch/en/vacancies/detail/job-1/": (
                detail_fixture("job-1")
            ),
            "https://www.jobs.ch/en/vacancies/detail/job-2/": (
                detail_fixture("job-2")
            ),
        }
    )
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


def test_jobs_ch_keeps_required_empty_term_during_pagination():
    scraper = JobsChScraper()

    assert scraper._listing_url(1) == (
        "https://www.jobs.ch/en/vacancies/?term="
    )
    assert scraper._listing_url(2) == (
        "https://www.jobs.ch/en/vacancies/?term=&page=2"
    )


def test_jobcloud_detail_requires_job_posting_json_ld():
    scraper = JobsChScraper()
    record = scraper._parse_listing(fixture("jobcloud_page_1.html"))[0]

    with pytest.raises(ScrapeError, match="JobPosting JSON-LD is missing"):
        scraper._parse_detail("<html></html>", record)


def test_jobcloud_detail_rejects_mismatched_identifier():
    scraper = JobsChScraper()
    record = scraper._parse_listing(fixture("jobcloud_page_1.html"))[0]

    with pytest.raises(ScrapeError, match="identifier does not match"):
        scraper._parse_detail(detail_fixture("another-job"), record)
