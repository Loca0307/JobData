import assert from "node:assert/strict";
import test from "node:test";

import { countCompanyAtsJobs } from "./job-counts.ts";

test("countCompanyAtsJobs combines all company ATS source counters", () => {
  assert.equal(
    countCompanyAtsJobs({
      "jobs.ch": 20,
      "company:scandit": 4,
      "company:on": 7,
      "company:rivr": 2,
    }),
    13,
  );
});

test("countCompanyAtsJobs returns zero when no ATS source is present", () => {
  assert.equal(
    countCompanyAtsJobs({
      "jobs.ch": 20,
      "jobup.ch": 8,
      "swissdevjobs.ch": 3,
    }),
    0,
  );
});
