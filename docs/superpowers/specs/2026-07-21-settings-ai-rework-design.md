# Settings AI rework — design

Date: 2026-07-21

## Goal

Make the Settings AI section separate **key management** from **role assignment**, so the
athlete can: enter an API key per provider, test it and download its model list in one
click, and then independently choose which provider+model powers the **Coach** and which
powers the **Workout Generator**. Fix the model dropdown showing only the saved model
(e.g. just `gpt-oss:120b`) when the provider actually offers many.

## Background / current state

- `coach.py` already stores per-provider `{api_key, endpoint, model}` plus a separate
  `workout_generator: {provider, model}` block; keys are shared per provider. So Coach and
  Generator are *already* independent in storage — this rework makes that explicit in the UI.
- `/api/coach/models?provider=P` already validates the key and returns the live model list
  (a successful list is proof the key is valid).
- **Bug:** `settings.html`'s `onProviderChange()` seeds the coach model `<select>` with only
  the saved model until the user clicks "Load models," so it shows one entry. Meanwhile the
  provider may offer many (Ollama returns 18: deepseek-v4, glm-5.x, gpt-oss:20b/120b, kimi,
  qwen3.5, minimax, nemotron, mistral-large-3, …), and those are already cached in
  `config.known_models['ollama']` from the weekly check.
- `/api/workout/config` POST currently accepts only `anthropic|openai|gemini`.

## Decisions (locked in brainstorming)

- **One "Test & load models" button per provider** — validates the key and downloads+caches
  the model list in a single action (they are the same API call).
- **All five providers** (Anthropic, OpenAI, Google, Ollama, xAI/Grok) selectable for both
  the Coach and the Generator.

## Non-goals (YAGNI)

- No change to how the Coach or Generator actually call the model.
- No new provider beyond the existing five; no streaming; no new key storage location.
- No separate "test key" call distinct from listing models (they are one call).

## UI: `templates/settings.html` AI section, rewritten in two parts

**Part A — AI providers & keys.** One row per provider (`anthropic, openai, gemini, ollama,
grok`), each with:
- masked key `<input>` (placeholder "paste to set / change"; a "· key set" marker when the
  server reports `has_key`), and a "get one → <host>" link (existing `KEY_LINKS`).
- Ollama only: an editable endpoint field (existing behavior; allowlisted server-side).
- a **Test & load models** button → `testProvider(p)`:
  1. If a new key (or Ollama endpoint) was typed, POST it to `/api/coach/config`
     (`{providers: {p: {api_key, endpoint}}}`) first.
  2. GET `/api/coach/models?provider=p`. On `ok`, show `✓ key valid · N models` and keep the
     returned list in a client-side `modelsByProvider[p]`; the server also caches it (below).
     On failure show `✗ <error>`.

**Part B — Assign models.** Two independent selector rows:
- **Coach:** provider `<select>` (all five; label marks whether each has a key) + model
  `<select>` + `↻` (re-fetch) + **Save**. Save posts `{provider, providers: {provider:
  {model}}}` to `/api/coach/config` (sets the active provider + that provider's model).
- **Workout Generator:** provider `<select>` + model `<select>` + `↻` + **Save**. Save posts
  `{provider, model}` to `/api/workout/config`.
- Each model `<select>` is filled from `modelsByProvider[provider]`, seeded on page load from
  the config's `known_models` so lists appear immediately without a click (this is the
  gpt-oss fix). If the cache is empty for a provider, the dropdown shows
  "— Test & load models above —"; `↻` calls the same fetch as Part A.

The old single "AI Coach" card and the separate "AI Workout Generator" card are replaced by
this two-part layout. The weekly new-model banner (`checkNewModels`) is preserved.

## Backend: `app.py` (small)

1. `/api/coach/models` (GET): on a successful fetch, cache the list into
   `config.known_models[provider]` and `coach.save_config(config)`, so Part B can populate
   from cache on the next load. (Currently it fetches without persisting.)
2. `/api/coach/config` (GET): the public config additionally returns `known_models` (already
   stored; just expose it). Never returns keys — unchanged.
3. `/api/workout/config` (POST): accept any provider in `coach.PROVIDERS` (all five), not
   just `anthropic|openai|gemini`. The GET response additionally reports `has_key` per
   provider and the cached model list is available via the coach config, so the UI can fill
   the generator dropdown from cache too.

No `coach.py` schema change is required (the config already has `known_models` and
`workout_generator`). A tiny helper may be added if it keeps `app.py` clean.

## Errors

- Bad key → `/api/coach/models` returns `{ok:false, error}`; the row shows `✗ <error>`
  (rendered via `textContent`, not HTML).
- Provider-not-keyed on Save (Coach/Generator) → the existing "add a key / configure in
  Settings" messaging applies at use-time; the UI marks unkeyed providers in the dropdowns.
- SSRF: only Ollama's endpoint is editable and it stays behind the existing allowlist.

## Testing

`tests/test_coach.py` (or a small new test): `/api/workout/config` POST accepts `ollama`
and `grok` (previously rejected); the model-fetch route caches into `known_models`
(assert the config gains the provider's list after a successful fetch — using a stubbed
`coach.list_models` so no network). Front-end verified by rendering `/settings` and a live
Ollama model load showing all 18.

## Files touched

- `templates/settings.html` — rewrite the AI section into Part A + Part B (the bulk).
- `app.py` — cache models in `/api/coach/models`; expose `known_models` in coach config GET;
  accept all five providers in `/api/workout/config` POST; add `has_key` to workout config GET.
- `tests/test_coach.py` (or `tests/test_app_ai.py`) — the backend assertions above.
