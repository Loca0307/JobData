from __future__ import annotations

import hashlib
import json
import random
import threading
import time
from datetime import UTC
from decimal import Decimal
from typing import Any, Protocol

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError

from app.analysis.demand_map import recover_location
from app.analysis.models import IndexedJobLocation
from app.analysis.title_aliases import expand_search_title
from app.models.jobs import SourceRecord
from app.models.runs import JobCounts, ScrapeRun, SourceRunResult

_serializer = TypeSerializer()
_deserializer = TypeDeserializer()
_TRANSACTION_MAX_RETRIES = 5
_TRANSACTION_RETRY_BASE_SECONDS = 0.05
_UPDATE_OCCURRENCE_EXPRESSION = (
    "SET last_seen_at = :last_seen_at, "
    "last_run_id = :last_run_id, "
    "content_hash = :content_hash, "
    "normalized_job = :normalized, "
    "raw_payload = :raw_payload"
)


class IngestionRepository(Protocol):
    def create_run(self, run: ScrapeRun) -> None: ...

    def save_source_result(self, run_id: str, result: SourceRunResult) -> None: ...

    def save_record(self, record: SourceRecord, run_id: str) -> bool: ...

    def finish_run(self, run: ScrapeRun) -> None: ...

    def get_run(self, run_id: str) -> ScrapeRun | None: ...

    def get_counts(self, source_names: tuple[str, ...]) -> JobCounts: ...

    def get_cached_job_locations(self) -> list[IndexedJobLocation]: ...


