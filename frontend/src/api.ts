// Typed contract with the FastAPI backend (mirrors backend/app/schemas.py).

export interface TestCase {
  id: number;
  fingerprint: string;
  project: string;
  suite: string;
  classname: string;
  name: string;
  flakiness_score: number;
  confirmed_flake_count: number;
  last_status: string;
  last_seen_at: string;
  quarantined: boolean;
  quarantined_at: string | null;
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

const projectParam = (project?: string) =>
  project && project !== "All" ? `project=${encodeURIComponent(project)}` : "";

export const fetchSummary = (project?: string) => {
  const q = projectParam(project);
  return getJson<Summary>(`/api/summary${q ? `?${q}` : ""}`);
};
export const fetchTests = (project?: string) => {
  const q = projectParam(project);
  return getJson<TestCase[]>(`/api/tests?limit=200${q ? `&${q}` : ""}`);
};
export const fetchHistory = (id: number) =>
  getJson<History>(`/api/tests/${id}/history?limit=60`);
export const fetchProjects = () => getJson<string[]>("/api/projects");

export async function setQuarantine(id: number, quarantined: boolean): Promise<TestCase> {
  const resp = await fetch(`/api/tests/${id}/quarantine`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ quarantined }),
  });
  if (!resp.ok) throw new Error(`quarantine ${id} -> ${resp.status}`);
  return resp.json() as Promise<TestCase>;
}
