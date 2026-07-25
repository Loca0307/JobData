from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models.jobs import NormalizedJob, SourceRecord
from app.models.runs import JobCounts, RunStatus, ScrapeRun, SourceRunResult
from app.scrapers.base import BaseJobScraper, ScrapeError
from app.services.ingestion import NoAuthorizedSourcesError, ingest_all_sources


def record(source: str, source_job_id: str) -> SourceRecord:
    raw = {"id": source_job_id}
    job = NormalizedJob(
        source_name=source,
        source_job_id=source_job_id,
        source_url=f"https://example.test/{source_job_id}",
        title=f"Job {source_job_id}",
        parser_version="test-v1",
        raw_payload=raw,
    )
    return SourceRecord(
        source_name=source,
        source_job_id=source_job_id,
        raw_payload=raw,
        normalized_job=job,
    )


class FakeScraper(BaseJobScraper):
    def __init__(
        self,
        source_name: str,
        records: list[SourceRecord],
        *,
        fail_after: int | None = None,
    ) -> None:
        self.source_name = source_name
        self.records = records
        self.fail_after = fail_after

    def scrape_all(self):
        for index, item in enumerate(self.records):
            if self.fail_after == index:
                raise ScrapeError("fixture failure")
            yield item


class FakeRepository:
    def __init__(self) -> None:
        self.known: set[tuple[str, str]] = set()
        self.created_run: ScrapeRun | None = None
        self.source_results: list[SourceRunResult] = []
        self.finished_run: ScrapeRun | None = None

    def create_run(self, run: ScrapeRun) -> None:
        self.created_run = run.model_copy(deep=True)

    def save_source_result(self, run_id: str, result: SourceRunResult) -> None:
        assert self.created_run and run_id == self.created_run.run_id
        self.source_results.append(result)

    def save_record(self, item: SourceRecord, run_id: str) -> bool:
        assert self.created_run and run_id == self.created_run.run_id
        key = (item.source_name, item.source_job_id)
        created = key not in self.known
        self.known.add(key)
        return created

    def finish_run(self, run: ScrapeRun) -> None:
        self.finished_run = run.model_copy(deep=True)

    def get_counts(self, source_names: tuple[str, ...]) -> JobCounts:
        return JobCounts(total=0, by_source=dict.fromkeys(source_names, 0))


def test_ingestion_isolates_source_failure_and_keeps_partial_records():
    repository = FakeRepository()
    good = FakeScraper("good.test", [record("good.test", "1")])
    partial = FakeScraper(
        "partial.test",
        [record("partial.test", "1"), record("partial.test", "2")],
        fail_after=1,
    )

    run = ingest_all_sources([good, partial], repository, max_workers=2)

    assert run.status == RunStatus.PARTIAL
    assert run.jobs_seen == 2
    assert run.jobs_created == 2
    assert [result.status for result in run.sources] == [
        RunStatus.COMPLETED,
        RunStatus.FAILED,
    ]
    assert run.sources[1].error_category == "ScrapeError"
    assert repository.finished_run == run


def test_reingestion_updates_sightings_without_duplicate_creation():
    repository = FakeRepository()
    scraper = FakeScraper("example.test", [record("example.test", "1")])

    first = ingest_all_sources([scraper], repository)
    second = ingest_all_sources([scraper], repository)

    assert first.jobs_created == 1
    assert second.jobs_created == 0
    assert second.jobs_updated == 1


def test_no_authorized_sources_stops_before_creating_a_run():
    repository = FakeRepository()

    with pytest.raises(NoAuthorizedSourcesError):
        ingest_all_sources([], repository)

    assert repository.created_run is None