class DynamoIngestionRepository:
    """Single-table repository for idempotent occurrences, runs, and counters."""

    def __init__(self, client: Any, table_name: str) -> None:
        self._client = client
        self._table_name = table_name
        self._job_location_cache: tuple[IndexedJobLocation, ...] = ()
        self._job_location_cache_expires_at = 0.0
        self._job_location_cache_lock = threading.Lock()

    def create_run(self, run: ScrapeRun) -> None:
        item = {
            "PK": f"RUN#{run.run_id}",
            "SK": "META",
            "entity_type": "scrape_run",
            **run.model_dump(mode="json"),
        }
        self._client.put_item(
            TableName=self._table_name,
            Item=_serialize_item(item),
            ConditionExpression="attribute_not_exists(PK)",
        )

    def save_source_result(self, run_id: str, result: SourceRunResult) -> None:
        item = {
            "PK": f"RUN#{run_id}",
            "SK": f"SOURCE#{result.source_name}",
            "entity_type": "source_run",
            "run_id": run_id,
            **result.model_dump(mode="json"),
        }
        self._client.put_item(
            TableName=self._table_name,
            Item=_serialize_item(item),
        )

    def save_record(self, record: SourceRecord, run_id: str) -> bool:
        self._job_location_cache_expires_at = 0.0
        now = record.normalized_job.scrape_timestamp.astimezone(UTC).isoformat()
        job_id = stable_job_id(record.source_name, record.source_job_id)
        key = {
            "PK": f"JOB#{job_id}",
            "SK": f"SOURCE#{record.source_name}#{record.source_job_id}",
        }
        normalized = record.normalized_job.model_dump(mode="json")
        raw_payload = record.raw_payload
        content_hash = _content_hash(normalized, raw_payload)
        values = _serialize_item(
            {
                ":last_seen_at": now,
                ":last_run_id": run_id,
                ":content_hash": content_hash,
                ":normalized": normalized,
                ":raw_payload": raw_payload,
            }
        )
        if self._update_occurrence_if_present(key, values):
            return False

        item = {
            **key,
            "entity_type": "job_occurrence",
            "job_id": job_id,
            "source_name": record.source_name,
            "source_job_id": record.source_job_id,
            "first_seen_at": now,
            "last_seen_at": now,
            "last_run_id": run_id,
            "content_hash": content_hash,
            "normalized_job": normalized,
            "raw_payload": raw_payload,
        }
        transaction_items = [
            {
                "Put": {
                    "TableName": self._table_name,
                    "Item": _serialize_item(item),
                    "ConditionExpression": "attribute_not_exists(PK)",
                }
            },
            _counter_update(self._table_name, "TOTAL"),
            _counter_update(
                self._table_name, f"SOURCE#{record.source_name}"
            ),
        ]
        client_request_token = hashlib.sha256(
            f"{run_id}\0{record.source_name}\0{record.source_job_id}".encode()
        ).hexdigest()[:36]
        for attempt in range(_TRANSACTION_MAX_RETRIES + 1):
            try:
                self._client.transact_write_items(
                    TransactItems=transaction_items,
                    ClientRequestToken=client_request_token,
                )
                return True
            except ClientError as exc:
                if _is_transaction_condition_failure(exc):
                    # Another worker inserted this occurrence after our first
                    # existence check. Updating the winner keeps counters exact.
                    if self._update_occurrence_if_present(key, values):
                        return False
                    raise
                if (
                    not _is_transaction_conflict(exc)
                    or attempt == _TRANSACTION_MAX_RETRIES
                ):
                    raise
                backoff = _TRANSACTION_RETRY_BASE_SECONDS * (2**attempt)
                time.sleep(backoff + random.uniform(0, backoff))
        raise AssertionError("transaction retry loop terminated unexpectedly")

    def _update_occurrence_if_present(
        self,
        key: dict[str, str],
        values: dict[str, Any],
    ) -> bool:
        """Update one occurrence, returning False when it does not exist."""
        try:
            self._client.update_item(
                TableName=self._table_name,
                Key=_serialize_item(key),
                ConditionExpression="attribute_exists(PK)",
                UpdateExpression=_UPDATE_OCCURRENCE_EXPRESSION,
                ExpressionAttributeValues=values,
            )
        except ClientError as exc:
            if _is_conditional_failure(exc):
                return False
            raise
        return True

    def finish_run(self, run: ScrapeRun) -> None:
        run_payload = run.model_dump(mode="json")
        self._client.transact_write_items(
            TransactItems=[
                {
                    "Update": {
                        "TableName": self._table_name,
                        "Key": _serialize_item(
                            {"PK": f"RUN#{run.run_id}", "SK": "META"}
                        ),
                        "UpdateExpression": (
                            "SET #status = :status, completed_at = :completed_at, "
                            "jobs_seen = :jobs_seen, jobs_created = :jobs_created, "
                            "jobs_updated = :jobs_updated, sources = :sources"
                        ),
                        "ExpressionAttributeNames": {"#status": "status"},
                        "ExpressionAttributeValues": _serialize_item(
                            {
                                ":status": run_payload["status"],
                                ":completed_at": run_payload["completed_at"],
                                ":jobs_seen": run.jobs_seen,
                                ":jobs_created": run.jobs_created,
                                ":jobs_updated": run.jobs_updated,
                                ":sources": run_payload["sources"],
                            }
                        ),
                    }
                },
                {
                    "Put": {
                        "TableName": self._table_name,
                        "Item": _serialize_item(
                            {
                                "PK": "STATS",
                                "SK": "LATEST_RUN",
                                "entity_type": "latest_run",
                                **run_payload,
                            }
                        ),
                    }
                },
            ]
        )

    def get_run(self, run_id: str) -> ScrapeRun | None:
        response = self._client.get_item(
            TableName=self._table_name,
            Key=_serialize_item({"PK": f"RUN#{run_id}", "SK": "META"}),
            ConsistentRead=True,
        )
        raw_item = response.get("Item")
        if not raw_item:
            return None
        item = _deserialize_item(raw_item)
        return ScrapeRun.model_validate(
            {
                key: value
                for key, value in item.items()
                if key not in {"PK", "SK", "entity_type"}
            }
        )

    def get_counts(self, source_names: tuple[str, ...]) -> JobCounts:
        keys = [{"PK": "STATS", "SK": "TOTAL"}]
        keys.extend(
            {"PK": "STATS", "SK": f"SOURCE#{name}"}
            for name in source_names
        )
        keys.append({"PK": "STATS", "SK": "LATEST_RUN"})
        request_items = {
            self._table_name: {
                "Keys": [_serialize_item(key) for key in keys],
                "ConsistentRead": False,
            }
        }
        response = self._client.batch_get_item(RequestItems=request_items)
        raw_items = list(
            response.get("Responses", {}).get(self._table_name, [])
        )
        unprocessed = response.get("UnprocessedKeys", {})
        while unprocessed:
            response = self._client.batch_get_item(RequestItems=unprocessed)
            raw_items.extend(
                response.get("Responses", {}).get(self._table_name, [])
            )
            unprocessed = response.get("UnprocessedKeys", {})
        items = [
            _deserialize_item(item)
            for item in raw_items
        ]
        by_key = {(item["PK"], item["SK"]): item for item in items}
        by_source = {
            name: int(
                by_key.get(("STATS", f"SOURCE#{name}"), {}).get("count", 0)
            )
            for name in source_names
        }
        total = int(by_key.get(("STATS", "TOTAL"), {}).get("count", 0))
        latest_item = by_key.get(("STATS", "LATEST_RUN"))
        latest_run = (
            ScrapeRun.model_validate(
                {
                    key: value
                    for key, value in latest_item.items()
                    if key not in {"PK", "SK", "entity_type"}
                }
            )
            if latest_item
            else None
        )
        return JobCounts(
            total=total,
            by_source=by_source,
            latest_run=latest_run,
        )

    def get_cached_job_locations(self) -> list[IndexedJobLocation]:
        """Scan job occurrences once, then reuse them for five minutes."""
        now = time.monotonic()
        if now < self._job_location_cache_expires_at:
            return list(self._job_location_cache)

        with self._job_location_cache_lock:
            now = time.monotonic()
            if now < self._job_location_cache_expires_at:
                return list(self._job_location_cache)

            jobs: list[IndexedJobLocation] = []
            exclusive_start_key = None
            while True:
                request: dict[str, Any] = {
                    "TableName": self._table_name,
                    "FilterExpression": "entity_type = :entity_type",
                    "ExpressionAttributeValues": _serialize_item(
                        {":entity_type": "job_occurrence"}
                    ),
                    "ProjectionExpression": "normalized_job, raw_payload",
                }
                if exclusive_start_key:
                    request["ExclusiveStartKey"] = exclusive_start_key
                response = self._client.scan(**request)
                for raw_item in response.get("Items", []):
                    item = _deserialize_item(raw_item)
                    normalized = item.get("normalized_job", {})
                    title = normalized.get("title")
                    location = normalized.get("location")
                    if not isinstance(location, str) or not location.strip():
                        raw_payload = item.get("raw_payload", {})
                        location = (
                            recover_location(raw_payload)
                            if isinstance(raw_payload, dict)
                            else None
                        )
                    if isinstance(title, str) and isinstance(location, str):
                        jobs.append(
                            IndexedJobLocation(
                                title=title,
                                search_title=expand_search_title(title),
                                location=location,
                            )
                        )
                exclusive_start_key = response.get("LastEvaluatedKey")
                if not exclusive_start_key:
                    break

            self._job_location_cache = tuple(jobs)
            self._job_location_cache_expires_at = now + 300
            return list(self._job_location_cache)


