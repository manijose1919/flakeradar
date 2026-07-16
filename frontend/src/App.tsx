import { useCallback, useEffect, useState } from "react";
import {
  fetchHistory, fetchSummary, fetchTests,
  type History, type Summary, type TestCase,
} from "./api";
import { Leaderboard } from "./components/Leaderboard";
import { StatTiles } from "./components/StatTiles";
import { TestDetail } from "./components/TestDetail";

const REFRESH_MS = 30_000;

export default function App() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [tests, setTests] = useState<TestCase[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [s, t] = await Promise.all([fetchSummary(), fetchTests()]);
      setSummary(s);
      setTests(t);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

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

  return (
    <div className="app">
      <header className="app-header">
        <h1>FlakeRadar</h1>
        <span className="tagline">flaky-test detection for your CI</span>
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
          <Leaderboard tests={tests} selectedId={selectedId} onSelect={setSelectedId} />
        </section>
        <section className="panel">
          <h2>Test detail</h2>
          <TestDetail history={history} />
        </section>
      </div>

      <footer className="app-footer">
        Ingest from CI:{" "}
        <code>
          curl -X POST "$URL/api/ingest?commit_sha=$SHA&amp;branch=$BRANCH" -H "X-API-Key: $TOKEN"
          --data-binary @junit.xml
        </code>
      </footer>
    </div>
  );
}
