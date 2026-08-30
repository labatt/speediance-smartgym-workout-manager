# Wellness Project Exercise Backfill — Design

**Date:** 2026-08-30
**Status:** Approved for planning

## Problem

The user's Wellness Project dashboard (`wellnessproject.ai`) receives workout
sessions from the Speediance mobile app via Health Connect, but **only as
summaries** — e.g. `2026-08-29: Strength Training · 33 min · 341 cal`, with **no
exercises logged**. The per-exercise detail (sets, reps, weights) exists in
Speediance, keyed by `trainingId`, but never crosses the Health Connect bridge.

The user wants the Speediance Flask app (`speediance.labattsimon.com`) to
**find Wellness Project workouts that have no exercises and backfill them from
the matching Speediance session** — on demand and, later, automatically.

### Confirmed against live data (2026-08-30)

- WP `[ID 696827] 2026-08-29 Strength Training · 33 min · 341 cal` has notes
  `"Imported from Health Connect... (com.speediance.speediance_mobile)"` and
  **no exercises**.
- Speediance `[trainingId 1103072] "Miami Pull - Back Biceps Traps"` = 1949 s
  (~33 min), **341 cal**, 5 exercises (Barbell Bent Over Row, Seated Barbell Lat
  Pulldown, Seated Barbell Wide Row, Standing Barbell Biceps Curl, Standing
  Barbell Shrugs). **This is the worked oracle for tests.**
- Across the 90-day window, **date + calories is an essentially exact join key**
  (341=341, 481=481, 452=452, 434=434, 609=609, 680=680, 570=570, …).

### Two streams that must NOT be confused

1. **Speediance strength imports** — WP `"Strength Training · N cal"` rows, no
   NSI, empty. **These are the backfill targets.**
2. **Real-gym days** — WP entries like `"Upper @ Gym · NSI 24.5"`, logged
   directly into WP by Claude on days the user trains at a gym (not the
   Speediance). These already carry exercises and NSI. **Never touched** — the
   "only write to workouts with zero exercises" rule protects them automatically.

Rowing / cardio sessions (Speediance `courseType == 2`, `totalCapacity == 0`)
have no discrete exercises and are **out of scope** (the cardio-stats feature
already covers them).

## Feasibility: Wellness Project auth (probed 2026-08-30)

WP has **no REST API and no API key**. Its OAuth discovery documents show the
MCP endpoint (`/api/mcp`) *is* the API, protected by OAuth:

```
issuer:                https://wellnessproject.ai
authorization_endpoint https://wellnessproject.ai/api/oauth/authorize
token_endpoint         https://wellnessproject.ai/api/oauth/token
registration_endpoint  https://wellnessproject.ai/api/oauth/register
grant_types_supported  ["authorization_code", "refresh_token"]   # NO client_credentials
code_challenge_methods ["S256"]                                   # PKCE required
token_endpoint_auth    ["none"]                                   # public client
scopes_supported       ["mcp"]
```

Consequence: there is **no machine-only grant**. The app must obtain the first
token via an interactive **authorization-code + PKCE** flow, then rely on
**refresh tokens** for unattended operation ("offline access" pattern). This is
sufficient for the scheduled scan: authorize once in a browser, refresh silently
thereafter.

**Chosen bootstrap:** in-app **Connect** button (approach A) — a `/wp/connect`
route drives the browser OAuth flow; the app stores and rotates the refresh
token itself.

**Operational caveat:** public-client refresh tokens typically rotate on every
use and may expire after inactivity. Regular use keeps them alive; a long gap
may require re-connecting. The design fails **gracefully** to a "reconnect
required" state — never a silent breakage.

## Architecture

The Flask app becomes an **MCP client to Wellness Project only**. It continues
to read Speediance through its **existing `SpeedianceClient`**
(`get_training_records`, `get_training_detail`) — the GM Manager MCP is not
involved. Exactly one new external dependency is added.

Three new units, each with a single purpose:

### `wellness_client.py` — WP connection layer

- **OAuth:** dynamic client registration (DCR), PKCE (S256) authorize-URL
  construction, `authorization_code` exchange, **silent refresh with rotation**,
  token persistence.
- **MCP transport:** JSON-RPC `initialize` + `tools/call` over HTTPS for
  `list_workouts`, `get_workout`, `update_workout`. Handles the MCP HTTP
  response framing (`Accept: application/json, text/event-stream`; parse a
  single JSON result whether returned raw or as one SSE `data:` event).
- **Errors:** `WellnessAPIError` (base), `WellnessAuthError` (missing/expired/
  revoked credentials → reconnect required), mirroring the Speediance client's
  typed-exception pattern.
- **Public surface (consumed by `app.py` / `reconcile.py`):**
  - `is_connected() -> bool`
  - `begin_authorization() -> (authorize_url, state)` — registers client if
    needed, stores PKCE verifier + state in the pending-store.
  - `complete_authorization(code, state) -> None` — validates state, exchanges
    code, persists tokens.
  - `list_workouts(start_date, end_date) -> list`
  - `get_workout(session_id) -> dict`
  - `update_workout(session_id, add_exercises=[...], notes=None) -> dict`

