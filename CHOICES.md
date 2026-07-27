# Architectural Choices

This document records meaningful decisions that are reflected in the
implementation. Each future entry must identify the chosen option, its
rationale, the relevant files, alternatives and their trade-offs, and the
conditions under which the decision should be revisited.

## 1. Application-Managed Infrastructure Boundary

- **Choice:** Keep infrastructure provisioning outside this repository. The
  application will consume an owner-provisioned DynamoDB table through
  configuration.
- **Why:** The project owner will personally configure DynamoDB and explicitly
  does not want Terraform in this project.
- **Relevant files:** `AGENTS.md`
- **Other possibilities:**
  - Terraform could make environments reproducible, but it is explicitly
    outside this repository's scope.
  - AWS CDK or CloudFormation could provision the same resources, but would
    violate the same application/infrastructure boundary.
  - Automatic table creation at application startup would simplify initial
    setup, but risks mutating production infrastructure unexpectedly.
- **Revisit when:** Only if the owner explicitly changes the infrastructure
  policy. Until then, code may document requirements but must not provision
  cloud resources.

## 2. Data-First Private Platform

- **Choice:** Prioritize collection, provenance, normalization, and durable
  storage before user-facing search, recommendations, or analytics.
- **Why:** The first project phase is intended to build a broad job dataset for
  analysis that will be defined later.
- **Relevant files:** `AGENTS.md`
- **Other possibilities:**
  - A user-facing live search could deliver immediate interaction, but would
    optimize for request latency rather than dataset completeness.
  - Building analytics first could validate presentation ideas, but without a
    stable ingestion layer the analysis would rest on incomplete data.
  - Adding AI enrichment during ingestion could produce richer fields, but
    would increase cost and make raw collection harder to reproduce.
- **Revisit when:** A dependable ingestion pipeline and representative dataset
  exist and the owner defines the first analysis workflow.

## 3. Unfiltered Exhaustion-Based Collection with Detail Enrichment

- **Choice:** Collect JobCloud boards from their unfiltered listing page in
  ascending page order until a valid empty page or a page with no unseen source
  IDs is reached. Collect the full SwissDevJobs RSS feed without local
  filtering. For every emitted ID, fetch its public detail page through the
  same rate-limited HTTP client before persistence.
- **Why:** Fixed page counts and user-profile filters from JobFinder would make
  market analysis systematically incomplete. Sequential pagination also
  avoids guessing a total before the source has been inspected and makes the
  exact stopping evidence observable. Listing cards and RSS entries are not
  rich enough for analysis; the detail surfaces provide full descriptions,
  addresses, salary evidence, work terms, skills, seniority, benefits, and
  company metadata while the original summary remains available.
- **Relevant files:** `backend/app/scrapers/jobcloud.py`,
  `backend/app/scrapers/swissdevjobs.py`,
  `backend/tests/test_jobcloud.py`, and
  `backend/tests/test_swissdevjobs.py`
- **Other possibilities:**
  - A fixed number of pages is simpler and bounds cost, but silently truncates
    large result sets.
  - Concurrently requesting a guessed page range is faster, but can over-fetch,
    creates more load, and cannot prove completeness without reliable source
    pagination metadata.
  - Location or keyword partitions could improve recoverability for very large
    sources, but overlapping partitions increase deduplication complexity and
    are unnecessary while the unfiltered listing surface remains enumerable.
  - Persisting listing summaries only is substantially faster, but leaves most
    canonical fields empty and does not satisfy analysis requirements.
  - Fetching detail pages concurrently would reduce elapsed time, but produces
    burstier source traffic and complicates the current source-level throttle.
- **Constraints and risks:** A configurable `SCRAPER_MAX_PAGES` remains as a
  circuit breaker. Reaching it fails the run; it does not produce a false
  completeness claim. A repeated page is treated as exhaustion because some
  sites redirect out-of-range pages back to the last available page. Query
  construction remains source-aware: jobs.ch requires `term=` even for an
  unfiltered request, because it redirects a page-only query back to page one.
  Detail enrichment adds one request per job and therefore makes a complete run
  materially longer. Missing structured fields stay null; raw detail evidence
  is retained for later reprocessing.
