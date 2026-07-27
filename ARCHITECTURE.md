# Architecture

## Tech Stack

- Python 3.12, FastAPI, Pydantic, and pydantic-settings
- boto3 and DynamoDB
- HTTPX, Beautiful Soup, and Python XML ElementTree
- pytest, respx, and Ruff
- Next.js 16, React 19, TypeScript, and ESLint
- Docker and Docker Compose for local application containers

## Unfiltered Swiss Job-Board Adapters

- The shared contract in `backend/app/scrapers/base.py` makes every adapter emit
  `SourceRecord` values and keeps persistence outside source code.
- `backend/app/scrapers/jobcloud.py` contains one JobCloud implementation with
  concrete jobs.ch and jobup.ch subclasses. It walks the public unfiltered
  listing pages in order until a valid empty or repeated page, then fetches the
  public detail page for every unseen source ID. Detail-page JobPosting JSON-LD
  supplies descriptions, responsibilities and requirements where labeled,
  company data, addresses, work terms, salary, skills, benefits, application
  URL, and posting dates. Source-specific query parameters are preserved on
  every page; jobs.ch keeps the required empty `term` value so its page number
  is not redirected away.
- `backend/app/scrapers/swissdevjobs.py` fetches one RSS document, parses every
  item without keyword or location filters, strips tracking query parameters,
  and fetches each canonical public detail page. It combines RSS description
  sections and salary evidence with the detail page's address, work terms,
  seniority, annual salary bounds, technology stack, company metadata, and
  dates.
- `backend/app/scrapers/http.py` supplies bounded redirects, connect/read
  timeouts, shared request spacing, and retry-after-aware transient retries.
  Fetch targets are fixed by the adapters.
- `backend/app/models/jobs.py` is the canonical normalized contract. Unknown
  values stay null, empty, or explicitly `unknown`; the raw adapter payload is
  retained beside normalized fields for reprocessing.
- `backend/app/scrapers/registry.py` makes source selection
  configuration-driven. Every registered adapter is enabled by default and
  `SCRAPER_ENABLED_SOURCES` can select a subset without any project-specific
  authorization setting.
- Inputs are listing HTML, detail HTML, or RSS XML. Outputs are source
  occurrences; adapters never write to DynamoDB. Every record retains both its
  summary/feed payload and detail payload. HTTP, parser, identity mismatch,
  schema, and safety-limit failures stop that source instead of producing a
  false empty result.
- `backend/tests/test_jobcloud.py`,
  `backend/tests/test_swissdevjobs.py`, `backend/tests/test_http.py`, and
  `backend/tests/test_registry.py` cover pagination, repetition, malformed
  inputs, detail identity checks, normalized enrichment, source-specific query
  parameters, raw retention, transient retries, rate limiting, registry
  contracts, and enabled-source selection using sanitized fixtures in
  `backend/tests/fixtures/jobcloud_detail.html`,
  `backend/tests/fixtures/swissdevjobs_detail.html`, and the other fixture
  files in `backend/tests/fixtures/`.

## DynamoDB Ingestion and Scrape Runs

- `backend/app/services/ingestion.py` starts one scrape run and executes
  enabled sources concurrently. Each source remains isolated: records
  already written by a failed source remain stored, successful sources finish,
  and the overall result becomes completed, partial, or failed.
- `backend/app/db/repositories.py` is the persistence boundary. A source
  occurrence receives a deterministic ID derived from source name and source
  job ID. Existing occurrences update their last-seen time, run ID, normalized
  data, raw data, and content hash rather than creating duplicates.
- Every occurrence item contains the complete canonical object under
  `normalized_job` and the lossless source evidence under `raw_payload`.
  Unpublished values remain null or empty; detail enrichment never fabricates
  salary, location, or other missing facts.
- The owner-provisioned table needs only string partition key `PK` and sort key
  `SK`. Job occurrences use `JOB#<stable-id>` /
  `SOURCE#<source>#<source-id>`; scrape runs use `RUN#<run-id>` / `META` plus
  one `SOURCE#<source>` result item.
- New occurrence creation and aggregate counter increments are one DynamoDB
  transaction. Count items use `STATS` / `TOTAL` and
  `STATS` / `SOURCE#<source>`. The latest completed run is stored at
  `STATS` / `LATEST_RUN`, so API reads use a bounded batch get and never scan.
- Each new-occurrence transaction has a deterministic request token for safe
  retries. `backend/app/db/repositories.py` distinguishes a conditional
  duplicate race from a shared-counter `TransactionConflict`: duplicate races
  update the winning item, conflicts receive at most five exponential-backoff
  retries with jitter, and unknown cancellations fail the source.
