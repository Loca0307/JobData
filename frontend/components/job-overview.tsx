"use client";

import { useCallback, useEffect, useState } from "react";

import {
  fetchJobCounts,
  fetchScrapeRun,
  startScrapeRun,
  type JobCounts,
  type ScrapeRun,
} from "@/lib/api";

const SOURCE_LABELS: Record<string, string> = {
  "jobs.ch": "jobs.ch",
  "jobup.ch": "jobup.ch",
  "swissdevjobs.ch": "SwissDevJobs",
};

const numberFormatter = new Intl.NumberFormat("en-CH");
const dateFormatter = new Intl.DateTimeFormat("en-CH", {
  dateStyle: "medium",
  timeStyle: "short",
});

export function JobOverview() {
  const [counts, setCounts] = useState<JobCounts | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [activeRun, setActiveRun] = useState<ScrapeRun | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [isStartingRun, setIsStartingRun] = useState(false);

  const loadCounts = useCallback(async (signal?: AbortSignal) => {
    if (signal?.aborted) {
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      setCounts(await fetchJobCounts(signal));
    } catch (loadError) {
      if (loadError instanceof DOMException && loadError.name === "AbortError") {
        return;
      }
      setError(
        loadError instanceof Error
          ? loadError.message
          : "The stored-job totals could not be loaded.",
      );
    } finally {
      if (!signal?.aborted) {
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    queueMicrotask(() => void loadCounts(controller.signal));
    return () => controller.abort();
  }, [loadCounts]);

  useEffect(() => {
    if (!activeRun || activeRun.status !== "running") {
      return;
    }

    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      void fetchScrapeRun(activeRun.run_id, controller.signal)
        .then((run) => {
          setActiveRun(run);
          setRunError(null);
          if (run.status !== "running") {
            void loadCounts();
          }
        })
        .catch((pollError: unknown) => {
          if (
            pollError instanceof DOMException &&
            pollError.name === "AbortError"
          ) {
            return;
          }
          setRunError(
            pollError instanceof Error
              ? pollError.message
              : "The scrape-run status could not be loaded.",
          );
        });
    }, 2000);

    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [activeRun, loadCounts]);

  const runAllScrapers = useCallback(async () => {
    setIsStartingRun(true);
    setRunError(null);
    try {
      setActiveRun(await startScrapeRun());
    } catch (startError) {
      setRunError(
        startError instanceof Error
          ? startError.message
          : "The scraper run could not be started.",
      );
    } finally {
      setIsStartingRun(false);
    }
  }, []);

  const displayedRun = activeRun ?? counts?.latest_run ?? null;
  const isRunActive = activeRun?.status === "running";

  return (
    <main>
      <header className="masthead">
        <div>
          <p className="eyebrow">Private market dataset</p>
          <h1>JobData overview</h1>
          <p className="intro">
            A compact view of the job occurrences currently stored in DynamoDB.
          </p>
        </div>
        <div className="header-actions">
          <button
            className="run-scrapers"
            type="button"
            onClick={() => void runAllScrapers()}
            disabled={isStartingRun || isRunActive}
          >
            {isStartingRun
              ? "Starting…"
              : isRunActive
                ? "Scrapers running…"
                : "Run all scrapers"}
          </button>
          <button
            className="refresh"
            type="button"
            onClick={() => void loadCounts()}
            disabled={isLoading}
          >
            {isLoading ? "Refreshing…" : "Refresh totals"}
          </button>
        </div>
      </header>

      {error ? (
        <section className="notice error" role="alert">
          <div>
            <strong>Data is unavailable</strong>
            <p>{error} Check that the FastAPI backend is running and ready.</p>
          </div>
          <button type="button" onClick={() => void loadCounts()}>
            Try again
          </button>
        </section>
      ) : null}

      {runError ? (
        <section className="notice error" role="alert">
          <div>
            <strong>Scraper action failed</strong>
            <p>{runError} Check the backend logs for the source failure.</p>
          </div>
          <button type="button" onClick={() => void runAllScrapers()}>
            Try again
          </button>
        </section>
      ) : null}

      <section className="summary" aria-label="Stored job totals">
        <article className="total-card">
          <p>Stored job occurrences</p>
          <strong>{counts ? numberFormatter.format(counts.total) : "—"}</strong>
          <span>Distinct source IDs collected across all enabled boards</span>
        </article>

        <div className="source-grid">
          {Object.keys(SOURCE_LABELS).map((source) => (
            <article className="source-card" key={source}>
              <div className="source-mark" aria-hidden="true">
                {SOURCE_LABELS[source].slice(0, 1)}
              </div>
              <div>
                <p>{SOURCE_LABELS[source]}</p>
                <strong>
                  {counts
                    ? numberFormatter.format(counts.by_source[source] ?? 0)
                    : "—"}
                </strong>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="run-card" aria-labelledby="latest-run-heading">
        <div>
          <p className="eyebrow">Ingestion health</p>
          <h2 id="latest-run-heading">Latest run</h2>
        </div>
        {displayedRun ? (
          <div className="run-details">
            <span className={`status ${displayedRun.status}`}>
              {displayedRun.status}
            </span>
            <dl>
              <div>
                <dt>Completed</dt>
                <dd>
                  {displayedRun.completed_at
                    ? dateFormatter.format(
                        new Date(displayedRun.completed_at),
                      )
                    : "Still running"}
                </dd>
              </div>
              <div>
                <dt>Seen</dt>
                <dd>{numberFormatter.format(displayedRun.jobs_seen)}</dd>
              </div>
              <div>
                <dt>New</dt>
                <dd>{numberFormatter.format(displayedRun.jobs_created)}</dd>
              </div>
              <div>
                <dt>Updated</dt>
                <dd>{numberFormatter.format(displayedRun.jobs_updated)}</dd>
              </div>
            </dl>
          </div>
        ) : (
          <p className="empty-run">
            No completed ingestion run has been recorded yet.
          </p>
        )}
      </section>
    </main>
  );
}