- **Revisit when:** A source publishes a supported bulk API/feed, listing
  pagination becomes unstable, a single run exceeds the acceptable recovery
  window, or reliable total-page metadata is exposed.

## 4. Preserve Source Occurrences Before Cross-Source Deduplication

- **Choice:** Scrapers deduplicate only repeated IDs within their own source
  run and emit a lossless `SourceRecord` for every remaining occurrence.
  Use the compact JobFinder-style `NormalizedJob` fields and keep all
  source-specific evidence in one raw payload. `SourceRecord` contains one
  normalized job and one raw payload; its source identity is derived from the
  normalized job rather than copied into both objects. Cross-source merging is
  intentionally deferred to a later service.
- **Why:** Similar titles, companies, and locations are not sufficient proof
  that two postings are identical. Keeping each source occurrence preserves
  provenance and supports future reprocessing. A single identity and raw-data
  location avoids inconsistent duplicate fields and reduces every DynamoDB
  occurrence without losing information.
- **Relevant files:** `backend/app/models/jobs.py`,
  `backend/app/scrapers/jobcloud.py`, and
  `backend/app/scrapers/swissdevjobs.py`
- **Other possibilities:**
  - Title/company/location fingerprints are cheap, but can merge distinct
    vacancies and discard source evidence.
  - Embedding or fuzzy-description similarity can find more duplicates, but
    requires calibrated thresholds and still needs a provenance-aware data
    model.
  - No within-source deduplication preserves literal responses, but pagination
    overlap would produce uncontrolled duplicates during one scrape.
  - Copying source identity and raw payload into both models makes each object
    independently inspectable, but wastes storage and permits contradictory
    values.
  - A wide typed field for every possible source attribute makes individual
    facts easier to query, but most fields remain empty, scraper code becomes
    mapping-heavy, and each new source-specific concept expands the shared
    contract.
- **Constraints and risks:** The compact normalized map is intentionally not a
  complete typed projection of every publisher field. Technologies, benefits,
  structured salary components, expiry dates, company identifiers, and similar
  evidence remain in `raw_payload` and require source-aware reprocessing when
  needed.
- **Revisit when:** The persistence and deduplication services define durable
  occurrence keys, content hashes, and merge/unmerge behavior, or a concrete
  analysis requires an additional field to be promoted into the normalized
  model.

## 5. Public Structured Surfaces with Fail-Loud Parsing

- **Choice:** Implement parsers for the public JobCloud page state used by the
  existing JobFinder implementation, JobCloud JobPosting JSON-LD, the
  SwissDevJobs RSS surface, and its embedded public detail record. Enable
  registered adapters by default without project-specific authorization
  flags. Do not use browser automation, private APIs, login state, or
  controls-bypassing techniques.
- **Why:** These surfaces are simpler, lower-load, and easier to test than
  browser-driven scraping. Removing redundant application flags makes the
  configured scraper command run immediately, while strict shape validation
  and summary/detail identity checks prevent a source redesign or redirect from
  being recorded as a valid job.
- **Relevant files:** `backend/app/scrapers/http.py`,
  `backend/app/scrapers/registry.py`, `backend/app/core/settings.py`,
  `backend/app/scrapers/jobcloud.py`, and
  `backend/app/scrapers/swissdevjobs.py`
- **Other possibilities:**
  - Per-source operator assertion flags create an explicit compliance
    checkpoint, but they duplicate source selection and can leave a correctly
    configured installation with no runnable scrapers.
  - Playwright could render client-side pages, but it consumes more resources
    and is unnecessary for the current structured surfaces.
  - Undocumented internal APIs might be more compact, but are explicitly
    disallowed by current robots directives and are more likely to change.
  - A separate enrichment queue could make detail failures independently
    retryable, but requires durable worker infrastructure that the project has
    not selected.
