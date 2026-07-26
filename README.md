# JobData

Private, data-first ingestion for Swiss job-market experiments. The repository
contains three unfiltered source adapters, an idempotent DynamoDB pipeline,
FastAPI operational endpoints, and a basic Next.js count dashboard.

## Source status

Adapters exist for:

- `jobs.ch`
- `jobup.ch`
- `swissdevjobs.ch`

The two JobCloud adapters enumerate unfiltered listing pages until an empty or
repeated page. SwissDevJobs reads the RSS surface once. No title, location,
skill, or profile filters are applied. All three adapters are enabled by
default and require no project-specific authorization flag.

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
`dynamodb:BatchGetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, and
`dynamodb:TransactWriteItems` on this table.

Required environment:

```bash
export AWS_REGION="eu-south-1"
export DYNAMODB_TABLE_NAME="JobData"
```

The normal AWS credential provider chain is used. Never commit AWS credentials
or expose them to the frontend.

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
| `SCRAPER_ENABLED_SOURCES` | all three names | Comma-separated source selection |
| `SCRAPER_CONTACT` | unset | Truthful operator contact appended to user agent |
| `SCRAPER_REQUESTS_PER_SECOND` | `1` | Process-local request rate |
| `SCRAPER_MAX_RETRIES` | `3` | Transient retry count |
| `SCRAPER_RETRY_BACKOFF_SECONDS` | `1` | Exponential-backoff base |
| `SCRAPER_CONNECT_TIMEOUT_SECONDS` | `5` | Connection timeout |
| `SCRAPER_READ_TIMEOUT_SECONDS` | `20` | Read timeout |
| `SCRAPER_MAX_PAGES` | `2000` | Fail-loud pagination circuit breaker |
| `SCRAPER_SOURCE_MAX_WORKERS` | `3` | Parallel source workers |
| `API_CORS_ORIGINS` | `http://localhost:3000` | Allowed dashboard origins |

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
- `POST /api/v1/ingestion/runs`
- `GET /api/v1/ingestion/runs/{run_id}`

The ingestion POST creates a persisted run and returns `202 Accepted`
immediately. The backend executes every source in `SCRAPER_ENABLED_SOURCES` in
the background. Query the returned run ID to observe its status.

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
the totals when the run finishes. It never connects to DynamoDB directly.

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

“All jobs” means all distinct source IDs exposed by an enabled, implemented
public listing surface during a successful run. It does not include
authenticated, hidden, personalized, expired, or otherwise restricted records.

Re-running ingestion updates `last_seen_at`, provenance, content hash, and raw
payload for an existing source ID. It does not create another occurrence.
Missing listings are not marked inactive after one run; a source-aware
multi-run inactivity policy has not been implemented yet.
