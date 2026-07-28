from pydantic import BaseModel, ConfigDict, Field


class CategoryBreakdown(BaseModel):
    """Counts for one categorical job field."""

    model_config = ConfigDict(extra="forbid")

    counts: dict[str, int] = Field(default_factory=dict)
    missing: int = Field(default=0, ge=0)


class AnalysisSummary(BaseModel):
    """A first, intentionally small set of descriptive job statistics."""

    model_config = ConfigDict(extra="forbid")

    total_jobs: int = Field(ge=0)
    by_source: CategoryBreakdown
    by_company: CategoryBreakdown
    by_location: CategoryBreakdown
    by_employment_type: CategoryBreakdown
    by_remote_type: CategoryBreakdown


class IndexedJobLocation(BaseModel):
    """Minimal job data stored in the role/location query index."""

    model_config = ConfigDict(extra="forbid")

    title: str
    location: str


class DemandMapPoint(BaseModel):
    """An aggregated map point for one recognized Swiss location."""

    model_config = ConfigDict(extra="forbid")

    name: str
    latitude: float
    longitude: float
    job_count: int = Field(ge=1)


class DemandMapResult(BaseModel):
    """Map-ready demand data for one role filter."""

    model_config = ConfigDict(extra="forbid")

    role: str
    matching_jobs: int = Field(ge=0)
    mapped_jobs: int = Field(ge=0)
    unmapped_jobs: int = Field(ge=0)
    is_truncated: bool = False
    points: list[DemandMapPoint] = Field(default_factory=list)
