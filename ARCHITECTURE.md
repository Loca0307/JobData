# Architecture

## Tech Stack

- Python 3.12, FastAPI, Pydantic, and pydantic-settings
- boto3 and DynamoDB
- HTTPX, Beautiful Soup, and Python XML ElementTree
- pytest, respx, and Ruff
- Next.js, React, TypeScript, ESLint, D3 Geo, TopoJSON Client, and Swiss Maps
- Docker and Docker Compose

## Job Collection

- `backend/app/scrapers/registry.py` constructs the enabled `jobs.ch`,
  `jobup.ch`, and `swissdevjobs.ch` adapters from configuration.
- Every adapter implements `BaseJobScraper.scrape_all()` from
  `backend/app/scrapers/base.py` and yields `SourceRecord` objects. Scrapers do
  not write to DynamoDB.
- `backend/app/scrapers/http.py` contains a thread-safe
  `RequestRateLimiter` and a small HTTP client. Together they apply a truthful
  user agent, per-source request spacing, timeouts, bounded redirects, and
  bounded retries with exponential backoff. Numeric `Retry-After` values are
  honored.
- `backend/app/scrapers/jobcloud.py` shares one implementation between jobs.ch
  and jobup.ch. It reads the public listing payload, stops at an empty or
  repeated page, and reads each public JobPosting JSON-LD detail record.
- `backend/app/scrapers/swissdevjobs.py` reads the RSS feed and each public
  embedded detail record.
- Both adapters normalize only the core fields used by `NormalizedJob` and
  retain the listing/feed and structured detail objects in `raw_payload`.
  Missing fields remain null. They do not contain the previous large set of
  source-specific extraction helpers.
- Missing listing markers, malformed payloads, mismatched detail identities,
  HTTP failures, and pagination-limit exhaustion fail the affected source
  visibly.
- `backend/tests/test_http.py`, `backend/tests/test_jobcloud.py`,
  `backend/tests/test_swissdevjobs.py`, and fixtures under
  `backend/tests/fixtures/` cover this reduced workflow without live traffic.

## Normalized Records

- `backend/app/models/jobs.py` defines `NormalizedJob` and `SourceRecord`.
- `NormalizedJob` is the small common representation used by persistence.
- `SourceRecord.raw_payload` preserves source evidence for later reprocessing.
- The source name and source job ID identify an occurrence. The implementation
  does not attempt uncertain cross-source vacancy matching.

## Ingestion

- `backend/app/services/ingestion.py` creates a scrape run and executes enabled
  sources concurrently.
- Each yielded record is sent to the `IngestionRepository` interface.
- A source failure does not discard records already stored by that source or
  successful results from other sources.
- The final run status is completed, partial, or failed.
- `backend/app/workers/scrape_all.py` provides the command-line entry point.
- `backend/tests/test_ingestion.py` covers partial failure, repeat ingestion,
  and the no-enabled-source case.

## DynamoDB Persistence

- `backend/app/db/repositories.py` owns all DynamoDB keys and serialization.
- A deterministic hash of source name and source job ID produces the internal
  occurrence ID.
- Existing occurrences update their last-seen data. New occurrences are
  inserted in the same transaction that increments total and per-source
  counters.
- The transaction uses a deterministic request token. Duplicate insert races
  update the winning item, and temporary transaction conflicts receive bounded
  retries.
- Scrape runs use `RUN#<run-id>` items. Aggregate counters and the latest
  completed run use `STATS` items.
- `get_counts()` batch-reads a fixed set of keys and never scans the job table.
- `backend/app/db/dynamodb.py` uses the normal AWS credential chain and never
  creates or changes the owner-provisioned table.
- `backend/tests/test_repository.py` covers IDs, hashing, new and existing
  records, counters, transaction conflicts, and run reads.

## API and Dashboard

- `backend/app/api/main.py` configures FastAPI, startup validation, and CORS.
- `backend/app/api/routes.py` exposes health, readiness, aggregate counts,
  scrape-run creation, and scrape-run status endpoints under `/api/v1`.
- The ingestion POST stores a running record, returns `202`, and starts an
  in-process FastAPI background task.
- `frontend/lib/api.ts` is the typed API client.
- `frontend/components/job-overview.tsx` displays occurrence counts and run
  state, starts a run, polls every two seconds, and refreshes totals when the
  run finishes.
- The frontend never receives AWS credentials or accesses DynamoDB directly.
- `backend/tests/test_api.py` covers the operational API.

## Job Analysis and Demand Map

- `backend/app/analysis/summary.py` calculates descriptive counts from any
  iterable of `NormalizedJob` objects. `backend/app/analysis/models.py`
  defines the typed summary and map outputs.
- `backend/app/db/repositories.py` scans all normalized job occurrences,
  projects only the normalized job and retained raw payload, and keeps the
  resulting title/location list in memory for five minutes. A successful job
  write invalidates the cache so the next request sees newly ingested data.
- `GET /api/v1/analysis/demand-map?role=<role>` in
  `backend/app/api/routes.py` filters the complete cached list for every role
  search; it does not truncate the candidate set.
- `backend/app/analysis/demand_map.py` verifies all requested title terms,
  supports word-prefix searches such as `medic` matching `medical`, and
  aggregates matching jobs by resolved city.
- `backend/app/analysis/geocoding.py` resolves common cities locally, then uses
  the official Swiss geo.admin.ch location search for other city strings.
  Distinct locations for one result are resolved with bounded concurrency, and
  a bounded in-process LRU cache avoids repeated lookups. Coordinates are
  accepted only inside a Swiss bounding box.
- `frontend/lib/api.ts` retrieves the typed result.
  `frontend/lib/swiss-map.ts` converts the published 2026 Swiss canton
  TopoJSON into SVG paths and projects job coordinates through the same D3
  geographic projection.
  `frontend/components/demand-map.tsx` renders it as a responsive inline SVG
  map with keyboard-accessible dots and a details panel for the selected city.
  The same canton polygons assign each mapped city to a canton for the
  expandable canton-count list; the total uses every title match, including
  jobs whose location could not be mapped.
  `frontend/app/globals.css` contains the map styling; no map tiles, browser
  geocoding, or client-side job dataset are used.
- A DynamoDB scan failure is returned as an API failure and does not replace
  the existing cache. A failed or invalid geocoding response leaves that job
  explicitly unmapped rather than guessing a coordinate.
- `backend/tests/test_analysis.py`, `backend/tests/test_repository.py`, and
  `backend/tests/test_api.py` cover aggregation, cached geo.admin.ch location
  resolution, partial role words, raw-location recovery, scan caching, and the
  API response without live network access.

## Containers

- `backend/Dockerfile` and `frontend/Dockerfile` build the two applications.
- `compose.yaml` runs only FastAPI and Next.js. It does not provision DynamoDB.
- Inputs are the documented environment variables. Outputs are the API on port
  8000 and dashboard on port 3000.
