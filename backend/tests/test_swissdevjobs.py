from pathlib import Path

import pytest

from app.scrapers.base import ScrapeError
from app.scrapers.swissdevjobs import SwissDevJobsScraper

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = (FIXTURES / "swissdevjobs.xml").read_text()
DETAIL_FIXTURE = (FIXTURES / "swissdevjobs_detail.html").read_text()


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


def test_scrape_fetches_feed_and_enriches_every_entry_without_filtering():
    pages = {
        "https://swissdevjobs.ch/rss": FIXTURE,
        "https://swissdevjobs.ch/jobs/example?ref=keep": DETAIL_FIXTURE,
        "https://swissdevjobs.ch/jobs/other": DETAIL_FIXTURE.replace(
            '"jobUrl": "example"',
            '"jobUrl": "other"',
        ),
    }
    client = FakeClient(pages)
    scraper = SwissDevJobsScraper(client_factory=lambda: client)

    records = list(scraper.scrape_all())

    assert [record.source_job_id for record in records] == [
        "example-1",
        "other-1",
    ]
    assert client.urls == list(pages)
    job = records[0].normalized_job
    assert job.title == "Senior Platform Engineer"
    assert job.company == "Example AG"
    assert job.location == "Example Street 1, 8000 Zürich"
    assert job.employment_type == "Full-Time"
    assert job.seniority == "Senior"
    assert job.remote_type == "hybrid"
    assert job.salary == "CHF 115'000 - 130'000"
    assert job.required_languages == ["German"]
    assert job.source_website == "swissdevjobs.ch"
    assert job.external_id == "example-1"
    assert records[0].raw_payload["rss"]["guid"] == "example-1"
    detail = records[0].raw_payload["detail"]
    assert detail["extraEvidence"] == {
        "keep": True
    }
    assert detail["technologies"] == ["Python", "Kubernetes", "Python"]
    assert detail["annualSalaryFrom"] == 115_000


def test_feed_normalization_retains_sections_and_lossless_source_fields():
    records = list(SwissDevJobsScraper()._parse_feed(FIXTURE))
    job = records[0].normalized_job

    assert job.title == "Senior Platform Engineer"
    assert job.company == "Example AG"
    assert job.salary == "CHF 115'000 - 130'000"
    assert job.requirements == "German and English."
    assert "Python\nKubernetes" in job.description
    assert job.posting_date.isoformat() == "2026-03-20T23:00:00+00:00"
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


def test_detail_requires_structured_payload():
    record = next(SwissDevJobsScraper()._parse_feed(FIXTURE))

    with pytest.raises(ScrapeError, match="payload marker is missing"):
        SwissDevJobsScraper()._parse_detail("<html></html>", record)


def test_detail_rejects_mismatched_slug():
    record = next(SwissDevJobsScraper()._parse_feed(FIXTURE))
    detail = DETAIL_FIXTURE.replace(
        '"jobUrl": "example"',
        '"jobUrl": "different"',
    )

    with pytest.raises(ScrapeError, match="slug does not match"):
        SwissDevJobsScraper()._parse_detail(detail, record)
