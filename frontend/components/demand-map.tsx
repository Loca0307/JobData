"use client";

import { type FormEvent, useEffect, useState } from "react";

import {
  fetchDemandMap,
  type DemandMapPoint,
  type DemandMapResult,
} from "@/lib/api";
import {
  jobsByCanton,
  projectSwissCoordinates,
  SWISS_MAP_HEIGHT,
  SWISS_MAP_WIDTH,
  swissCantonPaths,
} from "@/lib/swiss-map";

function project(point: DemandMapPoint) {
  return projectSwissCoordinates(point.longitude, point.latitude);
}

export function DemandMap() {
  const [roleInput, setRoleInput] = useState("");
  const [role, setRole] = useState("");
  const [result, setResult] = useState<DemandMapResult | null>(null);
  const [selectedPoint, setSelectedPoint] = useState<DemandMapPoint | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [requestVersion, setRequestVersion] = useState(0);

  useEffect(() => {
    if (!role) {
      return;
    }
    const controller = new AbortController();
    void fetchDemandMap(role, controller.signal)
      .then((demandResult) => {
        setResult(demandResult);
        setSelectedPoint(null);
      })
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
      setSelectedPoint(null);
      setRole(cleanedRole);
      setRequestVersion((version) => version + 1);
    }
  }

  const cantonCounts = jobsByCanton(result?.points ?? []);
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
              viewBox={`0 0 ${SWISS_MAP_WIDTH} ${SWISS_MAP_HEIGHT}`}
              role="img"
              aria-label={
                role
                  ? `Swiss job demand for ${role}`
                  : "Swiss job demand map"
              }
            >
              <g className="canton-map" aria-hidden="true">
                {swissCantonPaths.map((canton) => (
                  <path key={canton.id} d={canton.path} />
                ))}
              </g>
              {[...(result?.points ?? [])].reverse().map((point) => {
                const position = project(point);
                const radius =
                  7 + Math.sqrt(point.job_count / largestCount) * 19;
                return (
                  <g
                    className={`demand-point${
                      selectedPoint?.name === point.name ? " selected" : ""
                    }`}
                    key={point.name}
                    transform={`translate(${position.x} ${position.y})`}
                    role="button"
                    tabIndex={0}
                    aria-label={`${point.name}: ${point.job_count} matching jobs`}
                    aria-pressed={selectedPoint?.name === point.name}
                    onClick={() => setSelectedPoint(point)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setSelectedPoint(point);
                      }
                    }}
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
            <p className="map-role">
              {result?.role || role || "Choose a role"}
            </p>
            {selectedPoint ? (
              <>
                <h3>{selectedPoint.name}</h3>
                <strong>{selectedPoint.job_count}</strong>
                <span>
                  matching job{selectedPoint.job_count === 1 ? "" : "s"}
                </span>
                <small className="location-coordinates">
                  {selectedPoint.latitude.toFixed(4)},{" "}
                  {selectedPoint.longitude.toFixed(4)}
                </small>
              </>
            ) : (
              <p className="map-message">
                {isLoading
                  ? "Loading demand…"
                  : result?.points.length
                    ? "Select a dot to see that location’s details."
                    : role
                      ? "No mapped jobs match this role yet."
                      : "Enter a job field to load the demand map."}
              </p>
            )}
            {result ? (
              <div className="map-total">
                <span>Total jobs found</span>
                <strong>{result.matching_jobs}</strong>
                <details className="canton-breakdown">
                  <summary>Jobs by canton</summary>
                  <ul>
                    {cantonCounts.map((canton) => (
                      <li key={canton.id}>
                        <span>{canton.name}</span>
                        <strong>{canton.jobCount}</strong>
                      </li>
                    ))}
                  </ul>
                </details>
              </div>
            ) : null}
          </aside>
        </div>
      )}
    </section>
  );
}
