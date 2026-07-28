"use client";

import { type FormEvent, useEffect, useState } from "react";

import {
  fetchDemandMap,
  type DemandMapPoint,
  type DemandMapResult,
} from "@/lib/api";

const MAP_WIDTH = 800;
const MAP_HEIGHT = 400;
const MIN_LONGITUDE = 5.8;
const MAX_LONGITUDE = 10.6;
const MIN_LATITUDE = 45.75;
const MAX_LATITUDE = 47.9;

function project(point: DemandMapPoint) {
  return {
    x:
      ((point.longitude - MIN_LONGITUDE) /
        (MAX_LONGITUDE - MIN_LONGITUDE)) *
      MAP_WIDTH,
    y:
      ((MAX_LATITUDE - point.latitude) /
        (MAX_LATITUDE - MIN_LATITUDE)) *
      MAP_HEIGHT,
  };
}

export function DemandMap() {
  const [roleInput, setRoleInput] = useState("engineer");
  const [role, setRole] = useState("engineer");
  const [result, setResult] = useState<DemandMapResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [requestVersion, setRequestVersion] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    void fetchDemandMap(role, controller.signal)
      .then(setResult)
      .catch((loadError: unknown) => {
        if (
          loadError instanceof DOMException &&
          loadError.name === "AbortError"
        ) {
          return;
        }
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Demand data could not be loaded.",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setIsLoading(false);
        }
      });
    return () => controller.abort();
  }, [role, requestVersion]);

  function applyFilter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleanedRole = roleInput.trim();
    if (cleanedRole.length >= 2) {
      setIsLoading(true);
      setError(null);
      setRole(cleanedRole);
      setRequestVersion((version) => version + 1);
    }
  }

  const largestCount = Math.max(
    1,
    ...(result?.points.map((point) => point.job_count) ?? []),
  );

  return (
    <section className="demand-card" aria-labelledby="demand-map-heading">
      <div className="demand-heading">
        <div>
          <p className="eyebrow">Role demand</p>
          <h2 id="demand-map-heading">Where are the jobs?</h2>
          <p>
            Search a job-title word to compare demand across recognized Swiss
            cities.
          </p>
        </div>
        <form className="role-filter" onSubmit={applyFilter}>
          <label htmlFor="role">Job field</label>
          <div>
            <input
              id="role"
              value={roleInput}
              onChange={(event) => setRoleInput(event.target.value)}
              minLength={2}
              maxLength={80}
              placeholder="e.g. engineer"
            />
            <button type="submit" disabled={isLoading}>
              {isLoading ? "Loading…" : "Show demand"}
            </button>
          </div>
        </form>
      </div>

      {error ? (
        <p className="map-message error-text" role="alert">
          {error} Check that the backend is available.
        </p>
      ) : (
        <div className="map-layout">
          <div className="swiss-map">
            <svg
              viewBox={`0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`}
              role="img"
              aria-label={`Swiss job demand for ${role}`}
            >
              <path
                className="country-shape"
                d="M 26 329 L 49 288 L 32 242 L 97 167 L 122 102 L 252 74 L 292 52 L 438 19 L 478 47 L 600 56 L 640 93 L 608 158 L 762 195 L 713 260 L 616 298 L 535 385 L 486 335 L 389 344 L 324 363 L 211 335 L 146 298 L 65 316 Z"
              />
              {result?.points.map((point) => {
                const position = project(point);
                const radius =
                  7 + Math.sqrt(point.job_count / largestCount) * 19;
                return (
                  <g
                    className="demand-point"
                    key={point.name}
                    transform={`translate(${position.x} ${position.y})`}
                  >
                    <title>
                      {point.name}: {point.job_count} matching jobs
                    </title>
                    <circle r={radius} />
                    <text y="4">{point.job_count}</text>
                  </g>
                );
              })}
            </svg>
          </div>

          <aside className="map-summary" aria-live="polite">
            <p className="map-role">{result?.role ?? role}</p>
            <strong>{result?.mapped_jobs ?? 0}</strong>
            <span>mapped matching jobs</span>
            {result?.points.length ? (
              <ol>
                {result.points.map((point) => (
                  <li key={point.name}>
                    <span>{point.name}</span>
                    <strong>{point.job_count}</strong>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="map-message">
                {isLoading
                  ? "Loading demand…"
                  : "No mapped jobs match this role yet."}
              </p>
            )}
            {result?.unmapped_jobs ? (
              <small>
                {result.unmapped_jobs} additional matching job
                {result.unmapped_jobs === 1 ? "" : "s"} had an unrecognized
                location.
              </small>
            ) : null}
            {result?.is_truncated ? (
              <small>
                Results reached the 1,000-job safety limit; displayed demand is
                a partial view.
              </small>
            ) : null}
          </aside>
        </div>
      )}
    </section>
  );
}
