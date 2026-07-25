from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_ingestion_repository
from app.core.settings import get_settings
from app.db.dynamodb import get_dynamodb_client
from app.db.repositories import IngestionRepository
from app.models.runs import JobCounts
from app.scrapers.registry import get_all_source_names

router = APIRouter(prefix="/api/v1")


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
