# JobData

Private, data-first collection and analysis infrastructure for Swiss job-market
data.

## Current scope

The backend currently provides unfiltered source adapters for:

- `jobs.ch`
- `jobup.ch`
- `swissdevjobs.ch`

Each adapter emits a `SourceRecord` containing both a normalized job and the
original source payload. The adapters do not write to DynamoDB directly.
Persistence, scrape-run workers, and API endpoints will be added as separate
pipeline stages.

`jobs.ch` and `jobup.ch` are collected page by page from their public,
unfiltered English listing pages until the source returns an empty page or
repeats a page. SwissDevJobs is collected once from its public RSS feed. No
title, location, skill, or user-profile filtering is applied.

## Backend setup

Python 3.12 and [`uv`](https://docs.astral.sh/uv/) are expected.

```bash
cd backend
uv sync
```

Set a truthful contact value before live collection:

```bash
export SCRAPER_CONTACT="mailto:owner@example.com"
```

The user agent, timeouts, retry policy, rate limit, and pagination safety bound
can be configured:

| Variable | Default | Purpose |
| --- | ---: | --- |
| `SCRAPER_USER_AGENT` | `JobDataBot/0.1 ...` | Identifies the collector |
| `SCRAPER_CONTACT` | unset | Appended contact information |
| `SCRAPER_CONNECT_TIMEOUT_SECONDS` | `5` | Connection timeout |
| `SCRAPER_READ_TIMEOUT_SECONDS` | `20` | Response-read timeout |
| `SCRAPER_MAX_RETRIES` | `3` | Retry count for transient failures |
| `SCRAPER_RETRY_BACKOFF_SECONDS` | `1` | Exponential-backoff base |
| `SCRAPER_REQUESTS_PER_SECOND` | `1` | Process-local source request rate |
| `SCRAPER_MAX_PAGES` | `2000` | Fails a run that does not exhaust first |

Run the offline tests and lint checks:

```bash
uv run pytest
uv run ruff check .
```

Ordinary tests use only sanitized fixtures and never contact a job board.

## Important collection limits

"All jobs" means all records exposed through the implemented public listing
surface during a successful run. It does not imply access to hidden,
authenticated, personalized, expired, or otherwise restricted listings.
Source terms and robots directives must be reviewed before operating the
collector at scale. If a source changes its schema, the adapter raises an error
instead of treating the change as an empty result.
