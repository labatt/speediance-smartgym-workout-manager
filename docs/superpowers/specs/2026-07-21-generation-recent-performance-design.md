# AI generation — recent-performance context — design

Date: 2026-07-21

## Goal

Give the workout generator the athlete's **recent lifts** so it sets real weights instead
of guessing. Without this, the model prescribes RM values or absolute loads with no idea of
the athlete's strength. Send, by default, a compact per-exercise "what you last lifted"
table for the last 30 days, plus explicit progression instructions telling the model how to
act on it (trending well + felt easy → progress; missed/hard → hold or reduce).

This is the recent-performance half of the original Phase 2. "Add Workout Reference" is
deferred to its own later phase so this stays focused on weight-grounding.

## Decisions (locked in brainstorming)

- **On by default**, last **30 days**, with a control to widen/narrow (30/14/7) or turn off.
- Format: a **per-exercise recent-loads table** (most recent entry per exercise, with the
  prior entry so trend is visible), not the assessment prose.
- The data is **facts only** (no verdicts — same discipline as the coach/progression code);
  the "how to use it" lives in a **PROGRESSION instruction block** in the system prompt.
- Felt rating outranks the raw numbers (the project's standing principle).

## Data source

Reuse the assessment gather logic. Refactor the session-gathering in `/api/assessment`
into a shared helper:

- `_gather_recent_sessions(days) -> (sessions, truncated)` in `app.py`. Returns sessions
  **oldest→newest**, each `{date, title, snapshot, notes}`, where `snapshot` is
  `progression.analyze_session(...)` and `notes` is the journal entry. Capped at
  `ASSESSMENT_MAX_SESSIONS` (40). `/api/assessment` is updated to call it (no behaviour
  change).

Per-exercise snapshot fields available (from `progression.analyze_exercise`): `name`,
`region`, `kind` (`reps`/`timed`/`level`), `all_complete`, `any_missed`, `top_load`,
`sets` (each `{done, target, complete, skipped, load|None, seconds?}`), `scores`. Felt
ratings live in `notes.exercises[name]`.

## Pure core: `workout_gen.build_recent_performance(sessions, unit_label, days) -> str`

No I/O, unit-tested. Builds the table:

1. Collect every occurrence of each exercise across `sessions`, keyed by name, each tagged
   with its session `date` and felt rating.
2. Per exercise, sort occurrences by date descending; take the latest as "current" and the
   next as "previous".
3. Emit one line per exercise (most-recent first):
   - **reps**: `- {name} — {date}: top set {top_load}{unit} × {reps}, {all reps|missed some}, felt {felt}` plus trend `(↑|→|↓ from {prev_load}{unit} × {prev_reps} on {prev_date})` or `(new)`. `top_load` is the max load among worked sets; `{reps}` is the `done` of that set.
   - **level** (Vita) / **timed**: `- {name} — {date}: {done} reps × {seconds}s (timed), felt {felt}` plus `(prev {done}×{seconds}s on {prev_date})` or `(new)`. No weight/unit — the read-side snapshot does not expose the Vita level, so we do not fabricate one.
4. Header line: `RECENT PERFORMANCE (last {days} days; most recent per exercise, with trend). Loads are in {unit}.`
5. Empty `sessions` → `""` (caller omits the section).

A small local `FEEL` map renders feel keys (`too_easy`/`easy`/`right`/`hard`/`too_hard`/None)
to words; the trend arrow compares `top_load` (reps) or `done` (level/timed).

## Prompt changes (`workout_gen.py`)

- `build_generation_system_prompt(exercises, unit_label, has_recent=False)` — when
  `has_recent`, append a **PROGRESSION** block:
  > PROGRESSION — the user prompt includes a RECENT PERFORMANCE table of the athlete's recent lifts.
  > - Set each weight from that data, not a guess. The athlete's FELT rating outranks the numbers.
  > - Completed in full AND felt easy/too-easy (trend flat or up) → progress: add a little load, a rep, or a Vita level.
  > - Reps missed or it felt hard → hold or reduce.
  > - No recent entry for an exercise → estimate conservatively from similar lifts.
  > - Still never output weight 0.
- `build_generation_user_prompt(user_request, references=None, assessment=None, recent_performance="")`
  — appends the recent-performance table when non-empty. (`references`/`assessment` stay
  for later phases.)

## App wiring (`app.py`)

- `RECENT_PERF_DAYS = {7, 14, 30}` (generation-specific; the assessment page keeps 1/3/7/14).
- `POST /api/workout/generate` accepts `recent_days` (int, default **30**; `0`/absent-invalid
  → off). When it's in `RECENT_PERF_DAYS`, call `_gather_recent_sessions(recent_days)`, build
  the table with `workout_gen.build_recent_performance(...)`, pass it to the user prompt, and
  pass `has_recent=True` to the system prompt. Recent-perf gather failures degrade to no
  table (never block generation); auth errors still map to 401.
- The two-stage flow is otherwise unchanged; recent-performance rides only on the generation
  (stage 2) prompt, not the cheap selection pass.

## UI (`templates/create.html`)

Next to the **Generate Workout** button, a small control:
`Recent performance: [ Last 30 days ▾ ]` with options **30 / 14 / 7 days** and **Off**,
defaulting to 30. `generateWorkout()` reads it and includes `recent_days` in the POST
(`0` when Off).

## Errors

- No recent data in the window → no table; generation proceeds (model estimates
  conservatively, as instructed).
- Provider-not-ready / bad JSON / auth: unchanged from Phase 1.

## Testing

`tests/test_workout_gen.py`:
- `build_recent_performance`: latest-per-exercise dedupe (an exercise in two sessions shows
  once, newest); trend ↑ when load rose, `(new)` with no prior; Vita/timed rendered in
  reps×seconds with no weight; felt rating carried; loads labelled with the unit; empty
  sessions → `""`.
- `build_generation_system_prompt(..., has_recent=True)` contains the PROGRESSION block and
  the "felt rating outranks" and "never output weight 0" rules; `has_recent=False` omits it.
- `build_generation_user_prompt(..., recent_performance="...")` includes the table.

Live smoke: generate with real 30-day data and confirm prescribed weights track the recent
loads (e.g. an exercise done at 36.5 lb comes back at ~36–40, not a guess or 0).

## Files touched

- `workout_gen.py` — `build_recent_performance`, `FEEL`, top-set helper; `has_recent` on the
  system prompt; `recent_performance` on the user prompt.
- `app.py` — `_gather_recent_sessions(days)` (refactor from `/api/assessment`, reused there);
  `RECENT_PERF_DAYS`; `recent_days` handling in `/api/workout/generate`.
- `templates/create.html` — recent-performance window control; send `recent_days`.
- `tests/test_workout_gen.py` — the tests above.

## Non-goals

- No "Add Workout Reference" (separate later phase).
- No change to the auto-select stage or the cheap selection prompt.
- No biasing selection toward exercises with history (possible future enhancement).
