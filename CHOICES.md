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

- **Choice:** Reuse the public JobCloud page state used by the existing
  JobFinder implementation and the public SwissDevJobs RSS feed. Do not use
  browser automation, private APIs, login state, or controls-bypassing
  techniques.
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
- **Constraints and risks:** Public availability is not permanent permission.
  Operators must review current terms and robots directives before scaled
  runs. The adapters stop on access errors and do not evade rate limits or
  anti-bot measures.
- **Revisit when:** A board offers an official API or feed, removes public
  access, changes its terms/robots policy, or the listing payload schema
  changes.
