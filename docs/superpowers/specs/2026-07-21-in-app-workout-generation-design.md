# In-app AI workout generation — design

Date: 2026-07-21

## Goal

Replace the current copy-paste flow (Generate Prompt → paste into an external LLM →
paste the JSON back via Import) with an **in-app** generator: describe a workout, the
app calls your chosen provider/model, shows the result in the builder, lets you refine it
by comment and by hand, and imports it under a name — all without leaving the page.

The app already has a full multi-provider LLM client (`coach.py`: Anthropic, OpenAI,
Google, plus Grok/Ollama) with live model discovery and an SSRF allowlist, and the entire
prompt text already exists as JavaScript in `create.html` (`generateFullPrompt`). This
feature moves prompt-building into a pure server-side module and wires the loop.

## Decisions (locked during brainstorming)

- **Dedicated** provider+model picker for workout generation, separate from the coach's,
  but **sharing** the per-provider API keys already stored.
- **Auto-pick** the exercise pool via a cheap first model pass (two-stage generation),
  rather than category checkboxes or sending all 1,042 exercises.
- **Phased** delivery: Phase 1 (generate → builder → save), Phase 2 (references +
  assessment context), Phase 3 (comment-driven refinement + edits fed back).

## Non-goals (YAGNI)

- No streaming responses; a spinner while the call runs is enough.
- No persistent server-side "generation session" store — refinement is **stateless**
  (the client sends current state + full comment history each call).
- No new exercise-detail scraping beyond the existing `get_batch_details`.
- No change to how workouts are saved (`save_workout` is reused unchanged).

## Module: `workout_gen.py` (pure, unit-tested)

No I/O. Mirrors `coach.py`'s pure region. Functions:

- `compact_catalog(library) -> str` — one line per exercise: `[ID] Title (Category, Focus,
  Target)` plus `[TIMED]/[TIMED+LEVEL]/[UNILATERAL]` tags. Names only, no descriptions.
  Used for the stage-1 selection pass and as the swap-catalog during refinement.
- `build_selection_prompt(user_request, catalog) -> str` — asks the model to return a
  JSON array of candidate exercise IDs relevant to the request.
- `parse_selected_ids(text, library) -> list[int]` — extract IDs from the model's reply,
  keep only IDs present in `library`. Falls back to a bounded keyword match if the reply
  is unusable, so stage 2 always has a pool.
- `build_generation_system_prompt(exercises, unit_label) -> str` — the full "professional
  fitness coach…" system prompt, ported verbatim in intent from `generateFullPrompt`:
  available exercises (the selected pool, WITH descriptions), MODES, PRESET IDS, WEIGHT
  UNIT rules, TIMED and UNILATERAL sections (emitted only when the pool contains such
  exercises), and the OUTPUT JSON schema.
- `build_generation_user_prompt(user_request, references, assessment) -> str` — the user's
  request, plus (Phase 2) referenced workouts' JSON + exercise descriptions, plus an
  optional assessment-window summary.
- `validate_workout(obj, library) -> (ok, cleaned, warnings)` — parse/verify the returned
  workout: `name` + `exercises[]`; every exercise `id` must exist in `library` (drop with
  a warning otherwise); coerce timed/level/unilateral fields per the existing rules;
  ensure `presetId`/`unit` consistency. Returns a cleaned object safe to load into the
  builder, plus human-readable warnings.
- `build_refinement_system_prompt(exercises, unit_label, catalog) -> str` — like the
  generation system prompt but for editing an existing workout, and it includes the
  compact catalog so the model may swap in alternatives by ID.
- `build_refinement_user_prompt(current_workout, comment_log, new_comment) -> str` — states
  the current workout JSON as ground truth, lists **every** prior comment as standing
  constraints ("keep honoring all of these"), then the new instruction. This is what
  prevents reversion of earlier comments and manual edits.

## Provider config (Settings, part 1)

`coach_config.json` gains a top-level block:

```json
"workout_generator": { "provider": "anthropic", "model": "" }
```

The API key and endpoint come from the existing `providers[provider]` entry (keys are
shared per provider). New `coach.py` helpers:

- `workout_provider(cfg)` / `workout_model(cfg)` — read the block with sane defaults.
- `chat_with(provider, model, prompt, cfg, system=None, timeout=120) -> (ok, text)` —
  build a provider-config dict `{api_key, endpoint, model}` from the shared key + the given
  model and dispatch through the existing `_chat_provider`. Reuses the SSRF allowlist.

Settings UI: an **"AI Workout Generator"** card mirroring the coach card — provider
dropdown (Anthropic/OpenAI/Google), a **Load models** button hitting the existing
`/api/coach/models?provider=` route, a model `<select>`, and Save. The public config
endpoint is extended to report `workout_generator` (never the keys).

Routes:
- `GET/POST /api/workout/config` — auth-gated; GET returns `{provider, model}` + the
  provider list (no keys); POST saves `{provider, model}` after validating the provider is
  one of anthropic/openai/gemini.

## Generation flow (parts 2, 4, 7 — Phase 1)

