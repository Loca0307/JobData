from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import urlparse

from botocore.exceptions import BotoCoreError

from app.core.settings import get_settings
from app.db.dynamodb import get_dynamodb_client

LOCAL_HOSTS = {"dynamodb", "localhost", "127.0.0.1"}


def validate_local_bootstrap(endpoint_url: str | None) -> None:
    enabled = os.getenv("DYNAMODB_LOCAL_BOOTSTRAP", "").casefold() == "true"
    parsed = urlparse(endpoint_url or "")
    if not enabled:
        raise RuntimeError("DYNAMODB_LOCAL_BOOTSTRAP=true is required")
    if parsed.scheme != "http" or parsed.hostname not in LOCAL_HOSTS:
        raise RuntimeError(
            "Local bootstrap requires an HTTP DynamoDB endpoint on "
            "dynamodb, localhost, or 127.0.0.1"
        )


def ensure_table(client: Any, table_name: str) -> str:
    try:
        client.describe_table(TableName=table_name)
        return "existing"
    except client.exceptions.ResourceNotFoundException:
        client.create_table(
            TableName=table_name,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        client.get_waiter("table_exists").wait(TableName=table_name)
        return "created"


def main() -> None:
    settings = get_settings()
    validate_local_bootstrap(settings.dynamodb_endpoint_url)
    _, table_name = settings.require_dynamodb()
    client = get_dynamodb_client()

    for attempt in range(1, 31):
        try:
            result = ensure_table(client, table_name)
            print(f"DynamoDB Local table {table_name!r} is {result}.")
            return
        except BotoCoreError:
            if attempt == 30:
                raise
            time.sleep(1)


if __name__ == "__main__":
    main()
