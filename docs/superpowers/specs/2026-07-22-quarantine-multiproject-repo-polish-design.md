# FlakeRadar v1.1 — Quarantine, Multi-Project & Repo Polish

**Date:** 2026-07-22
**Status:** Approved design (pre-implementation)
**Scope:** One schema migration (introducing Alembic) delivering multi-project
isolation and a manual quarantine workflow, bundled with a repository
presentation / SEO / documentation pass.

---

## 1. Motivation

FlakeRadar v1.0 *detects* flakiness well but does two things poorly for its
stated audience (2–50 developer teams):

1. **It acts on nothing.** The only output of a high flakiness score is an
   optional GitHub issue. The core promise — stop developers reflexively
   re-running flaky tests — requires a way to *quarantine* a test so the runner
   skips it. Detection without action is half a product.
2. **It assumes one repo per instance.** Test identity is
   `fingerprint(suite, classname, name)` with no project dimension, so two
   repositories posting to one instance silently merge same-named tests into a
   single flakiness score. Teams of this size almost always have several repos.

Both fixes touch the schema, so they are delivered together behind a single
Alembic migration. We additionally bundle a repository-presentation pass
(license, discoverability, professional docs) because the repo is public and
currently missing a license and topics.

Non-goals are listed in §9.

---

## 2. Decisions (settled during brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| D1 | How a project is identified on ingest | **Explicit `project` query param**, defaulting to `"default"` (mirrors existing `commit_sha`/`branch`/`ci_run_id` params; backward-compatible) |
| D2 | How project lives in the schema | **Denormalized string column** on `TestCase` + `TestRun`; no `Project` table |
| D3 | What triggers a quarantine | **Manual only** — a human clicks quarantine in the dashboard; nothing is auto-skipped |
| D4 | Quarantine read contract | **Structured JSON** array of `{suite, classname, name, fingerprint, quarantined_at}` |
| D5 | Auth posture for new endpoints | **Follow the origin, not the verb** — quarantine toggle (internal) is open; quarantine list (external CI) is token-gated |
| D6 | License | **Apache-2.0** (permissive + patent grant; corporate-friendly) |
| D7 | Sequencing | **Bundle everything** into one spec / delivery |

---

## 3. Track A — Multi-project isolation

### 3.1 Data model (`backend/app/models.py`)

`TestCase`:
- `+ project: Mapped[str]` — `server_default="default"`, indexed.
- Uniqueness change: **drop** the standalone unique on `fingerprint`; **add**
  composite unique `(project, fingerprint)`.
- The fingerprint hash stays `(suite, classname, name)` — **unchanged**, so no
  existing fingerprint value moves; the backfill only sets `project="default"`.

`TestRun`:
- `+ project: Mapped[str]` — `server_default="default"`. A run inherently
  belongs to one project (ingest already knows it); storing it enables future
  per-project retention / run views at no cost now.

### 3.2 Ingest (`backend/app/ingest.py`)

- `fingerprint()` is untouched.
- `ingest_report(db, content, commit_sha, branch, ci_run_id, project)` gains the
  `project` argument.
- `_get_or_create_case` looks up by `(project, fingerprint)` instead of
  `fingerprint` alone (the race-safe get-or-create pattern is preserved; the
  `IntegrityError` retry now keys on the composite constraint).
- The new `TestRun` and any newly created `TestCase` are stamped with `project`.

### 3.3 API (`backend/app/main.py`)

- `POST /api/ingest` — new `project: str = Query(default="default", max_length=255)`.
  Backward-compatible: existing callers omit it and land in `"default"`.
- `GET /api/tests`, `GET /api/summary`, `GET /api/tests/{id}/history` — gain an
  optional `project: str | None = Query(default=None)`. When `None`, no project
  filter is applied (preserves current whole-instance behavior). The UI's "All"
  selector maps to omitting the param.
- `GET /api/projects` — **new, open** — returns the distinct list of project
  names (for the dashboard selector). Small and cache-friendly.

---

## 4. Track B — Quarantine workflow (manual)

### 4.1 Data model (`backend/app/models.py`)

