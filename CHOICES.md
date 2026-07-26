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

## 3. Unfiltered Exhaustion-Based Source Collection

- **Choice:** Collect JobCloud boards from their unfiltered listing page in
  ascending page order until a valid empty page or a page with no unseen source
  IDs is reached. Collect the full SwissDevJobs RSS feed without local
  filtering.
- **Why:** Fixed page counts and user-profile filters from JobFinder would make
  market analysis systematically incomplete. Sequential pagination also
  avoids guessing a total before the source has been inspected and makes the
  exact stopping evidence observable.
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
- **Constraints and risks:** A configurable `SCRAPER_MAX_PAGES` remains as a
  circuit breaker. Reaching it fails the run; it does not produce a false
  completeness claim. A repeated page is treated as exhaustion because some
  sites redirect out-of-range pages back to the last available page.
- **Revisit when:** A source publishes a supported bulk API/feed, listing
  pagination becomes unstable, a single run exceeds the acceptable recovery
  window, or reliable total-page metadata is exposed.

## 4. Preserve Source Occurrences Before Cross-Source Deduplication

- **Choice:** Scrapers deduplicate only repeated IDs within their own source
  run and emit a lossless `SourceRecord` for every remaining occurrence.
  Cross-source merging is intentionally deferred to a later service.
- **Why:** Similar titles, companies, and locations are not sufficient proof
  that two postings are identical. Keeping each source occurrence preserves
  provenance and supports future reprocessing.
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
- **Revisit when:** The persistence and deduplication services define durable
  occurrence keys, content hashes, and merge/unmerge behavior.

## 5. Public Structured Surfaces with Fail-Loud Parsing

- **Choice:** Implement parsers for the public JobCloud page state used by the
  existing JobFinder implementation and the SwissDevJobs RSS surface, but keep
  every live adapter disabled until the operator has explicit publisher
  authorization. Do not use browser automation, private APIs, login state, or
  controls-bypassing techniques.
- **Why:** These surfaces are simpler, lower-load, and easier to test than
  browser-driven scraping. Strict shape validation prevents a source redesign
  from being recorded as zero available jobs.
- **Relevant files:** `backend/app/scrapers/http.py`,
  `backend/app/scrapers/jobcloud.py`, and
  `backend/app/scrapers/swissdevjobs.py`
- **Other possibilities:**
  - Playwright could render client-side pages, but it consumes more resources
    and is unnecessary for the current structured surfaces.
  - Undocumented internal APIs might be more compact, but are explicitly
    disallowed by current robots directives and are more likely to change.
  - Detail-page crawling would enrich descriptions, but multiplies request
    volume and should be a separate, source-compliance-reviewed stage.
- **Constraints and risks:** As reviewed on 2026-07-24, JobCloud terms prohibit
  crawlers, scrapers, data-mining tools, and automated access, while
  SwissDevJobs terms prohibit automated website access and third-party
  collection without explicit agreement. Personal or non-commercial use does
  not itself provide that agreement. `backend/app/scrapers/registry.py` and
  `backend/app/core/settings.py` therefore require a separate authorization
  flag for each source. The adapters stop on access errors and never evade rate
  limits or anti-bot measures.
- **Revisit when:** A board offers an official API or feed, removes public
  access, grants the owner written collection permission, changes its
  terms/robots policy, or the listing payload schema changes.

## 6. Source-Occurrence Identity and Single-Table Persistence

- **Choice:** Use a deterministic hash of source name and source job ID as the
  current internal job ID, and store one lossless source occurrence per item in
  an owner-provisioned DynamoDB table with string `PK` and `SK` keys.
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
  a new occurrence is inserted, and store a latest-run summary item.
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
- **Constraints and risks:** Counters are source-occurrence counts, not
  cross-source vacancy counts. Deletion and merge workflows must update them
  transactionally when those workflows are added.
- **Revisit when:** The dashboard needs historical series, grouped analytics,
  or independently repairable counters at much larger scale.

## 8. Read-Only Next.js Dashboard Through FastAPI

- **Choice:** Put all DynamoDB access behind FastAPI and let a small Next.js
  client fetch only the aggregate endpoint.
- **Why:** It keeps AWS credentials out of the browser and maintains the
  repository/service boundaries required by this data platform.
- **Relevant files:** `backend/app/api/`, `frontend/app/`,
  `frontend/components/job-overview.tsx`, and `frontend/lib/api.ts`
- **Other possibilities:**
  - Direct browser access to DynamoDB removes one service hop, but exposes AWS
    authorization concerns and couples UI code to table keys.
  - Server-rendering the counts is possible, but makes the frontend build and
    runtime more dependent on backend network availability.
  - A charting library could add visuals, but three scalar counts do not
    justify another dependency.
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
