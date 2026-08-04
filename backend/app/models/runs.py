from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class SourceRunResult(BaseModel):
    source_name: str
    status: RunStatus
    jobs_seen: int = 0
    jobs_filtered: int = 0
    jobs_created: int = 0
    jobs_updated: int = 0
    started_at: datetime
    completed_at: datetime
    error_category: str | None = None
    error_message: str | None = None


class ScrapeRun(BaseModel):
    run_id: str
    status: RunStatus = RunStatus.RUNNING
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    jobs_seen: int = 0
    jobs_filtered: int = 0
    jobs_created: int = 0
    jobs_updated: int = 0
    sources: list[SourceRunResult] = Field(default_factory=list)


class JobCounts(BaseModel):
    total: int
    by_source: dict[str, int]
    latest_run: ScrapeRun | None = None
