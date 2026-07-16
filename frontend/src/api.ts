// Typed contract with the FastAPI backend (mirrors backend/app/schemas.py).

export interface TestCase {
  id: number;
  fingerprint: string;
  suite: string;
  classname: string;
  name: string;
  flakiness_score: number;
  confirmed_flake_count: number;
  last_status: string;
  last_seen_at: string;
  github_issue_number: number | null;
}

export interface Execution {
  id: number;
  status: string;
  duration: number;
  message: string;
  created_at: string;
  commit_sha: string;
  branch: string;
  ci_run_id: string;
}

export interface History {
  test: TestCase;
  executions: Execution[];
}

export interface Summary {
  total_tests: number;
  flaky_tests: number;
  confirmed_flaky_tests: number;
  total_runs: number;
  total_executions: number;
  flake_threshold: number;
}

async function getJson<T>(url: string): Promise<T> {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`${url} -> ${resp.status}`);
  return resp.json() as Promise<T>;
}

export const fetchSummary = () => getJson<Summary>("/api/summary");
export const fetchTests = () => getJson<TestCase[]>("/api/tests?limit=200");
export const fetchHistory = (id: number) =>
  getJson<History>(`/api/tests/${id}/history?limit=60`);
