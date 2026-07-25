from __future__ import annotations

from datetime import UTC, datetime

from app.db.repositories import (
    DynamoIngestionRepository,
    _content_hash,
    stable_job_id,
)
from app.models.jobs import NormalizedJob, SourceRecord
from app.models.runs import RunStatus, ScrapeRun


def make_record() -> SourceRecord:
    raw = {"id": "42", "score": 0.75}
    job = NormalizedJob(
        source_name="jobs.ch",
        source_job_id="42",
        source_url="https://www.jobs.ch/en/vacancies/detail/42/",
        title="Data Engineer",
        parser_version="fixture-v1",
        raw_payload=raw,
        scraped_at=datetime(2026, 7, 24, tzinfo=UTC),
    )
    return SourceRecord(
        source_name="jobs.ch",
        source_job_id="42",
        raw_payload=raw,
        normalized_job=job,
    )


def test_stable_job_id_is_source_scoped_and_repeatable():
    assert stable_job_id("jobs.ch", "42") == stable_job_id("JOBS.CH", "42")
    assert stable_job_id("jobs.ch", "42") != stable_job_id("jobup.ch", "42")


def test_content_hash_is_order_independent_but_content_sensitive():
    first = _content_hash({"a": 1, "b": 2}, {"nested": {"x": True}})
    reordered = _content_hash({"b": 2, "a": 1}, {"nested": {"x": True}})
    changed = _content_hash({"a": 1, "b": 3}, {"nested": {"x": True}})

    assert first == reordered
    assert first != changed


def test_repository_creates_atomic_counter_updates_for_new_occurrence():
    client = RecordingClient()
    repository = DynamoIngestionRepository(client, "JobData")

    created = repository.save_record(make_record(), "run-1")

    assert created is True
    transaction = client.transactions[0]
    assert [item[next(iter(item))]["TableName"] for item in transaction] == [
        "JobData",
        "JobData",
        "JobData",
    ]
    assert transaction[1]["Update"]["Key"]["SK"]["S"] == "TOTAL"
    assert transaction[2]["Update"]["Key"]["SK"]["S"] == "SOURCE#jobs.ch"
    stored = transaction[0]["Put"]["Item"]
    assert stored["raw_payload"]["M"]["score"]["N"] == "0.75"


def test_run_and_latest_run_are_finished_together():
    client = RecordingClient(existing=True)
    repository = DynamoIngestionRepository(client, "JobData")
    run = ScrapeRun(
        run_id="run-1",
        status=RunStatus.COMPLETED,
        completed_at=datetime(2026, 7, 24, tzinfo=UTC),
    )

    repository.finish_run(run)

    transaction = client.transactions[0]
    assert transaction[0]["Update"]["Key"]["PK"]["S"] == "RUN#run-1"
    assert transaction[1]["Put"]["Item"]["SK"]["S"] == "LATEST_RUN"


class RecordingClient:
    def __init__(self, *, existing: bool = False) -> None:
        self.existing = existing
        self.transactions: list[list[dict]] = []

    def update_item(self, **kwargs):
        if not self.existing and "ConditionExpression" in kwargs:
            from botocore.exceptions import ClientError

            raise ClientError(
                {
                    "Error": {
                        "Code": "ConditionalCheckFailedException",
                        "Message": "missing",
                    }
                },
                "UpdateItem",
            )
        return {}

    def transact_write_items(self, *, TransactItems):
        self.transactions.append(TransactItems)
        return {}
