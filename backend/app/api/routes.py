from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    status,
)

from app.analysis.demand_map import build_demand_map, matches_role, title_terms
from app.analysis.geocoding import resolve_cached_swiss_locations
from app.analysis.models import DemandMapResult
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


@router.get("/analysis/demand-map", response_model=DemandMapResult)
def job_demand_map(
    role: Annotated[str, Query(min_length=2, max_length=80)],
    repository: Annotated[
        IngestionRepository, Depends(get_ingestion_repository)
    ],
) -> DemandMapResult:
    if not title_terms(role):
        raise HTTPException(
            status_code=422,
            detail="Role must contain at least one word",
        )
    jobs = repository.get_cached_job_locations()
    locations = resolve_cached_swiss_locations(
        job.location
        for job in jobs
        if matches_role(role, job.search_title or job.title)
    )
    return build_demand_map(
        role,
        jobs,
        location_resolver=locations.get,
    )


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
