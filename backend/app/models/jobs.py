from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class NormalizedJob(BaseModel):
    """Source-independent job emitted by a scraper, before persistence."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    company: str | None = None
    location: str | None = None
    description: str | None = None
    requirements: str | None = None
    seniority: str | None = None
    employment_type: str | None = None
    remote_type: str | None = None
    salary: str | None = None
    required_languages: list[str] = Field(default_factory=list)
    source_website: str
    source_url: HttpUrl
    apply_url: HttpUrl | None = None
    posting_date: datetime | None = None
    scrape_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )
    external_id: str = Field(min_length=1)


class SourceRecord(BaseModel):
    """Lossless source occurrence paired with its normalized representation."""

    model_config = ConfigDict(extra="forbid")

    raw_payload: dict[str, Any]
    normalized_job: NormalizedJob

    @property
    def source_name(self) -> str:
        return self.normalized_job.source_website

    @property
    def source_job_id(self) -> str:
        return self.normalized_job.external_id
