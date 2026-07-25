# Architecture

## Tech Stack

- Python 3.12
- Pydantic and pydantic-settings for normalized contracts and environment
  configuration
- HTTPX for bounded HTTP requests
- Beautiful Soup for sanitized HTML-fragment extraction from RSS descriptions
- Python XML ElementTree for RSS parsing
- pytest for fixture-driven parser and scraper contract tests
- Ruff for linting

## Unfiltered Swiss Job-Board Collection

- The shared contract in `backend/app/scrapers/base.py` requires every adapter
  to yield `SourceRecord` values and prohibits persistence concerns from
  entering the scraper interface.
- `backend/app/models/jobs.py` defines the source occurrence and normalized job
  contracts. Each occurrence contains the complete adapter-level raw payload,
  source identity, parser version, and normalized fields. Missing normalized
  values remain null or explicitly unknown.
- `backend/app/scrapers/jobcloud.py` implements the shared JobCloud listing
  parser used by jobs.ch and jobup.ch. It requests unfiltered listing pages in
  order, removes only repeated source IDs, and stops on a valid empty page or a
  page containing no new IDs.
- JobCloud collection raises `ScrapeError` for missing or malformed embedded
  state, unusable non-empty results, HTTP failures, or reaching the configured
  page safety bound. It never reports a parser failure as a valid empty result.
- `backend/app/scrapers/swissdevjobs.py` fetches the public RSS feed once,
  parses every item without local filtering, removes tracking parameters from
  canonical URLs, extracts labeled description sections, and preserves all RSS
  child values as raw evidence.
- `backend/app/scrapers/http.py` applies a truthful configurable user agent,
  shared request spacing, bounded redirects and timeouts, and retry-after-aware
  retries for transient failures. Inputs are fixed adapter URLs; callers cannot
  inject arbitrary fetch targets.
- `backend/app/scrapers/registry.py` exposes the three implemented adapters
  without coupling future orchestration to source-specific imports.
- Inputs are public listing HTML or RSS XML. Outputs are in-memory
  `SourceRecord` streams. There are no persistence interactions in this
  feature.
- Sanitized fixtures in `backend/tests/fixtures/` and tests in
  `backend/tests/test_jobcloud.py`, `backend/tests/test_swissdevjobs.py`, and
  `backend/tests/test_http.py`, and `backend/tests/test_registry.py` cover
  pagination exhaustion, repeated pages, raw payload retention, malformed
  schemas, deduplication, both JobCloud domains, unfiltered RSS ingestion,
  throttling, and transient retries.
