from __future__ import annotations

from functools import lru_cache

from app.core.settings import get_settings
from app.db.dynamodb import get_dynamodb_client
from app.db.repositories import DynamoIngestionRepository


@lru_cache(maxsize=1)
def get_ingestion_repository() -> DynamoIngestionRepository:
    settings = get_settings()
    _, table_name = settings.require_dynamodb()
    return DynamoIngestionRepository(get_dynamodb_client(), table_name)
