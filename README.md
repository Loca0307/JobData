# JobData

Private, data-first ingestion for Swiss job-market experiments. The repository
contains broad job-board adapters, reusable company ATS adapters, an
idempotent DynamoDB pipeline, FastAPI operational endpoints, and a basic
Next.js count dashboard.

## Source status

Adapters exist for:

- `jobs.ch`
- `jobup.ch`
- `swissdevjobs.ch`
- configured company career sites using Greenhouse or Lever

The two JobCloud adapters enumerate unfiltered listing pages until an empty or
repeated page and then read each job's public JobPosting JSON-LD. SwissDevJobs
reads the RSS feed and each public embedded detail record. No title, location,
skill, or profile query is sent to those sources. Before persistence, a shared
territory gate keeps only jobs positively identified as being in Switzerland.

Each DynamoDB `job_occurrence` stores canonical fields in the
`normalized_job` map and the complete source evidence in the `raw_payload`
map, with no second raw-payload copy nested inside the normalized data.
The teaching-oriented adapters map only straightforward core fields such as
title, company, location, description, work type, salary text, languages,
URLs, dates, and source ID. Other publisher fields remain in `raw_payload`.
Unknown values stay null or empty and undisclosed salaries are not estimated.

### Company career sites

Company careers pages often publish their vacancies through an applicant
tracking system (ATS). JobData supports the public Greenhouse Job Board API and
the public Lever Postings API. It creates one scraper per configured company,
so each company has its own run result and stable source name. It does not
auto-detect ATS platforms or fall back to browser automation.

The versioned catalog is
`backend/app/scrapers/company_targets.json`. It contains the reviewed Swiss
test targets and can be extended using the fields for each ATS:

```json
{
  "targets": [
    {
      "id": "example-greenhouse",
      "company_name": "Example Greenhouse AG",
      "careers_url": "https://example.com/careers",
      "ats": "greenhouse",
      "board_token": "example"
    },
    {
      "id": "example-lever",
      "company_name": "Example Lever AG",
      "careers_url": "https://example.org/jobs",
      "ats": "lever",
      "site": "example",
      "region": "eu"
    }
  ]
}
```

The `id` must remain stable because it produces the source name, for example
`company:example-greenhouse`. Enable that exact name in
`SCRAPER_ENABLED_SOURCES`. Greenhouse's `board_token` is the segment used by
its public board URL. Lever's `site` is its public site token and `region` is
either `global` or `eu`. The application validates every catalog entry before
starting a run. Use `SCRAPER_COMPANY_TARGETS_FILE` only when a deployment needs
a different catalog path.

Each ATS response is normalized into the existing common job fields while the
complete source object and target configuration are retained in `raw_payload`.
Greenhouse prospect/general-interest posts are excluded. Lever pagination is
bounded and repeated pages fail loudly. Authenticated, blocked, or unsupported
career systems remain unsupported rather than being bypassed.

Global ATS boards are filtered during ingestion. Structured country fields take
precedence; otherwise a reviewed set of Swiss country, canton, and major city
names supplies conservative evidence. Only records classified as `CH` are
stored. Foreign and unknown locations are counted as `jobs_filtered` in the
scrape run and are not counted as updates. This intentionally favors a clean
Swiss dataset over guessing that an ambiguous remote or unknown location is
Swiss.

The operator remains responsible for ensuring each enabled source may be
collected in the intended jurisdiction and use case. The application does not
log in, bypass access controls, evade anti-bot measures, or turn an HTTP access
denial into a successful result. Fixture-driven tests work without live access.

## DynamoDB table

Create the table yourself with:

- partition key: `PK` (String)
- sort key: `SK` (String)
- billing/capacity mode: your choice
- no secondary index required for the current endpoints

The application never creates or mutates table configuration. Its AWS identity
needs `dynamodb:DescribeTable`, `dynamodb:GetItem`,
`dynamodb:BatchGetItem`, `dynamodb:Scan`, `dynamodb:PutItem`,
`dynamodb:UpdateItem`, and
`dynamodb:TransactWriteItems` on this table.

