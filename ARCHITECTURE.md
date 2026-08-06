# Architecture

## Tech Stack

- Python 3.12, FastAPI, Pydantic, pydantic-settings, and python-dotenv
- boto3 and DynamoDB
- HTTPX, Beautiful Soup, and Python XML ElementTree
- pytest, respx, and Ruff
- Next.js, React, TypeScript, ESLint, D3 Geo, TopoJSON Client, and Swiss Maps
- Docker and Docker Compose

## Job Collection

- `backend/app/scrapers/registry.py` constructs the enabled `jobs.ch`,
  `jobup.ch`, `swissdevjobs.ch`, and configured company adapters.
- `backend/app/scrapers/company_targets.json` is the versioned company catalog
  and currently registers Scandit, On, RIVR, and SwissBorg as test targets.
  `backend/app/scrapers/ats/targets.py` validates its stable ID, company, URL,
  ATS discriminator, and Greenhouse or Lever identifiers during API startup
  and before worker collection.
  Catalog targets are enabled through `SCRAPER_ENABLED_SOURCES` using their
  derived `company:<id>` source name.
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
- `backend/app/scrapers/ats/greenhouse.py` reads one company's public
  Greenhouse board with full content, excludes prospect posts, deduplicates job
  IDs, derives Swiss country evidence from reviewed country/place text, and
  emits the remaining vacancies without treating update timestamps as posting
  dates.
- `backend/app/scrapers/ats/lever.py` reads one company's global or EU public
  Lever postings API. It uses bounded `skip`/`limit` pagination, deduplicates
  job IDs, gives the structured posting country precedence over location text,
  and fails on repeated pages or pagination-limit exhaustion.
- Each company is a separate scraper task. Its normalized source name is
  `company:<stable-id>`, while its complete ATS job object and target metadata
  remain in `raw_payload`. A failed target does not fail other companies.
- Both adapters normalize only the core fields used by `NormalizedJob` and
  retain the listing/feed and structured detail objects in `raw_payload`.
  Missing fields remain null. They do not contain the previous large set of
  source-specific extraction helpers.
- Missing listing markers, malformed payloads, mismatched detail identities,
  HTTP failures, and pagination-limit exhaustion fail the affected source
  visibly.
- `backend/tests/test_http.py`, `backend/tests/test_jobcloud.py`,
  `backend/tests/test_swissdevjobs.py`, `backend/tests/test_company_targets.py`,
  `backend/tests/test_greenhouse.py`, `backend/tests/test_lever.py`,
  `backend/tests/test_swiss_territory.py`, and fixtures under
  `backend/tests/fixtures/` cover these workflows without live traffic.

## Normalized Records

- `backend/app/models/jobs.py` defines `NormalizedJob` and `SourceRecord`.
- `NormalizedJob` is the small common representation used by persistence. Its
  optional `country_code` contains an evidence-backed ISO two-letter code;
  missing location evidence remains null.
- `SourceRecord.raw_payload` preserves source evidence for later reprocessing.
- The source name and source job ID identify an occurrence. The implementation
  does not attempt uncertain cross-source vacancy matching.
- Company adapters use `company:<catalog-id>` as the source name and the ATS
  posting ID as the source job ID. The catalog ID must therefore remain stable.

## Ingestion

- `backend/app/services/ingestion.py` creates a scrape run and executes enabled
  sources concurrently.
- `backend/app/core/swiss_territory.py` normalizes structured country values
  and recognizes a reviewed set of Swiss country, canton, and major employment
  centre names used by global ATS location text. Structured ATS country data
  takes precedence over this fallback.
- Each yielded record increments `jobs_seen`, but only records whose normalized
  `country_code` is `CH` are sent to the `IngestionRepository` interface.
  Explicitly foreign and unknown locations are ignored conservatively and
  counted in `jobs_filtered`; they are never counted as updates.
- JobCloud obtains the country from its JobPosting address. SwissDevJobs has no
  country field, so its adapter uses that source's explicit Swiss-vacancy
  contract. Greenhouse and Lever use their normalized location/country
  evidence.
- A source failure does not discard records already stored by that source or
  successful results from other sources.
- Company targets expand into separate sources before the run is created, so
  company-level failures use the same isolation behavior.
- The final run status is completed, partial, or failed.
- `backend/app/workers/scrape_all.py` provides the command-line entry point.
- Its logging formatter supplies default run and source context for records
  emitted outside a source run. `backend/tests/test_worker.py` protects the
  command-line logging setup; `backend/tests/test_ingestion.py` covers partial
  failure, repeat ingestion, Swiss-only persistence, filtered counts, and the
  no-enabled-source case. `backend/tests/test_swiss_territory.py` covers the
  evidence rules without network access.

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
  creates or changes the owner-provisioned table. For local development,
  `backend/app/core/settings.py` loads the project-root `.env` without
  overriding exported environment variables, making the same values available
  to both Pydantic settings and boto3 regardless of the launch directory.
- `backend/tests/test_repository.py` covers IDs, hashing, new and existing
  records, counters, transaction conflicts, and run reads.
- `backend/tests/test_settings.py` verifies root `.env` discovery and
  non-overriding local environment loading.

