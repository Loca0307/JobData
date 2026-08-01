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

## 9. Storage-Independent Analysis Core

- **Choice:** Begin analysis as pure functions over `NormalizedJob` objects,
  with typed summary results and no direct DynamoDB or FastAPI dependency.
- **Why:** It creates a reusable analysis boundary while the required
  production access patterns and reports are still undefined.
- **Relevant files:** `backend/app/analysis/models.py`,
  `backend/app/analysis/summary.py`, and `backend/tests/test_analysis.py`.
- **Alternatives:**
  - Reading DynamoDB directly inside each calculation is immediately usable
    with stored data but couples analysis to table keys and may require scans.
  - Adding a dataframe library provides richer exploration but is unnecessary
    for the current categorical summaries.
- **Constraints and risks:** Pure calculations still require a caller to load
  bounded input. The demand-map endpoint provides one such caller.
- **Revisit when:** A concrete report or large-dataset access pattern is
  defined.

## 10. Cached Full-Table Analysis Scan

- **Choice:** Scan all normalized job occurrences on a demand-map request,
  retain their title/location data in the backend process for five minutes,
  and filter that complete cached list for each role search.
- **Why:** The map should reflect every stored job, including words in longer
  titles. The short cache makes repeated searches cheap while keeping the
  implementation and stored data model simple.
- **Relevant files:** `backend/app/db/repositories.py`,
  `backend/app/analysis/demand_map.py`,
  `backend/app/api/routes.py`, and `backend/tests/test_repository.py`.
- **Alternatives:**
  - A title-term DynamoDB index is cheaper to query at scale but adds write
    amplification, migration work, and can omit records when indexing rules
    change.
  - A search service supports richer full-text queries but adds infrastructure
    that the current use case does not justify.
  - Pre-aggregating only known roles is cheaper to query but prevents users
    from choosing their own title words.
- **Constraints and risks:** DynamoDB charges for the full scan once per
  five-minute cache window per backend process. Results may be stale for up to
  five minutes, and the complete projected title/location set consumes backend
  memory. The cache is invalidated by ingestion writes in the same process.
- **Revisit when:** The table or number of backend processes makes scan cost,
  latency, or memory use material. A purpose-built index or search service
  would then be appropriate.

## 11. Published Canton Geometry and Cached City Geocoding

- **Choice:** Render the published 2026 Swiss Maps canton TopoJSON with D3 Geo
  and TopoJSON Client, resolve common cities from a small server-side list, and
  resolve other city strings through the official Swiss geo.admin.ch location
  service with an in-memory LRU cache.
- **Why:** The normalized records already contain city text. Server-side
  cached resolution places small towns without sending job data to the browser.
  Sharing one geographic projection between the canton geometry and city dots
  keeps them aligned and replaces the former approximate hand-drawn outline.
  The separate aggregated list shows full canton names and summed counts;
  same-named cities are not presented as separate list rows.
- **Relevant files:** `backend/app/analysis/demand_map.py`,
  `backend/app/analysis/geocoding.py`,
  `frontend/lib/swiss-map.ts`,
  `frontend/lib/swiss-map.test.ts`,
  `frontend/components/demand-map.tsx`, and
  `frontend/app/globals.css`.
- **Alternatives:**
  - A static image is smaller to implement but makes it harder to guarantee
    that longitude/latitude dots use the exact same projection.
  - A full map library provides pan, zoom, and tiles but adds weight and
    interaction that the current view does not need.
  - A complete bundled Swiss municipality dataset removes the network
    dependency but requires maintaining a larger local data asset.
- **Constraints and risks:** The canton data and projection libraries add
  frontend bundle weight and require the source attribution documented in
  `README.md`. First-time resolution of an uncommon city depends on
  geo.admin.ch availability. Only the normalized location string is sent.
  Unknown towns, broad regions, and remote-only strings remain unmapped.
- **Revisit when:** Offline operation is required, geocoder latency becomes
  material, or the map needs detailed geographic interaction.

## 12. Reviewed Local Job-Title Aliases

- **Choice:** Expand the existing five-minute analysis projection with English
  search terms from a bundled catalog of 30 reviewed German, French, Italian,
  and English job-title families. Match aliases only as normalized whole words
  or phrases and retain the existing word-prefix search over the expansion.
- **Why:** This gives common multilingual titles useful English search behavior
  without changing stored or displayed titles, requiring re-ingestion, calling
  a billable service, or operating a taxonomy importer. Applying the catalog
  during cache construction also makes existing DynamoDB items work immediately.
- **Relevant files:** `backend/app/analysis/title_aliases.py`,
  `backend/app/analysis/data/job_title_aliases.json`,
  `backend/app/db/repositories.py`, and
  `backend/tests/test_title_aliases.py`.
- **Alternatives:**
  - Amazon Translate or another hosted translator covers arbitrary titles but
    needs credentials, quotas, network access, and potentially billable usage.
  - ESCO provides a much broader taxonomy but adds importer, refresh, review,
    persistence, and query-resolution complexity.
  - Offline neural translation avoids service charges but increases container
    size, memory use, model downloads, and deployment maintenance.
  - Semantic embeddings improve recall but add opaque matching and unnecessary
    infrastructure for the current short-title search.
- **Constraints and risks:** The list is a practical starter catalog, not an
  official ranking or a full translation system. Unlisted titles fall back to
  literal matching, Romansh is not covered, and maintainers must review aliases
  before adding them. A process restart or cache rebuild is required after a
  catalog deployment.
- **Revisit when:** Measured misses justify a larger reviewed catalog or the
  operational value of arbitrary translation outweighs its cost and complexity.
