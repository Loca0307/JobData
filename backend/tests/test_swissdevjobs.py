from pathlib import Path

import pytest

from app.scrapers.base import ScrapeError
from app.scrapers.swissdevjobs import SwissDevJobsScraper

FIXTURE = (Path(__file__).parent / "fixtures" / "swissdevjobs.xml").read_text()


class FakeClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.urls: list[str] = []

    def get_text(self, url: str) -> str:
        self.urls.append(url)
        return self.text

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *_: object) -> None:
        pass


def test_scrape_fetches_feed_once_and_returns_every_entry_without_filtering():
    client = FakeClient(FIXTURE)
    scraper = SwissDevJobsScraper(client_factory=lambda: client)

    records = list(scraper.scrape_all())

    assert [record.source_job_id for record in records] == [
        "example-1",
        "other-1",
    ]
    assert client.urls == ["https://swissdevjobs.ch/rss"]


def test_feed_normalization_retains_sections_and_lossless_source_fields():
    records = list(SwissDevJobsScraper()._parse_feed(FIXTURE))
    job = records[0].normalized_job

    assert job.title == "Senior Platform Engineer"
    assert job.company_name == "Example AG"
    assert job.salary_raw == "CHF 115'000 - 130'000"
    assert job.requirements == "German and English."
    assert job.responsibilities == "Build platforms."
    assert "Python Kubernetes" in job.description
    assert job.posted_at.isoformat() == "2026-03-20T23:00:00+00:00"
    assert str(job.source_url) == (
        "https://swissdevjobs.ch/jobs/example?ref=keep"
    )
    assert records[0].raw_payload["description"].lstrip().startswith(
        "<p><b>Salary:"
    )


def test_feed_deduplicates_by_guid():
    duplicate = FIXTURE.replace(
        "</channel>",
        """
        <item><title>Duplicate @ Example</title>
        <link>https://swissdevjobs.ch/jobs/duplicate</link>
        <guid>example-1</guid><description>duplicate</description></item>
        </channel>
        """,
    )

    assert len(list(SwissDevJobsScraper()._parse_feed(duplicate))) == 2


@pytest.mark.parametrize(
    "xml",
    ["not xml", "<rss></rss>"],
)
def test_feed_fails_on_malformed_or_unexpected_shape(xml: str):
    with pytest.raises(ScrapeError):
        list(SwissDevJobsScraper()._parse_feed(xml))
