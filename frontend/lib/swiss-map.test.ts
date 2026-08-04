import assert from "node:assert/strict";
import test from "node:test";

import { jobsByCanton } from "./swiss-map.ts";

test("jobsByCanton combines cities that belong to the same canton", () => {
  const counts = jobsByCanton([
    { latitude: 47.3769, longitude: 8.5417, job_count: 6 }, // Zürich
    { latitude: 47.4988, longitude: 8.7241, job_count: 4 }, // Winterthur
    { latitude: 46.948, longitude: 7.4474, job_count: 3 }, // Bern
  ]);

  const zurich = counts.find((canton) => canton.name === "Zürich");
  assert.equal(zurich?.jobCount, 10);
  assert.equal(counts.find((canton) => canton.name === "Bern")?.jobCount, 3);
});

test("jobsByCanton ignores coordinates outside Switzerland", () => {
  const counts = jobsByCanton([
    { latitude: 48.8566, longitude: 2.3522, job_count: 8 }, // Paris
  ]);

  assert.equal(
    counts.reduce((total, canton) => total + canton.jobCount, 0),
    0,
  );
});

test("jobsByCanton keeps a Swiss town on a simplified national border", () => {
  const counts = jobsByCanton([
    {
      latitude: 46.1937027,
      longitude: 6.2101703,
      job_count: 1,
    }, // Thônex, Geneva
  ]);

  assert.equal(
    counts.find((canton) => canton.name === "Geneva")?.jobCount,
    1,
  );
});