### `reconcile.py` — matching engine (pure, no network)

- `match_candidates(wp_empties, sp_strength_sessions) -> {confident[], ambiguous[]}`
  Pairs each empty WP workout to a Speediance session by **date (±1 day) +
  calories (exact, tolerance ±2)**; duration as tie-break.
  - **confident** — exactly one in-scope Speediance strength session matches.
  - **ambiguous** — zero or multiple candidates, or calorie mismatch beyond
    tolerance.
- `sp_detail_to_wp_exercises(detail) -> list` — transforms Speediance session
  detail into the `add_exercises` payload (see Transform below).

Both functions are unit-tested against the **Aug 29 Miami Pull oracle**.

### `app.py` — routes + scan entry point

Detailed under Triggers.

## Data flow — one backfill pass

1. **Auth:** ensure a valid WP access token (refresh if near-expiry). No refresh
   token → return `{status: "connect_required"}`; a scheduled pass logs and
   no-ops.
2. **WP side:** `list_workouts(window)` → pre-filter to likely Speediance
   strength imports (has calories, no NSI, not a walk/run/miles entry) → confirm
   each is genuinely empty via `get_workout` (reads its date + calories).
3. **Speediance side:** `SpeedianceClient.get_training_records(window)` → keep
   strength only (`totalCapacity > 0` and `courseType != 2`).
4. **Match:** `match_candidates(...)`.
5. **Apply:**
   - *confident* → `get_training_detail` → `sp_detail_to_wp_exercises` →
     `update_workout(session_id, add_exercises=..., notes="Backfilled from
     Speediance trainingId N")`.
   - *ambiguous* → collected, **never auto-written**.
6. **Report:** return `{applied[], flagged[], errors[]}`; scheduled passes also
   write `wellness_reconcile_report.json` so flagged items surface in the UI.

**Two invariants (both free from the design):**
- **Only WP workouts with zero exercises are ever written** → real-gym `@ Gym`
  entries are safe.
- **Idempotent** — a backfilled workout is no longer empty, so it never matches
  again.

## Connect / token lifecycle

### `GET /wp/connect`
1. If no registered client: **DCR** — POST `registration_endpoint` with
   `redirect_uris:["https://speediance.labattsimon.com/wp/callback"]`,
   `token_endpoint_auth_method:"none"`, grants `["authorization_code",
   "refresh_token"]`, `response_types:["code"]`, `scope:"mcp"`,
   `client_name:"Speediance Backfill"` → store `client_id`.
2. Generate PKCE verifier + S256 challenge and a random `state`; persist both in
   the pending-store keyed by `state` (few-minute TTL).
3. 302 → `authorization_endpoint?response_type=code&client_id=…&redirect_uri=…&
   scope=mcp&state=…&code_challenge=…&code_challenge_method=S256`.

### `GET /wp/callback?code=…&state=…`
1. Validate `state` against the pending-store (CSRF guard); reject if
   missing/expired.
2. POST `token_endpoint` `grant_type=authorization_code` with `code`,
   `redirect_uri`, `client_id`, `code_verifier` → `{access_token, refresh_token,
   expires_in}`.
3. Persist to `wellness_tokens.json` (chmod 600), clear the pending entry,
   redirect to `/wp/reconcile` showing **Connected**.

### Silent refresh
Before any MCP call, if the access token is expired/near-expiry: POST
`token_endpoint` `grant_type=refresh_token`. **Persist the new refresh token
immediately** (rotation). On `invalid_grant`: clear tokens → `WellnessAuthError`
→ "reconnect required".

### State store — a file, not memory or Flask session
Gunicorn runs multiple workers, so `/wp/connect` and `/wp/callback` may hit
different workers. The PKCE verifier + state live in **`wellness_pending.json`**
(state → {verifier, created_at}, TTL a few minutes), which survives that split
and avoids needing a Flask `SECRET_KEY`.

## Triggers

Routes (all behind the existing nginx basic-auth gate):

| Route | Purpose |
|-------|---------|
| `GET /wp/connect` | Start OAuth (Connect button target). |
| `GET /wp/callback` | OAuth redirect target; exchanges code, stores tokens. |
| `GET /wp/reconcile` | Status/report page: connection state, **Backfill now** button, last scan's applied/flagged/errors, per-item picker to resolve ambiguous matches. |
| `POST /wp/backfill?mode=manual\|scheduled` | Run one pass; returns `{applied[], flagged[], errors[]}`. UI calls via `fetch`; cron via `curl`. |
| `POST /wp/apply` | Write one user-confirmed ambiguous match `{wp_session_id, sp_training_id, sp_type}`. |

**Scheduling** — a daily **cron** entry (not an in-process scheduler, which
would fire once per gunicorn worker):

