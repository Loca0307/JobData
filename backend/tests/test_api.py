from fastapi.testclient import TestClient

from app.api.dependencies import get_ingestion_repository
from app.api.main import create_app
from app.models.runs import JobCounts


class StatsRepository:
    def get_counts(self, source_names: tuple[str, ...]) -> JobCounts:
        return JobCounts(
            total=12,
            by_source={
                "jobs.ch": 7,
                "jobup.ch": 4,
                "swissdevjobs.ch": 1,
            },
        )


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