Create page (`create.html`): the "Generate Prompt" button and its two-step modal are
replaced by, at the top of the builder, an **instructions blurb + free-text textarea** and
a **Generate Workout** button. (Import JSON stays as a manual fallback.)

`POST /api/workout/generate` (auth-gated), body `{request, references?, assessment_days?}`:
1. Guard: workout-gen provider has a key + model, else the coach-style "configure in
   Settings" message.
2. `library = get_library()`; `catalog = compact_catalog(library)`.
3. Stage 1: `chat_with(wp, wm, build_selection_prompt(request, catalog))` →
   `parse_selected_ids` → candidate IDs (bounded, e.g. ≤ 60).
4. `details = get_batch_details(candidate_ids)` for descriptions.
5. Stage 2: `system = build_generation_system_prompt(details, unit_label)`;
   `user = build_generation_user_prompt(request, references, assessment)`;
   `chat_with(wp, wm, user, system=system)`.
6. `validate_workout(parsed, library)`; on JSON-parse failure, one automatic repair retry
   ("return only valid JSON"), then a clear error.
7. Return `{ok, workout, pool_ids, warnings}` — `workout` in the same shape the builder's
   `processImport` already consumes; `pool_ids` is echoed back for stateless refinement.

Client: on success, load `workout` into the builder via the existing import path, surface
any `warnings`, and focus the name field. Save uses the existing `POST /create`.

## Context buttons (part 3 — Phase 2)

- **Add Workout Reference**: `GET /api/workout/list` → `[{name, code, id}]`. A modal lists
  them; picking one appends its name to the request box and adds its `code` to a
  client-held `references` list. On generate/refine, the server fetches each referenced
  workout (`get_workout_detail(code)`) and its exercises' descriptions
  (`get_batch_details`) and includes them in the user prompt.
- **Include assessment**: 7/14/30-day buttons set a client-held `assessment_days`. On
  send, the server gathers that window (the existing `/api/assessment` gather logic,
  refactored into a helper `_gather_assessment_sessions(days)`) and appends a
  `build_assessment_prompt` summary. `ASSESSMENT_DAYS` is extended to include 30 for this
  path (the assessment page keeps 1/3/7/14).

## Refinement loop (parts 5, 6 — Phase 3)

Below the builder: a **comment textarea** + **Apply AI adjustment** button, and a visible
**running list of prior comments**.

`POST /api/workout/refine` (auth-gated), body `{current_workout, pool_ids, comment_log,
new_comment, references?, assessment_days?}`:
1. `details = get_batch_details(union(pool_ids, ids in current_workout))`;
   `catalog = compact_catalog(library)`.
2. `system = build_refinement_system_prompt(details, unit_label, catalog)`;
   `user = build_refinement_user_prompt(current_workout, comment_log, new_comment)`.
3. `chat_with(...)` → `validate_workout` → return `{ok, workout, warnings}`.

The client keeps `current_workout` synced from the **builder** (so manual add/delete/
reorder/modify are included), appends `new_comment` to `comment_log`, and re-loads the
returned workout into the builder. Statelessness makes this robust to restarts and
guarantees no reversion: current state + full comment log are re-sent every call.

## Errors

- Provider not ready → coach-style friendly message, HTTP 200 `{ok:false, text}`.
- Model/JSON failure → one repair retry, then `{ok:false, text}` with the raw snippet.
- Auth error on any Speediance call → 401 via `_is_auth_error`, matching siblings.
- All model output is treated as untrusted: it is validated server-side, and rendered in
  the builder as structured fields (never as HTML).

## Files touched

- Create: `workout_gen.py`, `tests/test_workout_gen.py`,
  `templates/` partial(s) as needed.
- Modify: `coach.py` (`workout_provider`/`workout_model`/`chat_with`, config block),
  `app.py` (`/api/workout/config`, `/generate`, `/list`, `/refine`; assessment gather
  helper + 30-day window), `templates/create.html` (generate box/button, refinement UI,
  reference/assessment buttons; retire the prompt modal), `templates/settings.html`
  (workout-generator card), `coach_config.json` shape (gitignored).

## Testing

`tests/test_workout_gen.py` (pure, no network): compact catalog format + tags; selection
parsing (valid, garbage, fallback); generation system prompt (unit label present, timed/
unilateral sections appear only when relevant, schema present); `validate_workout` (drops
unknown IDs, coerces timed/level, flags unilateral); refinement user prompt (current JSON
+ every prior comment present). Existing `coach` tests stay green; `chat_with` reuses the
tested dispatch.

## Phasing

- **Phase 1:** `workout_gen.py` core + Settings card + `/api/workout/config` +
  `/api/workout/generate` (two-stage) + create-page box/button + load-into-builder + save.
- **Phase 2:** `/api/workout/list`, Add Workout Reference, assessment context (+30-day).
- **Phase 3:** `/api/workout/refine`, comment box, running comment log, edits-fed-back.

Each phase ships working software. One spec (this doc); a separate implementation plan per
phase, beginning with Phase 1.
