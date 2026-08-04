export type SourceRun = {
  source_name: string;
  status: "running" | "completed" | "partial" | "failed";
  jobs_seen: number;
  jobs_filtered: number;
  jobs_created: number;
  jobs_updated: number;
  started_at: string;
  completed_at: string;
  error_category: string | null;
  error_message: string | null;
};

export type ScrapeRun = {
  run_id: string;
  status: "running" | "completed" | "partial" | "failed";
  started_at: string;
  completed_at: string | null;
  jobs_seen: number;
  jobs_filtered: number;
  jobs_created: number;
  jobs_updated: number;
  sources: SourceRun[];
};

export type JobCounts = {
  total: number;
  by_source: Record<string, number>;
  latest_run: ScrapeRun | null;
};

export type DemandMapPoint = {
  name: string;
  latitude: number;
  longitude: number;
  job_count: number;
};

export type DemandMapResult = {
  role: string;
  matching_jobs: number;
  mapped_jobs: number;
  unmapped_jobs: number;
  is_truncated: boolean;
  points: DemandMapPoint[];
};

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function fetchJobCounts(signal?: AbortSignal): Promise<JobCounts> {
  const response = await fetch(`${API_BASE_URL}/api/v1/stats/jobs`, {
    signal,
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`The JobData API returned ${response.status}.`);
  }
  return response.json() as Promise<JobCounts>;
}

export async function fetchDemandMap(
  role: string,
  signal?: AbortSignal,
): Promise<DemandMapResult> {
  const query = new URLSearchParams({ role });
  const response = await fetch(
    `${API_BASE_URL}/api/v1/analysis/demand-map?${query}`,
    {
      signal,
      cache: "no-store",
    },
  );
  if (!response.ok) {
    throw new Error(`The JobData API returned ${response.status}.`);
  }
  return response.json() as Promise<DemandMapResult>;
}

export async function startScrapeRun(): Promise<ScrapeRun> {
  const response = await fetch(`${API_BASE_URL}/api/v1/ingestion/runs`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`The JobData API returned ${response.status}.`);
  }
  return response.json() as Promise<ScrapeRun>;
}

export async function fetchScrapeRun(
  runId: string,
  signal?: AbortSignal,
): Promise<ScrapeRun> {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/ingestion/runs/${encodeURIComponent(runId)}`,
    {
      signal,
      cache: "no-store",
    },
  );
  if (!response.ok) {
    throw new Error(`The JobData API returned ${response.status}.`);
  }
  return response.json() as Promise<ScrapeRun>;
}