def stable_job_id(source_name: str, source_job_id: str) -> str:
    value = f"{source_name.casefold()}\0{source_job_id}".encode()
    return hashlib.sha256(value).hexdigest()[:32]


def _content_hash(normalized: dict[str, Any], raw_payload: dict[str, Any]) -> str:
    value = json.dumps(
        {"normalized": normalized, "raw_payload": raw_payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(value).hexdigest()


def _counter_update(table_name: str, sort_key: str) -> dict[str, Any]:
    return {
        "Update": {
            "TableName": table_name,
            "Key": _serialize_item({"PK": "STATS", "SK": sort_key}),
            "UpdateExpression": (
                "SET entity_type = if_not_exists(entity_type, :entity_type) "
                "ADD #count :one"
            ),
            "ExpressionAttributeNames": {"#count": "count"},
            "ExpressionAttributeValues": _serialize_item(
                {":entity_type": "counter", ":one": 1}
            ),
        }
    }


def _serialize_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _serializer.serialize(_dynamodb_safe(value))
        for key, value in item.items()
    }


def _deserialize_item(item: dict[str, Any]) -> dict[str, Any]:
    return {key: _deserializer.deserialize(value) for key, value in item.items()}


def _dynamodb_safe(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, list):
        return [_dynamodb_safe(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _dynamodb_safe(item)
            for key, item in value.items()
        }
    return value


def _is_conditional_failure(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") == (
        "ConditionalCheckFailedException"
    )


def _is_transaction_condition_failure(exc: ClientError) -> bool:
    return (
        exc.response.get("Error", {}).get("Code")
        == "TransactionCanceledException"
        and "ConditionalCheckFailed" in _transaction_cancellation_codes(exc)
    )


def _is_transaction_conflict(exc: ClientError) -> bool:
    error_code = exc.response.get("Error", {}).get("Code")
    return error_code == "TransactionConflictException" or (
        error_code == "TransactionCanceledException"
        and "TransactionConflict" in _transaction_cancellation_codes(exc)
    )


def _transaction_cancellation_codes(exc: ClientError) -> set[str]:
    reasons = exc.response.get("CancellationReasons", [])
    return {
        reason["Code"]
        for reason in reasons
        if isinstance(reason, dict)
        and isinstance(reason.get("Code"), str)
        and reason["Code"] != "None"
    }