`TestCase`:
- `+ quarantined: Mapped[bool]` — `server_default` false.
- `+ quarantined_at: Mapped[datetime | None]` — nullable (`UTCDateTime`).

Un-quarantining sets `quarantined=False` and `quarantined_at=None`.

### 4.2 API (`backend/app/main.py`)

- `POST /api/tests/{id}/quarantine` — **open** (internal dashboard origin).
  Body `{ "quarantined": bool }`. Idempotent: sets the flag and stamps /
  clears `quarantined_at`. Returns the updated `TestCaseOut`. 404 if the test
  does not exist.
- `GET /api/quarantine?project=` — **token-gated** (`Depends(require_token)`;
  external CI reuses the existing `X-API-Key`). Returns only *currently
  quarantined* tests for the given project. The `project` param is optional and
  defaults to `"default"`, matching ingest. Response items:
  `{ suite, classname, name, fingerprint, quarantined_at }`.

Rationale for D5: the existing read-open / write-gated split is really about
*origin*, not HTTP verb — the token exists because ingest crosses the boundary
from external CI. The quarantine toggle is dashboard-internal (same trust level
as the already-open read APIs), while the quarantine list is consumed by
external CI (same origin as ingest), so it reuses the ingest token at zero extra
CI config.

### 4.3 Frontend (`frontend/src/`)

- **Project selector** in the header (populated from `GET /api/projects`), with
  an "All" option that omits the `project` filter. Drives the filter on all
  read calls.
- **Quarantine toggle** button on each leaderboard row and/or the detail view,
  calling `POST /api/tests/{id}/quarantine` and refreshing.
- **Quarantined visual state** — a badge/marker reusing the existing
  shape-coded, colorblind-safe convention (`StatusMark` philosophy: color never
  carries meaning alone).
- `frontend/src/api.ts` gains typed wrappers for the new endpoints and the
  `project` filter param.

---

## 5. Track C — Alembic introduction (the sharp edge)

Introducing Alembic into an app that currently builds its schema with
`Base.metadata.create_all` has a specific hazard: **existing databases already
have the tables but no `alembic_version` marker.** A naive `upgrade` would try
to re-create existing tables and fail.

Plan:

1. Add Alembic (dependency + `alembic.ini` + `migrations/` env wired to the
   app's `DATABASE_URL` and `Base.metadata`).
2. Author two revisions:
   - `0001_baseline` — today's exact schema (all current tables, columns,
     indexes), so a fresh DB can be built from zero via migrations.
   - `0002_project_and_quarantine` — the §3.1 + §4.1 changes.
3. The unique-constraint swap on `test_cases` uses `op.batch_alter_table`
   — **required on SQLite**, which cannot `ALTER` a constraint in place and
   needs Alembic's copy-and-rebuild ("batch") mode. New columns use
   `server_default` so existing rows backfill (`project="default"`,
   `quarantined=False`).
4. Startup (`main.py` lifespan) replaces `Base.metadata.create_all(engine)`
   with:
   - *If* `test_cases` exists **and** `alembic_version` does **not** → `stamp 0001`.
   - Then always `upgrade head`.

   This auto-migrates all three cases uniformly: a fresh DB (runs `0001`+`0002`),
   the existing local dev DB `backend/data/flakeradar.db`, and any deployed
   Docker named-volume DB.

README design note updated: the "introduce Alembic when the schema first
changes" line is now realized.

---

## 6. Track D — Repository presentation, SEO & docs

### 6.1 Local files (committed & pushed)

- **`LICENSE`** — Apache-2.0 full text.
- **`NOTICE`** — minimal attribution notice (Apache-2.0 convention). Per-file
  source headers are **out of scope** (LICENSE + NOTICE suffice for a project
  this size).
