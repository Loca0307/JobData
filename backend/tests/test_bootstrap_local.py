from __future__ import annotations

import pytest

from app.db.bootstrap_local import ensure_table, validate_local_bootstrap


class ResourceNotFoundException(Exception):
    pass


class FakeWaiter:
    def __init__(self) -> None:
        self.waited_for: str | None = None

    def wait(self, *, TableName: str) -> None:
        self.waited_for = TableName


class FakeClient:
    class exceptions:
        ResourceNotFoundException = ResourceNotFoundException

    def __init__(self, *, exists: bool) -> None:
        self.exists = exists
        self.create_request: dict[str, object] | None = None
        self.waiter = FakeWaiter()

    def describe_table(self, *, TableName: str) -> None:
        if not self.exists:
            raise ResourceNotFoundException(TableName)

    def create_table(self, **request: object) -> None:
        self.create_request = request

    def get_waiter(self, name: str) -> FakeWaiter:
        assert name == "table_exists"
        return self.waiter


def test_local_bootstrap_requires_explicit_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DYNAMODB_LOCAL_BOOTSTRAP", raising=False)

    with pytest.raises(RuntimeError, match="DYNAMODB_LOCAL_BOOTSTRAP"):
        validate_local_bootstrap("http://localhost:8000")


def test_local_bootstrap_rejects_non_local_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DYNAMODB_LOCAL_BOOTSTRAP", "true")

    with pytest.raises(RuntimeError, match="Local bootstrap"):
        validate_local_bootstrap("https://dynamodb.eu-central-1.amazonaws.com")


def test_ensure_table_creates_expected_local_schema() -> None:
    client = FakeClient(exists=False)

    result = ensure_table(client, "JobData")

    assert result == "created"
    assert client.create_request == {
        "TableName": "JobData",
        "AttributeDefinitions": [
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        "KeySchema": [
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        "BillingMode": "PAY_PER_REQUEST",
    }
    assert client.waiter.waited_for == "JobData"


def test_ensure_table_leaves_existing_table_unchanged() -> None:
    client = FakeClient(exists=True)

    assert ensure_table(client, "JobData") == "existing"
    assert client.create_request is None
