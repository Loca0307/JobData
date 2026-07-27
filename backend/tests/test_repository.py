from __future__ import annotations

from datetime import UTC, datetime

import pytest
from botocore.exceptions import ClientError

import app.db.repositories as repositories
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
        company_name="Example AG",
        raw_location_text="8000 Zürich",
        locations=["8000 Zürich"],
        country="CH",
        region="ZH",
        description="Build and maintain data platforms.",
        responsibilities="Build reliable pipelines.",
        requirements="Python and AWS experience.",
        employment_type="Full time",
        salary_minimum=120_000,
        salary_maximum=140_000,
        salary_currency="CHF",
        salary_period="YEAR",
        salary_raw="CHF 120000–140000 per year",
        required_skills=["Python", "AWS"],
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
    normalized = stored["normalized_job"]["M"]
    assert normalized["title"]["S"] == "Data Engineer"
    assert normalized["company_name"]["S"] == "Example AG"
    assert normalized["locations"]["L"][0]["S"] == "8000 Zürich"
    assert normalized["description"]["S"] == (
        "Build and maintain data platforms."
    )
    assert normalized["salary_minimum"]["N"] == "120000"
    assert normalized["salary_maximum"]["N"] == "140000"
    assert normalized["salary_currency"]["S"] == "CHF"
    assert [item["S"] for item in normalized["required_skills"]["L"]] == [
        "Python",
        "AWS",
    ]
    assert len(client.transaction_tokens[0]) == 36


def test_repository_retries_transaction_conflicts_with_bounded_backoff(
    monkeypatch,
):
    conflict = transaction_cancelled("None", "TransactionConflict", "None")
    client = RecordingClient(transaction_errors=[conflict, conflict])
    repository = DynamoIngestionRepository(client, "JobData")
    sleeps: list[float] = []
    monkeypatch.setattr(repositories.random, "uniform", lambda _start, _end: 0)
    monkeypatch.setattr(repositories.time, "sleep", sleeps.append)

    created = repository.save_record(make_record(), "run-1")

    assert created is True
    assert len(client.transactions) == 3
    assert len(set(client.transaction_tokens)) == 1
    assert sleeps == [0.05, 0.1]


def test_repository_uses_duplicate_fallback_only_for_conditional_cancellation():
    duplicate = transaction_cancelled(
        "ConditionalCheckFailed",
        "None",
        "None",
    )
    client = RecordingClient(transaction_errors=[duplicate])
    repository = DynamoIngestionRepository(client, "JobData")

    created = repository.save_record(make_record(), "run-1")

    assert created is False
    assert client.update_calls == 2


def test_repository_does_not_hide_unknown_transaction_cancellation():
    cancellation = transaction_cancelled("ValidationError", "None", "None")
    client = RecordingClient(transaction_errors=[cancellation])
    repository = DynamoIngestionRepository(client, "JobData")

    with pytest.raises(ClientError) as raised:
        repository.save_record(make_record(), "run-1")

    assert raised.value is cancellation
    assert client.update_calls == 1


def test_repository_stops_after_bounded_transaction_conflict_retries(
    monkeypatch,
):
    conflicts = [
        transaction_cancelled("None", "TransactionConflict", "None")
        for _ in range(repositories._TRANSACTION_MAX_RETRIES + 1)
    ]
    client = RecordingClient(transaction_errors=conflicts)
    repository = DynamoIngestionRepository(client, "JobData")
    sleeps: list[float] = []
    monkeypatch.setattr(repositories.random, "uniform", lambda _start, _end: 0)
    monkeypatch.setattr(repositories.time, "sleep", sleeps.append)

    with pytest.raises(ClientError):
        repository.save_record(make_record(), "run-1")

    assert len(client.transactions) == repositories._TRANSACTION_MAX_RETRIES + 1
    assert len(sleeps) == repositories._TRANSACTION_MAX_RETRIES


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


def test_repository_reads_a_specific_scrape_run():
    run = ScrapeRun(run_id="run-1")
    client = RecordingClient(run=run)
    repository = DynamoIngestionRepository(client, "JobData")

    stored = repository.get_run("run-1")

    assert stored == run
    assert client.gets[0]["Key"]["PK"]["S"] == "RUN#run-1"
    assert client.gets[0]["ConsistentRead"] is True


class RecordingClient:
    def __init__(
        self,
        *,
        existing: bool = False,
        run: ScrapeRun | None = None,
        transaction_errors: list[ClientError] | None = None,
    ) -> None:
        self.existing = existing
        self.run = run
        self.transaction_errors = list(transaction_errors or [])
        self.transactions: list[list[dict]] = []
        self.transaction_tokens: list[str] = []
        self.gets: list[dict] = []
        self.update_calls = 0

    def update_item(self, **kwargs):
        self.update_calls += 1
        if (
            not self.existing
            and self.update_calls == 1
            and "ConditionExpression" in kwargs
        ):
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

    def transact_write_items(
        self,
        *,
        TransactItems,
        ClientRequestToken=None,
    ):
        self.transactions.append(TransactItems)
        if ClientRequestToken is not None:
            self.transaction_tokens.append(ClientRequestToken)
        if self.transaction_errors:
            raise self.transaction_errors.pop(0)
        return {}

    def get_item(self, **kwargs):
        self.gets.append(kwargs)
        if self.run is None:
            return {}
        return {
            "Item": {
                "PK": {"S": f"RUN#{self.run.run_id}"},
                "SK": {"S": "META"},
                "entity_type": {"S": "scrape_run"},
                **{
                    key: _serialize_attribute(value)
                    for key, value in self.run.model_dump(mode="json").items()
                },
            }
        }


def _serialize_attribute(value):
    from boto3.dynamodb.types import TypeSerializer

    return TypeSerializer().serialize(value)


def transaction_cancelled(*codes: str) -> ClientError:
    return ClientError(
        {
            "Error": {
                "Code": "TransactionCanceledException",
                "Message": "transaction cancelled",
            },
            "CancellationReasons": [
                {"Code": code, "Message": code}
                for code in codes
            ],
        },
        "TransactWriteItems",
    )