- **`README.md`** —
  - Badge row near the top: license (Apache-2.0), Python version, "self-hosted".
  - Table of contents (README is ~230 lines).
  - Light keyword tuning for search intent ("detect flaky tests",
    "open-source BuildPulse / Datadog CI Visibility alternative", explicit
    runner names: pytest / Jest / Vitest / Go / JUnit).
  - **Fix the test-count inconsistency**: the file says "35 tests" in the
    Architecture block and "37 tests" in Development — reconcile to the real
    number after Track E lands.
  - Document the new `project` param, quarantine endpoints, and a
    quarantine-consumption recipe (how a runner matches the JSON on
    `classname`+`name`).
  - Move delivered items off the Roadmap; note the documented v1 limitations.
- **`SECURITY.md`** — how to report a vulnerability + the trust model
  (token-gated write path, private-network read/dashboard assumption, handling
  of the `FLAKERADAR_API_TOKEN` and GitHub token).
- **`CONTRIBUTING.md`** — dev setup + the test gate (pytest for backend, strict
  TypeScript build for frontend), largely lifted from existing README sections.
- **`.gitignore`** — add `frontend/tsconfig.tsbuildinfo`.
- **Untrack** `frontend/tsconfig.tsbuildinfo` (`git rm --cached`).

### 6.2 GitHub-side settings (via `gh`, outward-facing)

Run **only after explicit approval** during implementation (these mutate a
public repo):

- **Topics** (primary SEO lever, currently none):
  `flaky-tests`, `flaky-test-detection`, `ci`, `continuous-integration`,
  `test-automation`, `junit`, `pytest`, `test-analytics`, `fastapi`,
  `self-hosted`, `devops`, `developer-tools`.
- Optional: minor description tune (current one is already strong).
- Homepage left empty (no hosted demo exists).
- Social preview image: not changed (default is acceptable).

---

## 7. Track E — Testing

- **Regression guard:** scoring logic is untouched; its existing 37 tests must
  stay green.
- **New backend tests:**
  - Project isolation: ingest the same test name under two different projects →
    two distinct `TestCase` rows, independent scores.
  - Backward-compat: ingest with no `project` param → lands in `"default"`.
  - Quarantine toggle round-trip: `POST` true then false; `quarantined_at`
    stamped then cleared; 404 on unknown id.
  - `GET /api/quarantine`: returns only the requested project's quarantined
    tests; rejects missing/invalid `X-API-Key` (401).
  - Project filter on `GET /api/tests` and `/api/summary`.
- **Migration test:** build a DB at `0001`, run `upgrade` to `0002`, assert the
  new columns and composite unique exist and pre-existing rows carry
  `project="default"`, `quarantined=False`.
- Frontend automated tests remain out of scope (Vitest suite stays on the
  roadmap); the strict TypeScript build remains the frontend gate.

---

## 8. Affected files (summary)

| File | Change |
|------|--------|
| `backend/app/models.py` | `project` on `TestCase`+`TestRun`; `quarantined`/`quarantined_at`; composite unique |
| `backend/app/ingest.py` | `project` arg; get-or-create keyed on `(project, fingerprint)` |
| `backend/app/main.py` | `project` param + filters; `/api/projects`; quarantine toggle + list; lifespan → Alembic |
| `backend/app/schemas.py` | project fields; quarantine request/response; quarantine-list item |
| `backend/alembic.ini`, `backend/migrations/**` | new — Alembic env + `0001`,`0002` |
| `backend/requirements.txt` | `+ alembic` |
| `frontend/src/api.ts`, `App.tsx`, components | project selector, quarantine toggle, badge |
| `LICENSE`, `NOTICE`, `SECURITY.md`, `CONTRIBUTING.md` | new |
| `README.md`, `.gitignore` | polish per §6.1 |

---

## 9. Out of scope (documented v1 limitations)

- **GitHub issues stay global** — one repo for all projects. Per-project repo
  mapping is deferred; it is the feature that would later justify a real
  `Project` table.
- **No test-runner plugin** — we ship the `/api/quarantine` JSON contract and a
  documented matching recipe; a pytest/Vitest plugin is a follow-up.
- **Apache-2.0 per-file headers** — skipped; LICENSE + NOTICE suffice.
- **Auto-close issues, retention pruning, branch filtering, frontend Vitest
  suite** — remain on the roadmap, unchanged by this work.