- `backend/app/db/dynamodb.py` uses the normal AWS credential chain and reads
  region, table, and optional local endpoint settings. It never creates or
  changes the table.
- `backend/app/workers/scrape_all.py` is the scheduler-neutral command-line
  entry point. It validates DynamoDB settings, builds every enabled adapter,
  invokes the pipeline, and prints the completed run summary.
- `backend/app/services/ingestion.py` separates persisted run creation from
  execution so HTTP callers can receive a running `ScrapeRun` before the
  source work begins. The existing command-line worker still uses the combined
  synchronous entry point.
- The repository does not mark a listing inactive after a missing observation.
  Inactivity remains unchanged until a source-aware multi-run policy is
  implemented.
- `backend/tests/test_repository.py` and
  `backend/tests/test_ingestion.py` cover stable identity, content hashing,
  atomic counters, idempotent sightings, reason-aware transaction retries,
  partial failures, run summaries, and the no-enabled-source guard without
  contacting AWS.

## Operational and Aggregate API

- `backend/app/api/main.py` creates the FastAPI application, validates required
  DynamoDB configuration at startup, and permits configured frontend origins.
- `backend/app/api/routes.py` exposes `/api/v1/health` without external work,
  `/api/v1/readiness` with a table readiness check, and
  `/api/v1/stats/jobs` for total, per-source, and latest-run aggregates. It
  also exposes `POST /api/v1/ingestion/runs` to persist and schedule a run and
  `GET /api/v1/ingestion/runs/{run_id}` to read its strongly consistent status.
- `backend/app/api/dependencies.py` constructs the repository behind a FastAPI
  dependency, keeping routes thin and replaceable in tests.
- Inputs are GET requests plus the bodyless ingestion POST. Outputs are typed
  JSON responses; the POST returns `202 Accepted` with the running scrape-run
  ID before its in-process background task executes. DynamoDB or configuration
  failures make readiness fail; health never starts a scrape.
- `backend/app/db/repositories.py` persists and reads individual run metadata.
  `backend/tests/test_api.py` and `backend/tests/test_repository.py` verify the
  side-effect-free health response, bounded aggregates, asynchronous run
  creation, status lookup, missing-run response, and DynamoDB key access.

## Private Count Dashboard

- `frontend/app/page.tsx` renders the single private overview screen through
  `frontend/components/job-overview.tsx`.
- `frontend/lib/api.ts` is the typed API client. It reads only
  aggregate and scrape-run endpoints; the browser never receives AWS
  credentials or direct DynamoDB access.
- `frontend/app/globals.css` provides the responsive layout, loading, empty,
  failure, action, and run-status states. The dashboard shows total stored
  source occurrences, one total for each implemented source, and the latest or
  actively requested run.
- `frontend/components/job-overview.tsx` starts all configured sources from
  the “Run all scrapers” button, disables duplicate clicks while that run is
  active, polls its exact run ID every two seconds, and refreshes aggregates
  when it reaches a terminal state.
- `frontend/app/layout.tsx`, `frontend/next.config.ts`,
  `frontend/tsconfig.json`, and `frontend/eslint.config.mjs` define the
  production Next.js shell and checks.
- The frontend input is the FastAPI base URL. Output is a private operational
  dashboard; failed reads and start requests display retryable errors and do
  not retain credentials or job data.

## Application Containers

- `frontend/Dockerfile` uses one Node 22 Alpine stage: install from the lockfile,
  copy source, build Next.js, prune development packages, and start the
  production server.
- `frontend/next.config.ts` uses the normal Next.js server output so the simple
  `npm start` container command works without standalone-file copying.
- `backend/Dockerfile` installs `backend/requirements.txt` and starts the
  FastAPI application with Uvicorn.
- `compose.yaml` starts only `backend` and `frontend`. It passes AWS region,
  table name, and required local credential environment variables from the
  ignored root `.env` file to the backend. `.env.example` documents the
  temporary assumed-role credential fields without containing secrets.
- Backend directories are Python namespace packages and therefore do not
  contain `__init__.py` marker files. Imports continue to resolve from the
  backend application root in the Python 3.12 runtime.
- Inputs are the root `.env` values and optional frontend API build URL.
  Outputs are the dashboard on port 3000 and API on port 8000. Missing local
  credentials fail Compose interpolation before startup; expired or
  unauthorized credentials remain backend readiness or API failures. Compose
  contains no DynamoDB image, table bootstrap, endpoint override, or AWS
  resource provisioning.