## API and Dashboard

- `backend/app/api/main.py` configures FastAPI, startup validation, and CORS.
- `backend/app/api/routes.py` exposes health, readiness, aggregate counts,
  scrape-run creation, and scrape-run status endpoints under `/api/v1`.
- The ingestion POST stores a running record, returns `202`, and starts an
  in-process FastAPI background task.
- `frontend/lib/api.ts` is the typed API client.
- `frontend/components/job-overview.tsx` displays the three board occurrence
  counts plus one combined company ATS count, and shows run state—including
  the count excluded as outside/unknown territory. It starts a run, polls every
  two seconds, and refreshes totals when the run finishes.
- `frontend/lib/job-counts.ts` combines every `company:<id>` counter returned
  by the API without coupling the dashboard to the current company catalog;
  `frontend/lib/job-counts.test.ts` covers aggregation and the empty case.
- The frontend never receives AWS credentials or accesses DynamoDB directly.
- `backend/tests/test_api.py` covers the operational API.

## Job Analysis and Demand Map

- `backend/app/analysis/summary.py` calculates descriptive counts from any
  iterable of `NormalizedJob` objects. `backend/app/analysis/models.py`
  defines the typed summary and map outputs.
- `backend/app/db/repositories.py` scans all normalized job occurrences,
  projects only the normalized job and retained raw payload, and keeps the
  resulting title/location list in memory for five minutes. While constructing
  that projection, `backend/app/analysis/title_aliases.py` appends reviewed
  English search terms for whole German, French, Italian, or English title
  aliases from `backend/app/analysis/data/job_title_aliases.json`. Stored and
  displayed source titles are never changed. The cache remains a stable
  snapshot while a scrape run writes records, then successful run finalization
  invalidates it so the next request sees the completed ingestion. This avoids
  repeated full-table scans while ingestion and map requests overlap.
- `GET /api/v1/analysis/demand-map?role=<role>` in
  `backend/app/api/routes.py` filters the complete cached list for every role
  search; it does not truncate the candidate set.
- `backend/app/analysis/demand_map.py` normalizes aliases and queries with the
  same Unicode, accent, punctuation, and whitespace rules. It verifies all
  requested English terms against each expanded search title, supports word
  prefixes such as `medic` matching `medical`, and aggregates matches by city.
  Unknown titles retain literal matching against the original source title.
- `backend/app/analysis/geocoding.py` resolves common cities locally, then uses
  the official Swiss geo.admin.ch address, postal-code, and municipality
  indexes for other location strings. Comma-separated addresses are queried
  with their street, postal code, and municipality while only the municipality
  becomes the map label; broad gazetteer results are excluded to prevent fuzzy
  matches to border markers or infrastructure. Distinct locations for one
  result are resolved with bounded concurrency, and a bounded in-process LRU
  cache avoids repeated lookups. Coordinates are accepted only inside a Swiss
  bounding box.
- `frontend/lib/api.ts` retrieves the typed result.
  `frontend/lib/swiss-map.ts` converts the published 2026 Swiss canton
  TopoJSON into SVG paths and projects job coordinates through the same D3
  geographic projection.
  `frontend/components/demand-map.tsx` renders it as a responsive inline SVG
  map with keyboard-accessible dots and a details panel for the selected city;
  `frontend/app/globals.css` styles the map and its coverage note.
  The same canton polygons assign each mapped city to a canton for the
  expandable canton-only list. Its rows contain explicit full canton names and
  summed counts, never separate city entries. A small edge tolerance compensates
  for simplification at the national border so valid Swiss locations such as
  Thônex remain assigned, while clearly foreign coordinates remain excluded.
  `frontend/lib/swiss-map.ts` returns the verified points and canton totals from
  that single containment pass, so an unverified border-area geocode cannot be
  drawn on the map while being absent from the list. The details panel reports
  both the complete match count and the subset with a verified canton.
  The total uses every title match, including jobs whose location could not be
  mapped.
  `frontend/lib/swiss-map.test.ts`
  verifies that separate cities in the same canton are added together and
  that coordinates outside Switzerland are not assigned to a canton;
  `frontend/app/globals.css` contains the map styling. No map tiles, browser
  geocoding, or client-side job dataset are used.
- A DynamoDB scan failure is returned as an API failure and does not replace
  the existing cache. A failed or invalid geocoding response leaves that job
  explicitly unmapped rather than guessing a coordinate.
- `backend/tests/test_title_aliases.py`, `backend/tests/test_analysis.py`,
  `backend/tests/test_repository.py`, and `backend/tests/test_api.py` cover
  catalog validation, multilingual and whole-phrase matching, literal fallback,
  aggregation, geocoding, scan caching, and the unchanged API response without
  live network access. A malformed bundled catalog fails the projection build
  rather than silently disabling multilingual search.

## Containers

- `backend/Dockerfile` and `frontend/Dockerfile` build the two applications.
- `compose.yaml` runs only FastAPI and Next.js. It does not provision DynamoDB.
- Inputs are the documented environment variables. Outputs are the API on port
  8000 and dashboard on port 3000.