Required environment:

```bash
export AWS_REGION="eu-south-1"
export DYNAMODB_TABLE_NAME="JobData"
```

For local development, the backend reads these settings from the project-root
`.env` regardless of whether the command starts in the root or `backend/`
directory. It also loads that file without overriding variables already
exported by the shell, allowing boto3's normal AWS credential provider chain to
use local `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and optional
`AWS_SESSION_TOKEN` values. Never commit AWS credentials or expose them to the
frontend.

## Backend

Python 3.12 is required. Install with either pip:

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

or `uv`:

```bash
cd backend
uv sync
```

Configure the collector:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SCRAPER_ENABLED_SOURCES` | three boards and four catalogued companies | Comma-separated board and `company:<id>` source selection |
| `SCRAPER_COMPANY_TARGETS_FILE` | bundled empty catalog | Path to the validated company target JSON catalog |
| `SCRAPER_CONTACT` | unset | Truthful operator contact appended to user agent |
| `SCRAPER_REQUESTS_PER_SECOND` | `1` | Process-local request rate |
| `SCRAPER_MAX_RETRIES` | `3` | Transient retry count |
| `SCRAPER_RETRY_BACKOFF_SECONDS` | `1` | Exponential-backoff base |
| `SCRAPER_CONNECT_TIMEOUT_SECONDS` | `5` | Connection timeout |
| `SCRAPER_READ_TIMEOUT_SECONDS` | `20` | Read timeout |
| `SCRAPER_MAX_PAGES` | `2000` | Fail-loud pagination circuit breaker |
| `SCRAPER_SOURCE_MAX_WORKERS` | `3` | Parallel source workers |
| `API_CORS_ORIGINS` | `http://localhost:3000` | Allowed dashboard origins |

### Multilingual title search

Enter role searches in English. The backend keeps every job title exactly as
published, but its five-minute analysis cache adds English search terms for a
reviewed starter catalog of 30 common job families. Whole German, French,
Italian, and English title phrases are supported. Matching ignores casing,
accents, punctuation, and repeated whitespace; the existing word-prefix search
then supports queries such as `plumb` for `plumber`.

There is no translation API, model download, configuration, or DynamoDB
migration. Existing jobs gain the behavior after the backend restarts or its
analysis cache is rebuilt. Unlisted titles use the original literal-title
search, so this is intentionally not a general translation system and does not
currently cover Romansh.

Maintainers extend `backend/app/analysis/data/job_title_aliases.json` by adding
reviewed whole-title phrases to the appropriate language list. Every family
must contain non-empty `de`, `en`, `fr`, and `it` lists. Keys must be unique,
and the same normalized alias cannot belong to different families. Run the
backend tests before deploying catalog changes; malformed catalogs fail loudly
instead of silently disabling matching.

Run one complete ingestion:

```bash
cd backend
.venv/bin/python -m app.workers.scrape_all
```

Start the API:

```bash
cd backend
.venv/bin/uvicorn app.api.main:app --reload
```

Endpoints:

- `GET /api/v1/health`
- `GET /api/v1/readiness`
- `GET /api/v1/stats/jobs`
- `GET /api/v1/analysis/demand-map?role=engineer`
- `POST /api/v1/ingestion/runs`
- `GET /api/v1/ingestion/runs/{run_id}`

The ingestion POST creates a persisted run and returns `202 Accepted`
immediately. The backend executes every source in `SCRAPER_ENABLED_SOURCES`,
including configured company sources, in the background. Query the returned
run ID to observe its status. Run responses report jobs seen, filtered as
foreign/unknown, created, and updated. The dashboard labels the filtered count
as “Outside / unknown.”

