# AI generation — Add Workout Reference — design

Date: 2026-07-21

## Goal

Let the athlete point the generator at one or more of their existing workouts as
structure/inspiration ("build something like my Back Day, but harder"). The model sees a
readable summary of each referenced workout AND can reuse its exact exercises.

This is the deferred half of the original Phase 2 (recent-performance context shipped
separately). The refinement loop is a later, separate feature.

## Decisions (locked in brainstorming)

- References shown as removable **chips** below the request box; the request text stays the
  athlete's own words.
- Multiple references allowed.
- Referenced workouts' exercise IDs are **force-added to the generation candidate pool** so
  the model can reuse those exact movements (otherwise `validate_workout` drops any ID the
  auto-selector didn't pick — a reference would be inert text).
- Summary is a readable per-exercise digest (facts), not raw JSON.

## Data shapes (verified live)

- `client.get_user_workouts()` → list of `{id, name, code, actionNum, durationMinute, ...}`.
- `client.get_workout_detail(code)` → dict with `actionLibraryList`: each exercise has
  `groupId` (the library group id the generator uses), `title`, `setsAndReps` (comma string,
  reps or seconds), `weights` (comma string, load per set; "0" for Vita), `level` (comma
  string, Vita levels per set), `completionMethod` (5 = Vita level+timed; 0/2 = timed),
  `mainMuscleGroupName`.

## Pure core: `workout_gen.build_reference_workouts(references, unit_label) -> str`

No I/O, unit-tested. `references` is a normalized list the route builds:
`[{"name": str, "exercises": [{"title", "setsAndReps", "weights", "level", "is_level", "is_timed"}]}]`.

Formatting, one block per workout:
```
REFERENCE WORKOUTS (structure/inspiration — adapt to the request, don't copy verbatim):
{name}:
- {title}: {N} sets, {reps}×{load} {unit}          # weighted: distinct reps/loads summarised
- {title}: {N} sets, {secs}s, levels {a/b/c} (timed)  # Vita/level: levels×seconds, no unit
- {title}: {N} sets, {secs}s (timed)                # timed non-level
```
- Per exercise, parse the comma strings; if all sets share reps/load, show `3×10 @ 40 LBS`;
  if they vary, show the list (`10/8/6 @ 40/45/50 LBS`). Vita shows `levels 10/12/14 × 30s`,
  never a weight/unit. Empty `references` → `""`.

## Prompt hooks (`workout_gen.py`)

- Repurpose `build_generation_user_prompt`'s `references` parameter to accept the
  **preformatted string** from `build_reference_workouts` (append when non-empty). Drop the
  unused list-based `references` handling and the unused `assessment` param. New signature:
  `build_generation_user_prompt(user_request, references="", recent_performance="")`.
- `build_generation_system_prompt(exercises, unit_label, has_recent=False, has_refs=False)`
  — when `has_refs`, add one line: reference workouts are provided as structure to adapt,
  reuse their exercises where they fit, but tailor sets/loads to the request and the
  athlete's recent performance.

## App wiring (`app.py`)

- `GET /api/workout/list` (auth-gated) → `[{name, code, exercises, duration}]` from
  `get_user_workouts()` (fields: name, code, actionNum, durationMinute).
- `POST /api/workout/generate` accepts `references: [codes]` (optional). For each code:
  `get_workout_detail(code)`; from its `actionLibraryList` build (a) the normalized list for
  `build_reference_workouts`, and (b) the set of `groupId`s. Merge those groupIds into
  `pool_ids` (dedup, still respecting the pool cap) before building `merged`/system prompt,
  so referenced exercises are available to emit. Pass the reference summary to the user
  prompt and `has_refs=bool(...)` to the system prompt. A reference fetch that fails is
  skipped (never blocks generation); auth errors still propagate to 401.
- The saved last-generation (`workout_gen_last.json`) already stores the full assembled
  prompt, so referenced context is captured there automatically.

## UI (`templates/create.html`)

- An **"Add reference"** button next to Generate. Opens a modal listing workouts from
  `/api/workout/list` (name · N exercises · ~M min); clicking one adds a removable chip
  below the request box and pushes its code into a client `references` array (deduped).
- `generateWorkout()` includes `references` in the POST body.

## Errors

- No workouts / list fetch fails → modal shows a friendly empty/error message (textContent).
- A referenced workout that 404s server-side is skipped with the others still used.
- Provider/JSON/auth handling unchanged from prior phases.

## Testing

`tests/test_workout_gen.py`:
- `build_reference_workouts`: workout name present; weighted exercise shows reps×load with
  unit; uniform vs varying sets both render; Vita shows levels×seconds and no unit; empty→"".
- `build_generation_system_prompt(..., has_refs=True)` adds the reference note; default omits.
- `build_generation_user_prompt(user_request, references="...", recent_performance="...")`
  includes both.

`tests/` (app-level, isolated with the token+stub pattern):
- `/api/workout/list` returns name/code entries.
- generate merges referenced groupIds into the pool (stub `get_workout_detail` and assert the
  referenced id reaches the pool / a stubbed `build_generation_system_prompt` sees it).

Live smoke: reference a real workout and confirm the generated plan reuses its exercises and
the assembled prompt (viewable via the last-generation panel) contains the reference summary.

## Files touched

- `workout_gen.py` — `build_reference_workouts`; `has_refs` on system prompt; `references`
  string param on user prompt (signature cleanup).
- `app.py` — `/api/workout/list`; `references` handling + pool merge in `/api/workout/generate`.
- `templates/create.html` — Add-reference button, modal, chips; send `references`.
- `tests/test_workout_gen.py` (+ an app-level test).

## Non-goals

- The refinement loop (comment → adjust) — next, separate feature (Interactions API).
- No editing of referenced workouts from here; it's read-only inspiration.
