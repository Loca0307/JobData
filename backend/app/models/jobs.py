from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class WorkplaceType(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ON_SITE = "on-site"
    UNKNOWN = "unknown"


class ListingStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"


class NormalizedJob(BaseModel):
    """Source-independent job emitted by a scraper, before persistence."""

    model_config = ConfigDict(extra="forbid")

    source_name: str
    source_type: str = "job_board"
    source_job_id: str
    source_url: HttpUrl
    apply_url: HttpUrl | None = None
    title: str = Field(min_length=1, max_length=500)
    company_name: str | None = None
    company_identifiers: dict[str, str] = Field(default_factory=dict)
    company_website: HttpUrl | None = None
    raw_location_text: str | None = None
    locations: list[str] = Field(default_factory=list)
    country: str | None = None
    region: str | None = None
    description: str | None = None
    responsibilities: str | None = None
    requirements: str | None = None
    employment_type: str | None = None
    schedule: str | None = None
    contract_type: str | None = None
    occupation: str | None = None
    seniority: str | None = None
    workplace_type: WorkplaceType = WorkplaceType.UNKNOWN
    salary_minimum: int | float | None = None
    salary_maximum: int | float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    salary_raw: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    experience: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    benefits: list[str] = Field(default_factory=list)
    posted_at: datetime | None = None
    expires_at: datetime | None = None
    updated_at: datetime | None = None
    scraped_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )
    listing_status: ListingStatus = ListingStatus.ACTIVE
    inactive_evidence: str | None = None
    schema_version: str = "1"
    parser_version: str
    raw_payload: dict[str, Any]


class SourceRecord(BaseModel):
    """Lossless source occurrence paired with its normalized representation."""

    model_config = ConfigDict(extra="forbid")

    source_name: str
    source_job_id: str
    raw_payload: dict[str, Any]
    normalized_job: NormalizedJob
