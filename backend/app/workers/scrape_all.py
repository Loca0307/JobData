from __future__ import annotations

import json
import logging

from app.core.settings import get_settings
from app.db.dynamodb import get_dynamodb_client
from app.db.repositories import DynamoIngestionRepository
from app.scrapers.registry import get_configured_scrapers
from app.services.ingestion import ingest_all_sources


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s %(levelname)s %(name)s "
            "run_id=%(run_id)s source=%(source)s %(message)s"
        ),
        defaults={"run_id": "-", "source": "-"},
    )
    settings = get_settings()
    _, table_name = settings.require_dynamodb()
    repository = DynamoIngestionRepository(
        get_dynamodb_client(),
        table_name,
    )
    run = ingest_all_sources(
        get_configured_scrapers(settings),
        repository,
        max_workers=settings.scraper_source_max_workers,
    )
    print(json.dumps(run.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
