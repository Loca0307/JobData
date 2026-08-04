from pathlib import Path

import pytest

from app.scrapers.base import ScrapeError
from app.scrapers.swissdevjobs import SwissDevJobsScraper

FIXTURES = Path(__file__).parent / "fixtures"
FEED = (FIXTURES / "swissdevjobs.xml").read_text()
DETAIL = (FIXTURES / "swissdevjobs_detail.html").read_text()


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


def test_scrape_reads_feed_then_enriches_each_job():
    pages = {
        "https://swissdevjobs.ch/rss": FEED,
        "https://swissdevjobs.ch/jobs/example?ref=keep": DETAIL,
        "https://swissdevjobs.ch/jobs/other": DETAIL.replace(
            '"jobUrl": "example"',
            '"jobUrl": "other"',
        ),
    }
    client = FakeClient(pages)

    records = list(
        SwissDevJobsScraper(client_factory=lambda: client).scrape_all()
    )

    assert [record.source_job_id for record in records] == [
        "example-1",
        "other-1",
    ]
    assert client.urls == list(pages)
    job = records[0].normalized_job
    assert job.title == "Senior Platform Engineer"
    assert job.company == "Example AG"
    assert job.location == "Example Street 1, 8000, Zürich"
    assert job.country_code == "CH"
    assert job.employment_type == "Full-Time"
    assert job.seniority == "Senior"
    assert job.remote_type == "hybrid"
    assert job.salary == "CHF 115'000 - 130'000"
    assert job.required_languages == ["German"]
    assert records[0].raw_payload["rss"]["guid"] == "example-1"
    assert records[0].raw_payload["detail"]["technologies"] == [
        "Python",
        "Kubernetes",
        "Python",
    ]


def test_feed_normalizes_core_fields_and_removes_tracking_parameters():
    record = next(SwissDevJobsScraper()._parse_feed(FEED))
    job = record.normalized_job

    assert job.requirements == "German and English."
    assert "Python\nKubernetes" in job.description
    assert str(job.source_url) == (
        "https://swissdevjobs.ch/jobs/example?ref=keep"
    )
    assert record.raw_payload["description"].lstrip().startswith("<p><b>Salary:")


@pytest.mark.parametrize("xml", ["not xml", "<rss></rss>"])
def test_feed_rejects_invalid_xml(xml: str):
    with pytest.raises(ScrapeError):
        list(SwissDevJobsScraper()._parse_feed(xml))


def test_detail_must_exist_and_match_the_feed_job():
    scraper = SwissDevJobsScraper()
    record = next(scraper._parse_feed(FEED))

    with pytest.raises(ScrapeError, match="payload is missing"):
        scraper._enrich_from_detail("<html></html>", record)
    with pytest.raises(ScrapeError, match="IDs do not match"):
        scraper._enrich_from_detail(
            DETAIL.replace('"jobUrl": "example"', '"jobUrl": "different"'),
            record,
        )
