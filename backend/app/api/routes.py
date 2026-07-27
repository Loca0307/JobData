from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.core.settings import get_settings
from app.db.dynamodb import get_dynamodb_client
from app.db.repositories import DynamoIngestionRepository, IngestionRepository
from app.models.runs import JobCounts, ScrapeRun
from app.scrapers.registry import get_all_source_names, get_configured_scrapers
from app.services.ingestion import create_scrape_run, execute_scrape_run

router = APIRouter(prefix="/api/v1")


@lru_cache(maxsize=1)
def get_ingestion_repository() -> DynamoIngestionRepository:
    settings = get_settings()
    _, table_name = settings.require_dynamodb()
    return DynamoIngestionRepository(get_dynamodb_client(), table_name)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readiness")
def readiness() -> dict[str, str]:
    settings = get_settings()
    _, table_name = settings.require_dynamodb()
    try:
        get_dynamodb_client().describe_table(TableName=table_name)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="DynamoDB is not ready",
        ) from exc
    return {"status": "ready"}


@router.get("/stats/jobs", response_model=JobCounts)
def job_counts(
    repository: Annotated[
        IngestionRepository, Depends(get_ingestion_repository)
    ],
) -> JobCounts:
    return repository.get_counts(get_all_source_names())


@router.post(
    "/ingestion/runs",
    response_model=ScrapeRun,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_ingestion_run(
    background_tasks: BackgroundTasks,
    repository: Annotated[
        IngestionRepository, Depends(get_ingestion_repository)
    ],
) -> ScrapeRun:
    settings = get_settings()
    scrapers = get_configured_scrapers(settings)
    run = create_scrape_run(scrapers, repository)
    background_tasks.add_task(
        execute_scrape_run,
        run,
        scrapers,
        repository,
        max_workers=settings.scraper_source_max_workers,
    )
    return run


@router.get("/ingestion/runs/{run_id}", response_model=ScrapeRun)
def ingestion_run(
    run_id: str,
    repository: Annotated[
        IngestionRepository, Depends(get_ingestion_repository)
    ],
) -> ScrapeRun:
    run = repository.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Scrape run not found")
    return run
