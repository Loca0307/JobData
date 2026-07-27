# AGENTS.md

## Dev comments

- As I am using this project to understand better things, implememt the features using the best practices but as simply as possible, and add comments on the most complicated or domain specific parts of the code.

## Project Overview

JobData is a private, data-first job-market ingestion and analysis platform.
It is inspired by the scraping foundation of the neighboring `JobFinder`
project, but it is not a user-facing job-search or recommendation product.

The first phase must:

1. Collect as much useful job-posting data as is technically
   reasonable from major job boards, ATS platforms, and company career pages.
2. Normalize the data without discarding the original source payload.
3. Deduplicate repeated listings while preserving source provenance.
4. Store jobs in a DynamoDB table
   configured and provisioned by the project owner.
5. Expose operational and data-access endpoints through FastAPI.

Later phases may add analysis, reporting, enrichment, and a private dashboard
through a React/Next.js frontend. Do not assume the final analysis workflow
until it is explicitly defined.


## Preferred Technology Stack

- Backend: Python, FastAPI, Pydantic
- AWS access: boto3
- Database: DynamoDB
- HTTP scraping: HTTPX or Requests with shared retry, timeout, and throttling
  policies
- HTML parsing: BeautifulSoup
- Browser automation: Playwright only when necessary
- Scheduling/workers: keep interfaces scheduler-neutral until a deployment
  approach is chosen
- Backend dependency management: `uv` preferred
- Testing: pytest with recorded or synthetic fixtures; live tests must be
  opt-in
- Frontend: Next.js, React, TypeScript
- Frontend package management: npm
- Local development: Docker/Docker Compose 

Do not introduce a new framework or infrastructure dependency without a clear
need and an entry in `CHOICES.md`.

## Intended Repository Structure

```text
backend/
  app/
    api/              # FastAPI routes and dependencies
    core/             # settings, logging, and shared policies
    db/               # DynamoDB client, repositories, and item builders
    models/           # internal domain models
    schemas/          # API and normalized-data contracts
    services/         # ingestion, normalization, deduplication, enrichment
    scrapers/
      sources/        # one adapter per job board/source family
      ats/            # reusable ATS adapters
    workers/          # scrape-run and scheduling entry points
  tests/
frontend/
  app/
  components/
  lib/
  types/
AGENTS.md
ARCHITECTURE.md
CHOICES.md
README.md
```

Create directories only when they are needed; preserve clear boundaries even
if the initial implementation is smaller.

## Core Data Model

The canonical job contract should support, when available:

- stable internal job ID
- source name, source type, source job ID, source URL, and apply URL
- title, company name, company identifiers, and company website
- full description plus separately parsed responsibilities and requirements
- locations, country/region, and raw location text
- workplace type: remote, hybrid, on-site, or unknown
- employment type, schedule, contract type, occupation/category, and seniority
- salary minimum, maximum, currency, period, and raw salary text
- required and preferred skills, education, experience, certifications, and
  languages
- benefits
- posting, expiry, first-seen, last-seen, scraped, and updated timestamps
- listing status and evidence used to mark a job inactive
- source-specific metadata
- schema/parser version
- raw source payload or a lossless reference to it
- content hash and deduplication identifiers

Do not invent missing values. Use explicit `unknown`/`null` states and retain
the raw evidence needed for future reprocessing.

Store scrape-run metadata separately, including source, query/partition,
timestamps, counts, retries, parser version, warnings, errors, and completion
status. DynamoDB keys and indexes must be isolated behind repository
interfaces so the table design can evolve without leaking into scrapers or API
routes.

## Scraping Architecture

- Every source adapter must implement a shared scraper contract and emit
  source records or normalized job objects; it must never write directly to
  DynamoDB.
- Keep fetching, parsing, normalization, deduplication, and persistence as
  separate stages.
- Preserve both canonical normalized fields and raw source data.
- Reuse adapters for common ATS platforms such as Greenhouse, Lever, Workday,
  SmartRecruiters, Teamtailor, and Personio instead of creating company-only
  scrapers when possible.
- Treat major aggregators and job boards as independent adapters. Candidate
  sources include LinkedIn, Indeed, Glassdoor, Monster, ZipRecruiter, Dice,
  StepStone, jobs.ch/JobCloud, and relevant national boards.
- Make source coverage configuration-driven. Adding or disabling a source
  should not require changes to orchestration or API code.
- Apply per-source timeouts, bounded concurrency, retries with backoff and
  jitter, rate limits, pagination limits, and circuit-breaking behavior.
- Identify the scraper honestly with an appropriate user agent/contact where
  required. Never rotate identities to evade controls.
- Fail loudly on unexpected page/schema changes. A parser failure must not be
  reported as a valid empty result.
- Isolate source failures: one failed source must not discard successful data
  from other sources.
- Make persistence idempotent. Re-running the same scrape must update sightings
  and provenance rather than create uncontrolled duplicates.
