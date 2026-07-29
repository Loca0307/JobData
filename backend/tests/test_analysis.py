from app.analysis.demand_map import build_demand_map, recover_location
from app.analysis.geocoding import resolve_cached_swiss_location
from app.analysis.models import IndexedJobLocation
from app.analysis.summary import analyze_jobs
from app.models.jobs import NormalizedJob


def job(external_id: str, **values) -> NormalizedJob:
    return NormalizedJob(
        title=f"Job {external_id}",
        source_website=values.pop("source_website", "jobs.example"),
        source_url=f"https://jobs.example/{external_id}",
        external_id=external_id,
        **values,
    )


def test_analysis_summarizes_common_categorical_fields():
    jobs = [
        job(
            "1",
            company="Example AG",
            location="Zurich",
            employment_type="Full-time",
            remote_type="Hybrid",
        ),
        job(
            "2",
            company="Example AG",
            location="Bern",
            employment_type="Full-time",
            remote_type="Remote",
        ),
        job(
            "3",
            source_website="another.example",
            company="Other SA",
            location="Zurich",
            employment_type="Part-time",
            remote_type="Hybrid",
        ),
    ]

    summary = analyze_jobs(jobs)

    assert summary.total_jobs == 3
    assert summary.by_source.counts == {
        "jobs.example": 2,
        "another.example": 1,
    }
    assert summary.by_company.counts == {"Example AG": 2, "Other SA": 1}
    assert summary.by_location.counts == {"Zurich": 2, "Bern": 1}
    assert summary.by_employment_type.counts == {
        "Full-time": 2,
        "Part-time": 1,
    }
    assert summary.by_remote_type.counts == {"Hybrid": 2, "Remote": 1}


def test_analysis_tracks_missing_values_without_inventing_a_category():
    summary = analyze_jobs(
        iter(
            [
                job("1"),
                job("2", company="   ", location="Zurich"),
            ]
        )
    )

    assert summary.total_jobs == 2
    assert summary.by_company.counts == {}
    assert summary.by_company.missing == 2
    assert summary.by_location.counts == {"Zurich": 1}
    assert summary.by_location.missing == 1


def test_analysis_handles_an_empty_dataset():
    summary = analyze_jobs([])

    assert summary.total_jobs == 0
    assert summary.by_source.counts == {}
    assert summary.by_source.missing == 0


def test_demand_map_filters_titles_and_groups_swiss_locations():
    jobs = [
        IndexedJobLocation(
            title="Data Engineer",
            location="8000 Zürich",
        ),
        IndexedJobLocation(
            title="Senior Data Engineer",
            location="Zurich, Switzerland",
        ),
        IndexedJobLocation(
            title="Software Engineer",
            location="Genève",
        ),
        IndexedJobLocation(
            title="Data Scientist",
            location="Bern",
        ),
        IndexedJobLocation(
            title="Data Engineer",
            location="Remote Switzerland",
        ),
    ]

    result = build_demand_map("data engineer", jobs)

    assert result.matching_jobs == 3
    assert result.mapped_jobs == 2
    assert result.unmapped_jobs == 1
    assert [(point.name, point.job_count) for point in result.points] == [
        ("Zürich", 2)
    ]


def test_demand_map_supports_partial_role_words():
    jobs = [
        IndexedJobLocation(title="Medical Assistant", location="Bern"),
        IndexedJobLocation(title="Medicine Specialist", location="Zürich"),
        IndexedJobLocation(title="Media Manager", location="Geneva"),
    ]

    result = build_demand_map("medic", jobs)

    assert result.matching_jobs == 2
    assert {point.name for point in result.points} == {"Bern", "Zürich"}


def test_location_can_be_recovered_from_retained_listing_payload():
    location = recover_location(
        {
            "listing": {
                "title": "Data Engineer",
                "place": "8000 Zürich",
            }
        }
    )

    assert location == "8000 Zürich"


def test_engineer_locations_present_in_stored_data_are_mapped():
    jobs = [
        IndexedJobLocation(title="IT System Engineer", location="Domat/Ems"),
        IndexedJobLocation(title="Backend Engineer", location="Grand-Lancy"),
        IndexedJobLocation(title="System Engineer", location="Alpnach"),
    ]

    result = build_demand_map("engineer", jobs)

    assert result.mapped_jobs == 3
    assert {point.name for point in result.points} == {
        "Alpnach",
        "Domat/Ems",
        "Grand-Lancy",
    }


def test_unknown_city_is_resolved_once_and_cached(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {
                        "attrs": {
                            "label": "<b>Prilly (VD)</b>",
                            "lat": 46.5382,
                            "lon": 6.6046,
                        }
                    }
                ]
            }

    requests = []
    monkeypatch.setattr(
        "app.analysis.geocoding.httpx.get",
        lambda *args, **kwargs: requests.append((args, kwargs)) or Response(),
    )
    resolve_cached_swiss_location.cache_clear()

    first = resolve_cached_swiss_location("Prilly")
    second = resolve_cached_swiss_location("Prilly")

    assert first == second
    assert first and first.name == "Prilly"
    assert len(requests) == 1
