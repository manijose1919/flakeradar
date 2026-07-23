import { useCallback, useEffect, useState } from "react";
import {
  fetchHistory, fetchProjects, fetchSummary, fetchTests, setQuarantine,
  type History, type Summary, type TestCase,
} from "./api";
import { Leaderboard } from "./components/Leaderboard";
import { StatTiles } from "./components/StatTiles";
import { TestDetail } from "./components/TestDetail";

const REFRESH_MS = 30_000;

export default function App() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [tests, setTests] = useState<TestCase[]>([]);
  const [projects, setProjects] = useState<string[]>([]);
  const [project, setProject] = useState<string>("All");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [s, t, p] = await Promise.all([
        fetchSummary(project), fetchTests(project), fetchProjects(),
      ]);
      setSummary(s);
      setTests(t);
      setProjects(p);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [project]);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), REFRESH_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (selectedId == null) return;
    let cancelled = false;
    fetchHistory(selectedId)
      .then((h) => { if (!cancelled) setHistory(h); })
      .catch((e) => { if (!cancelled) setError(String(e)); });
    return () => { cancelled = true; };
  }, [selectedId, tests]); // re-fetch when leaderboard refreshes

  const onToggleQuarantine = useCallback(async (t: TestCase) => {
    try {
      await setQuarantine(t.id, !t.quarantined);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [refresh]);

  return (
    <div className="app">
      <header className="app-header">
        <h1>FlakeRadar</h1>
        <span className="tagline">flaky-test detection for your CI</span>
        <select
          className="project-select"
          value={project}
          onChange={(e) => setProject(e.target.value)}
          aria-label="Filter by project"
        >
          <option value="All">All projects</option>
          {projects.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
      </header>

      {error && (
        <div className="error-banner">
          Could not reach the FlakeRadar API ({error}). Is the backend running on port 8000?
        </div>
      )}

      {summary && <StatTiles summary={summary} />}

      <div className="columns">
        <section className="panel">
          <h2>Flakiness leaderboard</h2>
          <Leaderboard
            tests={tests}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onToggleQuarantine={onToggleQuarantine}
          />
        </section>
        <section className="panel">
          <h2>Test detail</h2>
          <TestDetail history={history} />
        </section>
      </div>

      <footer className="app-footer">
        Ingest from CI:{" "}
        <code>
          curl -X POST "$URL/api/ingest?commit_sha=$SHA&amp;branch=$BRANCH&amp;project=$REPO" -H "X-API-Key: $TOKEN"
          --data-binary @junit.xml
        </code>
      </footer>
    </div>
  );
}
