from collections import Counter
from collections.abc import Iterable

from app.analysis.models import AnalysisSummary, CategoryBreakdown
from app.models.jobs import NormalizedJob


def analyze_jobs(jobs: Iterable[NormalizedJob]) -> AnalysisSummary:
    """Build descriptive counts without knowing where the jobs are stored."""
    counters = {
        "source": Counter[str](),
        "company": Counter[str](),
        "location": Counter[str](),
        "employment_type": Counter[str](),
        "remote_type": Counter[str](),
    }
    missing = dict.fromkeys(counters, 0)
    total_jobs = 0

    for job in jobs:
        total_jobs += 1
        values = {
            "source": job.source_website,
            "company": job.company,
            "location": job.location,
            "employment_type": job.employment_type,
            "remote_type": job.remote_type,
        }
        for field_name, value in values.items():
            cleaned_value = value.strip() if value else ""
            if cleaned_value:
                counters[field_name][cleaned_value] += 1
            else:
                # Missing data is counted separately instead of being turned
                # into an invented category that looks like source data.
                missing[field_name] += 1

    return AnalysisSummary(
        total_jobs=total_jobs,
        by_source=_breakdown(counters["source"], missing["source"]),
        by_company=_breakdown(counters["company"], missing["company"]),
        by_location=_breakdown(counters["location"], missing["location"]),
        by_employment_type=_breakdown(
            counters["employment_type"],
            missing["employment_type"],
        ),
        by_remote_type=_breakdown(
            counters["remote_type"],
            missing["remote_type"],
        ),
    )


def _breakdown(counter: Counter[str], missing: int) -> CategoryBreakdown:
    # Stable ordering makes API responses, exported files, and tests repeatable.
    ordered_counts = dict(
        sorted(counter.items(), key=lambda item: (-item[1], item[0].casefold()))
    )
    return CategoryBreakdown(counts=ordered_counts, missing=missing)
