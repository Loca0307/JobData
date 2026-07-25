export type SourceRun = {
  source_name: string;
  status: "running" | "completed" | "partial" | "failed";
  jobs_seen: number;
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
  jobs_created: number;
  jobs_updated: number;
  sources: SourceRun[];
};

export type JobCounts = {
  total: number;
  by_source: Record<string, number>;
  latest_run: ScrapeRun | null;
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
