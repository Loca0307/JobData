# Architectural Choices

## 1. Owner-Managed DynamoDB

- **Choice:** The application uses an existing DynamoDB table configured with
  environment variables and never provisions AWS resources.
- **Why:** Infrastructure ownership is outside this learning project.
- **Relevant files:** `backend/app/core/settings.py`,
  `backend/app/db/dynamodb.py`, and `README.md`.
- **Alternatives:**
  - Terraform or CDK would make infrastructure reproducible but is explicitly
    outside scope.
  - Startup table creation is convenient but could mutate production
    infrastructure unexpectedly.
- **Revisit when:** The owner explicitly changes the infrastructure boundary.

## 2. Teaching-Oriented Source Adapters

- **Choice:** Keep the real listing/feed/detail workflow, but normalize only
  the core shared fields and retain other structured data in `raw_payload`.
  Use short, source-local parsing functions instead of exhaustive extraction
  frameworks.
- **Why:** The code should make fetch, parse, normalize, and emit steps visible
  to a student. The earlier parsers promoted many optional publisher fields and
  required hundreds of lines of helper logic.
- **Relevant files:** `backend/app/scrapers/jobcloud.py`,
  `backend/app/scrapers/swissdevjobs.py`, and
  `backend/app/models/jobs.py`.
- **Alternatives:**
  - Listing/feed-only collection is shorter but hides the useful enrichment
    step and loses detail evidence.
  - Exhaustive detail normalization produces richer canonical records but
    obscures the basic workflow and is harder to maintain.
- **Constraints and risks:** Some available fields remain only in raw data.
  They must be promoted later if a concrete analysis needs them.
- **Revisit when:** A defined analysis requires more normalized fields.

## 3. Shared Rate Limiter and HTTP Client

- **Choice:** Keep timeout, redirect, retry, backoff, and `Retry-After`
  behavior in `ScraperHttpClient`, with a small thread-safe
  `RequestRateLimiter` shared by a source's clients.
- **Why:** These policies protect third-party sites and make failures more
  reliable. A dedicated limiter makes request-slot coordination explicit and
  prevents concurrent clients for one source from exceeding its configured
  rate.
- **Relevant files:** `backend/app/scrapers/http.py` and
  `backend/tests/test_http.py`.
- **Alternatives:**
  - A bare `httpx.get()` is shorter but removes important operational safety.
  - Embedding timing state in each HTTP client uses less code but cannot
    coordinate multiple clients for the same source.
- **Constraints and risks:** Rate limiting is process-local and per scraper.
- **Revisit when:** Multiple processes need coordinated source limits.

## 4. Fail-Loud Structured Parsing

- **Choice:** Use public embedded JSON, JSON-LD, and RSS data. Reject missing
  core structures and mismatched listing/detail identities.
- **Why:** A changed source must not appear to be a successful empty scrape.
- **Relevant files:** `backend/app/scrapers/jobcloud.py` and
  `backend/app/scrapers/swissdevjobs.py`.
- **Alternatives:**
  - Silently skipping all malformed data is shorter but can erase an entire
    source without an operational signal.
  - Browser automation handles rendered pages but adds unnecessary machinery.
- **Revisit when:** A source offers a stable official API or feed.

## 5. Source-Scoped Identity and Raw Provenance

- **Choice:** Use a deterministic hash of source name and source job ID, store
  normalized fields once, and store source evidence once in `raw_payload`.
- **Why:** It makes repeat ingestion idempotent without risky cross-source
  matching.
- **Relevant files:** `backend/app/models/jobs.py`,
  `backend/app/db/repositories.py`, and
  `backend/tests/test_repository.py`.
- **Alternatives:**
  - Random IDs require a lookup before every write.
  - Title/company matching can incorrectly merge separate vacancies.
- **Constraints and risks:** The same vacancy on two boards remains two source
  occurrences.
- **Revisit when:** Evidence-backed merge and unmerge rules are defined.

## 6. Atomic Counters Without Table Scans

- **Choice:** Insert a new occurrence and increment its counters in one
  DynamoDB transaction. Retain bounded conflict retries and duplicate-race
  handling.
- **Why:** These mechanisms are part of the actual persistence process: they
  prevent repeat ingestion and concurrent writes from corrupting dashboard
  totals.
- **Relevant files:** `backend/app/db/repositories.py`,
  `backend/tests/test_repository.py`, and `frontend/lib/api.ts`.
- **Alternatives:**
  - Scanning for counts is easier to demonstrate but becomes expensive as data
    grows.
  - Non-transactional counters use less code but can disagree with stored jobs
    after partial failures.
- **Constraints and risks:** All new jobs contend on one total counter.
- **Revisit when:** Aggregate volume requires asynchronous analytics.

## 7. FastAPI Boundary and In-Process Runs

- **Choice:** Keep DynamoDB behind FastAPI. A run POST returns `202` and uses an
  in-process background task while the dashboard polls its run ID.
- **Why:** It keeps AWS credentials out of the browser without introducing a
  queue system.
- **Relevant files:** `backend/app/api/routes.py`,
  `backend/app/services/ingestion.py`, `frontend/lib/api.ts`, and
  `frontend/components/job-overview.tsx`.
- **Alternatives:**
  - A synchronous POST would remain open for the complete scrape.
  - A durable queue survives restarts but adds deployment infrastructure.
- **Constraints and risks:** Restarting FastAPI can leave a run marked
  `running`.
- **Revisit when:** Runs need recovery, cancellation, or scheduling.

## 8. Application-Only Compose

- **Choice:** Compose runs the backend and frontend but not DynamoDB.
- **Why:** It preserves the owner-managed database boundary.
- **Relevant files:** `compose.yaml`, `backend/Dockerfile`,
  `frontend/Dockerfile`, and `README.md`.
- **Alternatives:**
  - DynamoDB Local supports offline development but creates a second database
    workflow.
- **Revisit when:** Offline development becomes a requirement.
