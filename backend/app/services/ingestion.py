from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from uuid import uuid4

from app.db.repositories import IngestionRepository
from app.models.runs import RunStatus, ScrapeRun, SourceRunResult
from app.scrapers.base import BaseJobScraper

logger = logging.getLogger(__name__)


class NoEnabledSourcesError(RuntimeError):
    pass


def ingest_all_sources(
    scrapers: list[BaseJobScraper],
    repository: IngestionRepository,
    *,
    max_workers: int = 3,
) -> ScrapeRun:
    if not scrapers:
        raise NoEnabledSourcesError(
            "No scraper sources are enabled. Set SCRAPER_ENABLED_SOURCES to "
            "one or more registered source names."
        )

    run = ScrapeRun(run_id=str(uuid4()))
    repository.create_run(run)
    workers = min(max_workers, len(scrapers))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        tasks = {
            executor.submit(_ingest_source, scraper, repository, run.run_id): (
                scraper.source_name
            )
            for scraper in scrapers
        }
        results = []
        for task in as_completed(tasks):
            result = task.result()
            repository.save_source_result(run.run_id, result)
            results.append(result)

    results.sort(key=lambda result: result.source_name)
    run.sources = results
    run.jobs_seen = sum(result.jobs_seen for result in results)
    run.jobs_created = sum(result.jobs_created for result in results)
    run.jobs_updated = sum(result.jobs_updated for result in results)
    completed_count = sum(
        result.status == RunStatus.COMPLETED for result in results
    )
    if completed_count == len(results):
        run.status = RunStatus.COMPLETED
    elif completed_count:
        run.status = RunStatus.PARTIAL
    else:
        run.status = RunStatus.FAILED
    run.completed_at = datetime.now(UTC)
    repository.finish_run(run)
    return run


def _ingest_source(
    scraper: BaseJobScraper,
    repository: IngestionRepository,
    run_id: str,
) -> SourceRunResult:
    started_at = datetime.now(UTC)
    jobs_seen = 0
    jobs_created = 0
    try:
        for record in scraper.scrape_all():
            jobs_seen += 1
            jobs_created += repository.save_record(record, run_id)
        status = RunStatus.COMPLETED
        error_category = None
        error_message = None
    except Exception as exc:
        logger.exception(
            "Source ingestion failed",
            extra={"run_id": run_id, "source": scraper.source_name},
        )
        status = RunStatus.FAILED
        error_category = type(exc).__name__
        error_message = str(exc)
    completed_at = datetime.now(UTC)
    return SourceRunResult(
        source_name=scraper.source_name,
        status=status,
        jobs_seen=jobs_seen,
        jobs_created=jobs_created,
        jobs_updated=jobs_seen - jobs_created,
        started_at=started_at,
        completed_at=completed_at,
        error_category=error_category,
        error_message=error_message,
    )
