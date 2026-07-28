from datetime import UTC, datetime

from fastapi.testclient import TestClient

import app.api.routes as routes
from app.analysis.models import IndexedJobLocation
from app.api.main import create_app
from app.api.routes import get_ingestion_repository
from app.models.runs import JobCounts, RunStatus, ScrapeRun


class StatsRepository:
    def __init__(self) -> None:
        self.runs: dict[str, ScrapeRun] = {}

    def create_run(self, run: ScrapeRun) -> None:
        self.runs[run.run_id] = run.model_copy(deep=True)

    def finish_run(self, run: ScrapeRun) -> None:
        self.runs[run.run_id] = run.model_copy(deep=True)

    def get_run(self, run_id: str) -> ScrapeRun | None:
        return self.runs.get(run_id)

    def get_counts(self, source_names: tuple[str, ...]) -> JobCounts:
        return JobCounts(
            total=12,
            by_source={
                "jobs.ch": 7,
                "jobup.ch": 4,
                "swissdevjobs.ch": 1,
            },
        )

    def get_indexed_job_locations(
        self,
        role: str,
        limit: int,
    ) -> list[IndexedJobLocation]:
        assert role == "engineer"
        assert limit == 1_000
        return [
            IndexedJobLocation(title="Data Engineer", location="Zürich"),
            IndexedJobLocation(title="Software Engineer", location="Geneva"),
        ]


def test_health_does_not_trigger_dynamodb_access():
    with TestClient(create_app(validate_config=False)) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_job_counts_are_bounded_aggregate_data():
    app = create_app(validate_config=False)
    app.dependency_overrides[get_ingestion_repository] = StatsRepository

    with TestClient(app) as client:
        response = client.get("/api/v1/stats/jobs")

    assert response.status_code == 200
    assert response.json()["total"] == 12
    assert response.json()["by_source"]["jobs.ch"] == 7


def test_demand_map_returns_map_ready_aggregates():
    app = create_app(validate_config=False)
    app.dependency_overrides[get_ingestion_repository] = StatsRepository

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/analysis/demand-map",
            params={"role": "engineer"},
        )

    assert response.status_code == 200
    assert response.json()["matching_jobs"] == 2
    assert response.json()["mapped_jobs"] == 2
    assert [point["name"] for point in response.json()["points"]] == [
        "Geneva",
        "Zürich",
    ]


def test_ingestion_endpoint_returns_accepted_run_and_exposes_status(monkeypatch):
    repository = StatsRepository()
    app = create_app(validate_config=False)
    app.dependency_overrides[get_ingestion_repository] = lambda: repository
    executed: list[str] = []

    monkeypatch.setattr(routes, "get_configured_scrapers", lambda settings: [object()])

    def finish_in_background(run, scrapers, target_repository, **kwargs):
        executed.append(run.run_id)
        run.status = RunStatus.COMPLETED
        run.completed_at = datetime.now(UTC)
        target_repository.finish_run(run)

    monkeypatch.setattr(routes, "execute_scrape_run", finish_in_background)

    with TestClient(app) as client:
        start_response = client.post("/api/v1/ingestion/runs")
        run_id = start_response.json()["run_id"]
        status_response = client.get(f"/api/v1/ingestion/runs/{run_id}")

    assert start_response.status_code == 202
    assert start_response.json()["status"] == "running"
    assert executed == [run_id]
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "completed"


def test_unknown_ingestion_run_returns_404():
    repository = StatsRepository()
    app = create_app(validate_config=False)
    app.dependency_overrides[get_ingestion_repository] = lambda: repository

    with TestClient(app) as client:
        response = client.get("/api/v1/ingestion/runs/missing")

    assert response.status_code == 404