- Deduplicate conservatively. Preserve every source occurrence and never merge
  jobs solely because their titles are similar.
- Do not mark a job inactive after one missing observation. Use a documented
  source-aware policy.

## DynamoDB Rules

- Read connection settings from environment variables. At minimum support the
  AWS region, table name, and an optional endpoint URL for DynamoDB Local.
- Use the normal AWS credential provider chain. Never commit credentials,
  account IDs, table ARNs, or secrets.
- Validate required configuration at startup and provide actionable errors.
- Use batch operations where appropriate, handle unprocessed items, and make
  retries safe.
- Avoid scans in production request paths. Design access patterns before keys
  or secondary indexes and record the decision in `CHOICES.md`.
- Keep DynamoDB serialization and key construction in `backend/app/db/`.
- Do not create or mutate the table automatically in production. A local-only
  bootstrap helper is acceptable if clearly guarded and documented.
- Tests must use fakes, mocks, or DynamoDB Local and must never contact the
  owner’s real table by default.

## FastAPI Backend

- Keep route handlers thin. Put orchestration and business logic in services,
  and persistence in repositories.
- Separate operational ingestion endpoints from read/query endpoints.
- Use typed request/response schemas and a versioned API prefix.
- Provide health/readiness endpoints that do not trigger scrapes.
- Long-running, multi-source ingestion must not hold an HTTP request open.
  Represent it as a scrape run with observable status and a worker entry point.
- Use structured logs with run ID, source, page/partition, duration, counts,
  and error category. Do not log credentials or unnecessarily expose personal
  data.
- Add pagination and bounded query limits to data endpoints.

## Frontend

- The Next.js/React frontend is initially a shell for future private data
  analysis, not a public job-search interface.
- Do not build speculative dashboards or analytics until requirements are
  provided.
- When frontend work begins, keep API access in a typed client layer and keep
  analytical transformations outside presentation components.
- Design for large datasets: server-side filtering, pagination, and aggregation
  rather than downloading the full DynamoDB dataset to the browser.
- Do not expose AWS credentials or direct DynamoDB access to the browser.

## Quality and Testing

- Add unit tests for every parser using sanitized, versioned fixtures.
- Add contract tests for the shared scraper interface and normalized schema.
- Test pagination, duplicate pages, malformed records, partial failures,
  retries, throttling, disappearing jobs, and idempotent writes.
- Network tests against live job sites must be explicitly marked and disabled
  by default.
- Do not make ordinary CI or local test runs depend on third-party availability.
- Add regression fixtures before fixing parser breakage.
- Use timezone-aware UTC timestamps internally.
- Type-check and lint both backend and frontend code using the tools configured
  in the repository.
- Run the relevant tests after every implementation change and report anything
  that could not be verified.


## Documentation Requirements

### `ARCHITECTURE.md`

Keep `ARCHITECTURE.md` current with the implementation. It must begin with a
concise list of the technologies and task-specific libraries actually in use.

For every completed feature:

- add or update a section named after the feature;
- briefly describe the end-to-end flow in bullet points;
- cite every important implementation and test file using repository-relative
  paths in backticks;
- state relevant inputs, outputs, persistence interactions, and failure
  behavior;
- describe only what exists in code, not planned behavior.

A feature is not complete until its architecture entry is updated in the same
change. If the implementation changes, update the existing section rather than
adding a contradictory one.

### `CHOICES.md`

Keep `CHOICES.md` current with meaningful architectural, data-model,
efficiency, compliance, and dependency decisions.

For every decision:

- state the selected option and its present rationale;
- list the principal alternatives in bullet points with a brief trade-off for
  each;
- note constraints, risks, or conditions that would justify revisiting it;
- cite relevant repository-relative files when the decision is embodied in
  code.

Do not record trivial style preferences. A feature that introduces a meaningful
choice is not complete until the choice is documented in the same change.

## Codex Working Rules

1. Inspect the existing implementation and tests before proposing new
   abstractions. Use the neighboring `JobFinder` project only as a reference;
   do not copy its user-facing or Terraform assumptions.
2. Make the smallest coherent change that advances the requested feature.
3. Preserve source independence and data provenance.
4. Never add Terraform or provision the owner’s AWS resources.
5. Never claim a source is supported until its adapter, fixtures, tests,
   failure handling, and architecture documentation exist.
6. Do not silently weaken rate limits, compliance checks, deduplication, raw
   data retention, or test coverage for speed.
7. Update `ARCHITECTURE.md` and `CHOICES.md` as part of the implementation,
   not as deferred cleanup.
8. Update `README.md` whenever setup, environment variables, commands, or
   externally visible behavior changes.
9. Do not commit generated files, credentials, real scraped datasets, or
    copyrighted page dumps. Use minimal sanitized fixtures.
10. Clearly report assumptions, tests run, and any source behavior that could
    not be verified.

