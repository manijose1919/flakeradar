import type { TestCase } from "../api";
import { StatusMark } from "./StatusMark";

// Sequential blue: darker = worse, so severity reads as magnitude.
function scoreColor(score: number): string {
  if (score >= 0.75) return "var(--seq-650)";
  if (score >= 0.5) return "var(--seq-550)";
  if (score >= 0.25) return "var(--seq-400)";
  return "var(--seq-250)";
}

export function Leaderboard({
  tests, selectedId, onSelect, onToggleQuarantine,
}: {
  tests: TestCase[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  onToggleQuarantine: (t: TestCase) => void;
}) {
  if (tests.length === 0) {
    return (
      <div className="empty">
        No test data yet. POST a JUnit XML report to <code>/api/ingest</code> — see
        the README for the one-line CI snippet.
      </div>
    );
  }
  return (
    <table className="leaderboard">
      <thead>
        <tr>
          <th>Test</th>
          <th>Flakiness</th>
          <th>Proof</th>
          <th>Last status</th>
          <th>Quarantine</th>
        </tr>
      </thead>
      <tbody>
        {tests.map((t) => (
          <tr
            key={t.id}
            className={t.id === selectedId ? "selected" : ""}
            onClick={() => onSelect(t.id)}
          >
            <td>
              <div className="test-name">
                {t.quarantined && (
                  <span className="badge-quarantined" title="Quarantined — runner may skip">
                    ⏻ quarantined
                  </span>
                )}
                {t.name}
              </div>
              <div className="test-class">{t.classname || t.suite}</div>
            </td>
            <td>
              <div className="meter">
                <div className="track">
                  <div
                    className="fill"
                    style={{
                      width: `${Math.max(t.flakiness_score * 100, t.flakiness_score > 0 ? 4 : 0)}%`,
                      background: scoreColor(t.flakiness_score),
                    }}
                  />
                </div>
                <span className="num">{t.flakiness_score.toFixed(2)}</span>
              </div>
            </td>
            <td>
              {t.confirmed_flake_count > 0 ? (
                <span className="chip" title="Fail + pass observed on the same commit SHA">
                  ⚠ {t.confirmed_flake_count}× same-SHA
                </span>
              ) : (
                <span className="chip">—</span>
              )}
            </td>
            <td>
              <span className="chip">
                <StatusMark status={t.last_status} /> {t.last_status}
                {t.github_issue_number != null && (
                  <span className="badge-issue">#{t.github_issue_number}</span>
                )}
              </span>
            </td>
            <td>
              <button
                className="quarantine-btn"
                onClick={(e) => { e.stopPropagation(); onToggleQuarantine(t); }}
              >
                {t.quarantined ? "Un-quarantine" : "Quarantine"}
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
