const COMPANY_SOURCE_PREFIX = "company:";

/** Sum the per-company counters produced by the reusable ATS scrapers. */
export function countCompanyAtsJobs(
  bySource: Record<string, number>,
): number {
  return Object.entries(bySource).reduce(
    (total, [source, count]) =>
      source.startsWith(COMPANY_SOURCE_PREFIX) ? total + count : total,
    0,
  );
}