The demand-map endpoint scans all normalized job occurrences and caches their
title/location data plus local English search terms in the backend for five
minutes. Each English role search filters the full cached data set. Common
cities resolve locally; other city coordinates
use the official Swiss geo.admin.ch address and municipality indexes and are
cached in memory. While ingestion is active, the map keeps using its current
snapshot instead of rescanning after every stored job; completing the run
invalidates that snapshot so the next search loads the finished data. Full
addresses retain their postal code and municipality in
the lookup so a street name cannot be fuzzily matched to unrelated map
infrastructure.
The response includes explicit unmapped counts. The frontend shows city-level
map dots after a role is submitted; selecting a dot opens that location's job
count in the details panel. The expandable list separately assigns every
mapped city to its containing canton, adds the city counts together, and labels
each row with the canton's full name. A narrow boundary tolerance accounts for
simplification in the published polygons around Swiss border towns. The dots
and canton totals use the same verified polygon assignment, so a nearby foreign
geocode is not drawn as an unlisted dot. The panel reports how many total
matches have no verified canton. City-level results remain on the map and are
not separate rows in the canton list. No role is searched automatically on
first load.

The canton geometry is provided by the `swiss-maps` package from
Bundesamt für Statistik (BFS), GEOSTAT data.

Run backend checks:

```bash
cd backend
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
```

Ordinary tests use sanitized fixtures and fakes. They never contact live job
sites or the owner’s AWS account.

## Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Open `http://localhost:3000`. Set `NEXT_PUBLIC_API_BASE_URL` if FastAPI is not
running at `http://localhost:8000`.

Production checks:

```bash
cd frontend
npm run lint
npm run build
```

The dashboard reads aggregate counts and run status through FastAPI. “Run all
scrapers” starts every enabled adapter, polls the returned run ID, and refreshes
the totals when the run finishes. Alongside the three job-board totals, the
dashboard shows one Company ATS total formed from every configured
`company:<id>` source counter. The role-demand map plots recognized Swiss cities
from the bounded backend cache without downloading all jobs or using an external
map service. Existing jobs appear after the cache is rebuilt; no re-ingestion is
required. The frontend never connects to DynamoDB directly.

## Docker Compose

Compose runs only the FastAPI backend and Next.js frontend. It does not run,
create, or configure DynamoDB.

Create the ignored root `.env` file beside `compose.yaml`:

```bash
cp .env.example .env
```

Use `aws configure export-credentials --profile docker-role --format env` to
obtain temporary assumed-role values, then replace the three credential
placeholders in `.env`. Keep the non-secret settings aligned with the
owner-created table:

```dotenv
AWS_ACCESS_KEY_ID=<temporary role access key>
AWS_SECRET_ACCESS_KEY=<temporary role secret key>
AWS_SESSION_TOKEN=<temporary role session token>
AWS_REGION=eu-south-1
DYNAMODB_TABLE_NAME=JobData
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Do not commit `.env`; it is ignored by Git. Temporary role credentials expire,
so refresh those three values and recreate the backend when necessary. Start
both services with:

```bash
docker compose up --build
```

The dashboard is available at `http://localhost:3000` and FastAPI at
`http://localhost:8000`. On AWS compute with an attached IAM role, omit the
static credential variables and let boto3 use the role.

## Collection semantics

"All jobs" means all distinct source IDs exposed by an enabled, implemented
public listing surface or configured ATS board during a successful run that
also have positive Swiss-territory evidence. It does not include foreign or
unknown locations, authenticated, hidden, personalized, expired, or otherwise
restricted records.
Every occurrence also makes one detail request using the same per-source rate
limit, so a complete run is deliberately slower than summary-only collection.

Re-running ingestion updates `last_seen_at`, provenance, content hash, and raw
payload for an existing source ID. It does not create another occurrence.
Records collected before detail enrichment remain summary-only until the next
successful run updates them.
HTTP retries, DynamoDB counter-conflict retries, and duplicate-race handling
remain because they protect the source sites and stored counts. The surrounding
parsing code is intentionally kept small enough to follow as a learning
pipeline.
Missing listings are not marked inactive after one run; a source-aware
multi-run inactivity policy has not been implemented yet.

The Switzerland-only gate applies to future ingestion writes and updates. It
does not automatically delete foreign occurrences stored by an older version;
automatic deletion would conflict with the conservative inactivity policy and
owner-managed table boundary. Historical cleanup must therefore be performed
as a separate, explicitly reviewed operation.