```
# once daily
curl -sS -u labatt:<basic-auth-pw> -X POST \
  'https://speediance.labattsimon.com/wp/backfill?mode=scheduled'
```

Reuses the existing basic-auth credentials; documented in the README/deploy
notes. Window: **last 90 days** (a module constant; also WP `list_workouts`'
per-call max).

Scheduled vs manual differ only in unattended safety: **scheduled auto-applies
confident matches and records flagged ones to `wellness_reconcile_report.json`**;
it never writes an ambiguous match. Manual behaves the same but the flagged list
is shown immediately for interactive resolution via `/wp/apply`.

## Transform — `sp_detail_to_wp_exercises`

Speediance `get_training_detail` → WP `update_workout(add_exercises=[...])`.

**Input shape:** the transform consumes the **Flask app's own
`SpeedianceClient.get_training_detail` output — the raw Speediance API shape**
(exercises with `actionLibraryName`, per-set `finishedReps` / weight arrays),
**not** the GM Manager MCP's normalized `{name, setLog}` shape used during
recon. The app already parses this structure for the history-detail view
(`renderDetail`); the transform reuses that same parsing. The Miami Pull oracle
values are identical either way, but the plan must pin the exact raw field names
against a live `get_training_detail(1103072, 5)` sample before coding, and unit
tests fixture that raw payload.

Per exercise: `{name, sets:[...]}`. The Speediance exercise **name is passed
through** to WP's resolver (WP matches it to its own canonical library; unmatched
names are WP's to flag).

Per set (from the raw Speediance detail):
- `reps` → `reps`.
- `weight` → `weight_lb` **verbatim** — the account's display unit is lb and
  Speediance already returns lb; **no conversion** (per the API-quirks memory).
- A timed/isometric set (seconds, no load) → `hold_length_sec`.
- A zero-weight movement → `is_bodyweight: true`.

**v1 is flat:** every set `slot_type:"working"`; **no superset grouping** and no
`equipment` inference (both explicitly deferred — YAGNI). Each backfilled workout
receives a provenance note `"Backfilled from Speediance trainingId N"` so
app-written entries are traceable and distinct from hand-logged ones.

## Error handling

- **Not connected / refresh failed** → `WellnessAuthError` → `/wp/reconcile`
  shows Connect; scheduled pass logs + no-ops (exit 0, nothing written).
- **Per-session failure** (one `update_workout`, one detail fetch) → captured in
  `errors[]`, the pass continues for the rest.
- **Speediance auth error** → surfaced (the app's existing `_is_auth_error`
  handling / 401 path).
- **Ambiguous match** → never written; always flagged.

## Testing

unittest + mock, matching `tests/test_history_detail.py`. No live network, no
live OAuth.

- **`tests/test_reconcile.py`**
  - `match_candidates`: confident (single match), ambiguous (zero / multiple
    same-day / calorie beyond tolerance), ±1-day date tolerance, duration
    tie-break.
  - `sp_detail_to_wp_exercises`: **Aug 29 Miami Pull oracle** → exact 5-exercise
    payload with correct reps/weights; bodyweight set → `is_bodyweight`; timed
    set → `hold_length_sec`; unit passthrough (no conversion).
- **`tests/test_wellness_client.py`** (HTTP layer mocked)
  - PKCE challenge correctness (verifier → S256 → base64url, no padding).
  - DCR request shape; token exchange.
  - **refresh-with-rotation persists the new refresh token**; `invalid_grant` →
    `WellnessAuthError` + tokens cleared.
  - MCP `tools/call` request shaping and response parsing (raw JSON and single
    SSE `data:` event).
  - state validation: callback with unknown/expired state is rejected.
- **`tests/test_wp_backfill_routes.py`** (both clients mocked)
  - `/wp/backfill` → applied/flagged summary; not-connected → connect-required.
  - `/wp/apply` happy path writes the chosen match.
- **Regression:** existing suites still green (the two known-unrelated e2e
  failures in `test_e2e_workouts.py` are pre-existing and ignored).

## Files

**New:**
- `wellness_client.py`
- `reconcile.py`
- `tests/test_reconcile.py`, `tests/test_wellness_client.py`,
  `tests/test_wp_backfill_routes.py`

**Runtime, git-excluded (via `.git/info/exclude`):**
- `wellness_tokens.json` (secrets; chmod 600)
- `wellness_pending.json` (transient OAuth state)
- `wellness_reconcile_report.json` (last scan's flagged items)

**Modified:**
- `app.py` — `/wp/*` routes + backfill scan entry point.
- `README.md` — feature description + cron setup.
- `.git/info/exclude` — ignore the three runtime JSON files.

## Out of scope (YAGNI)

- Rowing / cardio sessions (no discrete exercises; covered by cardio-stats).
- Superset grouping and `equipment` inference in the transform.
- Editing / re-syncing a workout that already has exercises (only empties are
  written).
- Any WP domain beyond workouts (sleep, meals, runs, etc.).
- A machine-to-machine grant (WP does not offer one).