- **Constraints and risks:** Publisher terms and applicable law can restrict
  collection even when a page is publicly reachable; removing an application
  flag does not grant permission. The operator is responsible for enabling
  only permitted sources. Detail requests use the same GET-only, rate-limited,
  truthfully identified client as listing requests; adapters stop on access or
  schema errors and never evade rate limits, logins, or anti-bot measures.
- **Revisit when:** A board offers an official API or feed, removes public
  access, grants the owner written collection permission, changes its
  terms/robots policy, or the listing payload schema changes.

## 6. Source-Occurrence Identity and Single-Table Persistence

- **Choice:** Use a deterministic hash of source name and source job ID as the
  current internal job ID, and store one lossless source occurrence per item in
  an owner-provisioned DynamoDB table with string `PK` and `SK` keys. Store
  canonical fields once in `normalized_job` and source evidence once in
  `raw_payload`.
- **Why:** The current phase has reliable source identities but no calibrated
  cross-source deduplication rules. Source-scoped identity makes ingestion
  idempotent without guessing that similar ads are the same vacancy.
- **Relevant files:** `backend/app/db/repositories.py`,
  `backend/app/models/jobs.py`, `backend/tests/test_repository.py`, and
  `backend/tests/test_ingestion.py`
- **Other possibilities:**
  - A random UUID would work, but needs an additional lookup before every
    update and makes replay less deterministic.
  - Title/company/location fingerprints can combine boards immediately, but
    risk destructive false merges.
  - One table per entity simplifies item shapes, but adds configuration and
    makes atomic cross-entity updates harder.
- **Constraints and risks:** A source that reuses an ID for a genuinely new
  vacancy would update the old occurrence. Raw payloads, content hashes, and
  run history retain evidence for detection. Cross-source canonical IDs can be
  introduced later without changing scraper contracts.
- **Revisit when:** Deduplication evidence and merge/unmerge rules are defined,
  or a source demonstrates unstable/reused identifiers.

## 7. Transactional Materialized Counters Instead of Scans

- **Choice:** Increment total and per-source counter items transactionally when
  a new occurrence is inserted, use a deterministic request token, and retry
  only explicitly reported transaction conflicts with bounded exponential
  backoff and jitter. Store a latest-run summary item.
- **Why:** The dashboard needs a few exact totals. Materialized counters make
  that request constant-size and avoid expensive full-table scans.
- **Relevant files:** `backend/app/db/repositories.py`,
  `backend/app/api/routes.py`, `frontend/lib/api.ts`, and
  `backend/tests/test_repository.py`
- **Other possibilities:**
  - DynamoDB scans with `Select=COUNT` need no counter writes, but get slower
    and more expensive with dataset size and violate production access rules.
  - A GSI query still reads every matching key and requires extra table
    configuration.
  - Periodic analytics jobs can produce richer aggregates, but add a scheduler
    and delay for a dashboard that currently needs only counts.
  - Serializing all source writes behind a process lock avoids local counter
    conflicts, but discards write concurrency and cannot coordinate multiple
    application instances.
- **Constraints and risks:** Counters are source-occurrence counts, not
  cross-source vacancy counts. Concurrent sources contend on the total counter;
  five application retries bound the delay and then fail loudly rather than
  loop indefinitely. Conditional duplicate races retain their idempotent
  update fallback, while unknown transaction cancellations are not retried.
  Deletion and merge workflows must update counters transactionally when those
  workflows are added.
- **Revisit when:** The dashboard needs historical series, grouped analytics,
  or independently repairable counters at much larger scale.

## 8. Private Operational Next.js Dashboard Through FastAPI

- **Choice:** Put all DynamoDB access behind FastAPI and let a small Next.js
  client fetch aggregate/run status and request ingestion through typed API
  endpoints. Keep the cached repository dependency directly in
  `backend/app/api/routes.py`, and reuse one frontend count-loading function
  for initial load and manual refresh.
- **Why:** It keeps AWS credentials out of the browser and maintains the
  repository/service boundaries required by this data platform.
- **Relevant files:** `backend/app/api/`, `frontend/app/`,
  `frontend/components/job-overview.tsx`, and `frontend/lib/api.ts`
