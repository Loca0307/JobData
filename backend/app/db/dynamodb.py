from __future__ import annotations

from functools import lru_cache
from typing import Any

import boto3

from app.core.settings import get_settings


@lru_cache(maxsize=1)
def get_dynamodb_client() -> Any:
    settings = get_settings()
    region, _ = settings.require_dynamodb()
    return boto3.client(
        "dynamodb",
        region_name=region,
        endpoint_url=settings.dynamodb_endpoint_url,
    )
