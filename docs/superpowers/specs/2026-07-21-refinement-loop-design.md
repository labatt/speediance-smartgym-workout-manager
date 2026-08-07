# AI generation — refinement loop (stateless) — design

Date: 2026-07-21

## Goal

After a workout is in the builder, let the athlete refine it by comment ("make leg day
harder", "swap the back squat for a hinge", "add a set to the rows"). The model returns the
adjusted workout, never undoing earlier comments or the athlete's manual edits.

Phase 3 of in-app generation (parts 5 & 6). Stateless, provider-agnostic — no Gemini
Interactions API (decided in brainstorming: the thread is ephemeral and we must send current
state each round anyway, so a single stateless path is simpler and works for all providers).

## Decisions (locked in brainstorming)

- **Stateless only**, all five providers. No Interactions-API branch.
- Every round sends the **current builder state** (including manual edits) as the
  authoritative starting point, plus the **cumulative comment log** → guarantees no-reversion.
- Refinement reuses generation's machinery: stage-1 select on the comment, exercise pool =
  current workout's exercises (kept) + comment-selected candidates, the same system prompt
  (modes/presets/weight rules/recent-performance progression), and validation.

## UX (`templates/create.html`)

A **refinement panel** shown whenever the builder has exercises:
- a comment `<textarea>` + **Apply AI adjustment** button,
- a running list of applied comments (chips), and a status line.
Applying: serialize the current builder → generation JSON, POST to `/api/workout/refine`,
load the returned workout back into the builder, append the comment to the client-held
`commentLog`. Disabled while a request is in flight and when the generator isn't configured.

## Builder serialization

Add `serializeBuilderForAI()` producing the **generation schema** (distinct from the Save
payload, which targets the Speediance API):
```js
{ name, exercises: workoutData.map(ex => ({
    id: ex.groupId,
    presetId: ex.selectedPresetId,
    isUnilateralExpanded: ex.isUnilateral || undefined,   // sets already hold L/R — don't double on reload
    sets: ex.sets.map(s => ({ reps: s.reps, weight: s.weight, mode: s.mode, rest: s.rest, unit: s.unit })),
})) }
```
`isUnilateralExpanded` is set for unilateral exercises so the refine round-trip (serialize →
model echoes it → `loadWorkoutIntoBuilder`) does not re-double the L/R sets.

## Pure core: `workout_gen.build_refinement_user_prompt(current_workout, comment, comment_log) -> str`

No I/O, unit-tested. Presents the current workout as JSON in the output schema, the new
instruction, and the cumulative log:
```
This is an EDIT of an existing workout, not a new one.

CURRENT WORKOUT (JSON, in the output format):
{json of current_workout}

Apply this change: "{comment}"

Earlier instructions you must KEEP honoring (do not undo them):
- {comment_log[0]}
- {comment_log[1]}
...

Return the FULL updated workout in the same JSON format. Preserve every exercise, set, and
value not affected by the change (including any I edited by hand); change only what the
instruction requires.
```
Empty `comment_log` → omit that section. The system prompt (available exercises, modes,
presets, weight rules, PROGRESSION) is reused from `build_generation_system_prompt`.

## App wiring (`app.py`)

`POST /api/workout/refine` (auth-gated), body
`{current_workout, comment, comment_log?, recent_days?}`:
1. Validate: `comment` non-empty and `current_workout.exercises` non-empty (else 400).
2. Guard the generator provider is configured (same message/shape as generate).
3. `library = get_library()`; `catalog = compact_catalog(library)`.
4. Stage-1 select on the **comment** → candidate ids.
5. `pool_ids = current-workout exercise ids (prepended) + candidates`, deduped, capped at 60
   — so existing exercises are always available and relevant swaps surface.
6. `details = get_batch_details(pool_ids)`; `merged = [merge_exercise(...)]`.
7. Recent-performance (default 30, honoring `recent_days`), same as generate.
8. `system = build_generation_system_prompt(merged, unit, has_recent=..., has_refs=False)`;
   `user = build_refinement_user_prompt(current_workout, comment, comment_log)`.
9. `chat_with(active generator provider/model)` → `_extract_json` (one repair retry) →
   `validate_workout` → return `{ok, workout, warnings}`.
10. Save the refine into the generation history (`save_workout_gen_last`) with
    `kind: "refine"` and the comment, so it appears in "Recent prompts".

Errors mirror generate: provider-not-ready message, JSON-failure message, auth → 401,
recent-perf/detail failures degrade (auth still propagates).

## Testing

`tests/test_workout_gen.py`:
- `build_refinement_user_prompt`: current-workout JSON present, the comment present, every
  comment-log entry present, the "return the FULL updated workout" instruction present, and
  the "EDIT of an existing workout" framing; empty log omits the log section without error.

`tests/` (app-level, isolated): `/api/workout/refine` rejects empty comment / empty current
workout with 400; is auth-gated.

Live smoke: take an existing workout, refine with "add a set to every exercise", confirm the
returned workout keeps the same exercises with one more set each; then a second comment
("make the first exercise heavier") and confirm the first change persists (no reversion).

## Files touched

- `workout_gen.py` — `build_refinement_user_prompt`.
- `app.py` — `POST /api/workout/refine` (reuses generation machinery + history save with kind).
- `templates/create.html` — refinement panel, `serializeBuilderForAI()`, `applyRefinement()`,
  client `commentLog`.
- `tests/test_workout_gen.py` (+ an app-level refine test).

## Non-goals

- No Gemini Interactions API / server-side threads.
- No streaming; no diff view (the whole updated workout reloads into the builder).
- No persistence of the comment log across page reloads (session-only, like the builder).