- **Other possibilities:**
  - Direct browser access to DynamoDB removes one service hop, but exposes AWS
    authorization concerns and couples UI code to table keys.
  - Server-rendering the counts is possible, but makes the frontend build and
    runtime more dependent on backend network availability.
  - Running scraper code in Next.js would avoid a backend POST, but would
    duplicate Python ingestion logic and require AWS access in the frontend
    runtime.
  - A charting library could add visuals, but three scalar counts do not
    justify another dependency.
  - A separate API dependency module is useful when many dependency providers
    exist, but one repository constructor does not justify another layer.
- **Constraints and risks:** The dashboard is a private operational shell and
  has no authentication yet. It should only be exposed inside an appropriately
  controlled environment.
- **Revisit when:** Authentication, historical trends, or additional private
  analysis workflows are specified.

## 9. Simple Application-Only Compose Setup

- **Choice:** Use a single-stage frontend Dockerfile and run only the frontend
  and backend in Compose. Connect the backend to the owner-managed AWS
  DynamoDB table through temporary assumed-role values in an ignored root
  `.env` file, and use Python namespace packages without `__init__.py` marker
  files.
- **Why:** This is a small personal learning project, so a direct
  install/build/start image is easier to understand and maintain. DynamoDB
  lifecycle and configuration remain explicitly outside the application.
- **Relevant files:** `.env.example`, `frontend/Dockerfile`,
  `frontend/next.config.ts`, `backend/Dockerfile`, `compose.yaml`, and
  `README.md`
- **Other possibilities:**
  - A multi-stage standalone Next.js image is smaller, but adds build stages,
    copied output directories, users, and health-check machinery.
  - DynamoDB Local in Compose makes offline development possible, but creates a
    second database workflow that the owner does not want here.
  - Provisioning AWS DynamoDB from Compose or application startup could reduce
    setup steps, but violates the owner-managed infrastructure boundary.
  - Traditional Python packages with `__init__.py` markers are more explicit
    and support package initialization hooks, but the current marker files
    contained only docstrings and were removed at the owner's request.
- **Constraints and risks:** Development packages are pruned from the final
  filesystem, but their build layers still make the single-stage image larger
  than an optimized runtime-only image. Local Compose users must refresh
  temporary credentials after expiry. Namespace packages rely on the backend
  application root remaining on Python's import path.
- **Revisit when:** Image size, supply-chain surface, deployment startup time,
  or offline development becomes more important than configuration simplicity.

## 10. In-Process Background Execution for Manually Started Runs

- **Choice:** Persist a running scrape-run record during the POST request,
  return `202 Accepted`, and execute the configured adapters with a FastAPI
  background task. Expose a run-ID GET endpoint for polling.
- **Why:** A full multi-source collection must not hold an HTTP request open.
  The project does not yet have a deployment scheduler or queue, so the
  in-process task is the smallest scheduler-neutral bridge from the private
  dashboard to the existing ingestion service.
- **Relevant files:** `backend/app/api/routes.py`,
  `backend/app/services/ingestion.py`,
  `backend/app/db/repositories.py`, `backend/tests/test_api.py`,
  `backend/tests/test_repository.py`, `frontend/lib/api.ts`, and
  `frontend/components/job-overview.tsx`
- **Other possibilities:**
  - Running ingestion synchronously in the POST is simpler, but ties request
    lifetime to third-party pagination and violates the long-running endpoint
    boundary.
  - A durable queue and separate worker survive API restarts and scale across
    instances, but require deployment infrastructure that has not been chosen.
  - Starting a subprocess from the API reuses the CLI entry point, but makes
    lifecycle, logging, and shutdown behavior harder to control.
- **Constraints and risks:** The running record is durable but its in-process
  task is not. Restarting or terminating the API can leave a run marked
  `running`; concurrent API instances also do not coordinate duplicate manual
  starts. Individual source failures are still isolated and persisted.
- **Revisit when:** Runs need restart recovery, cancellation, scheduled
  execution, cross-instance exclusivity, or a production deployment model is
  selected.
