# Multi-day Assessment — design

Date: 2026-07-20

## Goal

An **Assessment** button in the top nav opens a dedicated page where the athlete
picks a window (1, 3, 7, or 14 days). The app gathers every completed workout in
that window and asks the active LLM provider for a read over the whole period:
where you're **strong**, **weak**, **improving**, **regressing/plateauing**, where
you should **increase weight or resistance**, plus other observations — grouped by
muscle region.

This extends the existing single-session coach (`coach.build_prompt` + `coach.chat`)
to a *list* of session snapshots. It reuses the same pure-core / IO-shell split and
the same provider dispatch.

## Non-goals (YAGNI)

- No scheduling or auto-run — on demand only.
- No charts on this page (History already has per-rep telemetry charts).
- No cross-provider fan-out — one assessment, one active provider.
- The cached assessment is informational; the window is rolling, so it is not
  treated as authoritative — it is shown with its date and a "run a new one" prompt.

## UX

Dedicated page at `/assessment` (auth-guarded; redirects to Settings when signed
out, like `/history`).

- On load, `GET /api/assessment/last` returns the cached assessment
  `{text, model, at, days, session_count}` or `{last: null}`.
  - If one exists: a banner — *"Last assessment: last 7 days, run Jul 18
    (2 days ago) · gpt-oss:120b"* — its text rendered below, and a
    **"Run a new assessment"** row with the four range buttons.
  - If none: the four range buttons and a prompt to run one.
- Range buttons **1 / 3 / 7 / 14 days** → `POST /api/assessment {days}` → spinner
  → render result.
- Rendering uses the **same escape-first `coachMarkdown()`** already used on the
  History page. It is extracted to `static/js/coach_markdown.js` and included by
  both `history.html` and `assessment.html`, so there is one renderer, not two
  copies. `escHtml` moves with it (or stays a small local dependency the file
  defines) so both pages keep escape-first rendering.

## Backend (`app.py`)

- `POST /api/assessment` (auth-gated):
  1. Validate `days ∈ {1, 3, 7, 14}` (reject others with 400).
  2. Window = `[today - (days - 1) .. today]` inclusive (rolling calendar days).
  3. `records = client.get_training_records(start, end)`; keep completed sessions
     that have a usable detail (custom/course).
  4. For each session: `_analyze_training(trainingId)` → snapshot;
     `load_journal().get(str(trainingId), {})` → felt ratings/notes.
  5. Build `sessions = [{date, title, snapshot, notes}]`, oldest→newest. Cap at
     **40** sessions; if exceeded, keep the most recent 40 and `log()`/note the
     truncation in the response so it is not silently hidden.
  6. `prompt = coach.build_assessment_prompt(sessions, days)`.
  7. `ok, text = coach.chat(prompt, cfg, system=coach.ASSESSMENT_SYSTEM_PROMPT)`.
  8. On success, persist to `assessment.json` (gitignored):
     `{text, model, at (ISO), days, session_count}`; return it.
  - **Empty window** → return `{ok: true, empty: true, session_count: 0}` with a
    friendly "no completed workouts in the last N days" message; no LLM call.
  - **Provider not ready** → reuse the coach's existing not-ready messaging
    (`coach.status`); same shape as the single-session coach route.
  - **Auth error** → 401, matching sibling routes (`_is_auth_error`).
- `GET /api/assessment/last` (auth-gated): return the cached object or
  `{last: null}`.

## Pure core (`coach.py`, unit-tested)

- `ASSESSMENT_SYSTEM_PROMPT`: same guardrails as `SYSTEM_PROMPT` — use ONLY the
  given facts, never invent a number, the athlete's **felt rating outranks every
  sensor metric**, Vita in levels/seconds not weight, add load only where the
  evidence agrees (all reps done AND felt easy AND form solid), prefer *hold* over
  churn — but framed for a **window of sessions** and asked to report: where
  strong, where weak, where improving, where regressing/plateauing, where to add
  weight or resistance, and other observations, **grouped by muscle region**, and
  to cite cross-session trends (e.g. a top load rising across dates) using only the
  dated facts given.
- `build_assessment_prompt(sessions, days)`: pure, no I/O. One compact block per
  session, oldest→newest, headed by its date and title, then one line per exercise
  using the **exact** formatting used for a single session. Ends with the
  assessment questions. Handles an empty `sessions` list without error.
- Refactor: extract the per-exercise line formatting out of `build_prompt` into a
  shared `_exercise_line(e, notes, cmp=None)` helper. `build_prompt` calls it, so
  its output is **byte-for-byte unchanged**; `build_assessment_prompt` calls it
  too. No behaviour change to the single-session path.
- `chat(prompt, config=None, timeout=120, system=None)`: add an optional `system`
  override that defaults to `SYSTEM_PROMPT`. Threaded through `_chat_provider` so
  every provider uses the given system prompt. The single-session call site passes
  nothing and is unchanged.

## Tests (`tests/test_coach.py`)

- `build_assessment_prompt`:
  - Includes each session's date and title.
  - Speaks Vita in levels, never `@weight`.
  - Carries felt ratings from notes.
  - Asks the strong / weak / improving questions (assertion on the closing block).
  - Empty `sessions` list produces a prompt without raising.
- `ASSESSMENT_SYSTEM_PROMPT` encodes the guardrails ("felt rating outranks",
  "never invent", region grouping).
- Single-session `build_prompt(SNAPSHOT, NOTES)` output is unchanged after the
  `_exercise_line` refactor (existing tests already assert its content; they must
  stay green).
- `chat(..., system=...)` default path unchanged (existing dispatch tests green).

## Files touched

- `coach.py` — `ASSESSMENT_SYSTEM_PROMPT`, `build_assessment_prompt`,
  `_exercise_line` refactor, `chat`/`_chat_provider` `system` param.
- `app.py` — `/assessment` page route, `POST /api/assessment`,
  `GET /api/assessment/last`, `assessment.json` load/save helpers.
- `templates/layout.html` — Assessment nav link.
- `templates/assessment.html` — new page.
- `templates/history.html` — swap inline `coachMarkdown` for the shared include.
- `static/js/coach_markdown.js` — extracted shared renderer.
- `tests/test_coach.py` — new assessment tests.
- `.gitignore` — `assessment.json`.
```
