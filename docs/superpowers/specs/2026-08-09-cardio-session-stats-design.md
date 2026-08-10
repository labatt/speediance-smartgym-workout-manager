# Cardio/Rowing Session Stats + Cross-Session Trend — Design

**Date:** 2026-08-09
**Status:** Approved for planning

## Problem

Opening a cardio/rowing session in the history detail modal (e.g. "30 Minutes
HIIT Rowing Workout", trainingId 2023440) shows the dead-end message:

> No exercise breakdown available for this session type.
> Detailed data is available for Program and Custom workouts.

That message is misleading on two counts:

1. This *is* a Program (type 2), yet it shows the "available for Program" text.
2. There **is** real data — the session just has no set-by-set strength
   breakdown because it's continuous rowing, not discrete weighted sets.

The distinction the panel actually cares about is **strength (reps×weight sets)**
vs **cardio (continuous telemetry: distance, energy, pace)** — not
Program-vs-Custom.

## What data exists (confirmed against live API, 2026-08-09)

For trainingId 2023440:

- **Exercise breakdown**: genuinely empty. Both `courseTrainingInfoDetail` and
  `cttTrainingInfoDetail` return `data: []`.
- **`session_info`** (`courseTrainingInfo/{id}`) is rich:
  `trainingTime=530`, `calorie=161`, `totalEnergy=29580.29`,
  `totalDistance=892.71`, `completionRate=29.0`, `rpe=6`,
  `existBoatingSkiDataGraph=true`, `courseMode=3`, `goalType=2`.
- This `session_info` payload **already reaches the frontend** as `data.session`
  (guaranteed by the 2026-08-09 session-info-403 route fix). So the per-session
  numbers need **no new backend call**.

### Within-session time-series graph: UNREACHABLE

`existBoatingSkiDataGraph: true` is only a boolean. The per-second/per-stroke
time series is **not** embedded in `session_info` (678 bytes, no arrays) or the
(empty) detail response, and is **not** served by any guessable endpoint — 12
candidate paths across `/api/app/trainingInfo/*` and `/api/mobile/v2/report/*`,
keyed by trainingId / code / uuid, all returned clean 404s (no throttling).
Obtaining it would require capturing the real mobile app's network traffic.
**Out of scope.**

### The meaningful graph is cross-session

RPE is one value per session — there is no within-session RPE curve. So the
useful graph is a **trend across sessions**: one point per cardio session,
plotted over time (avg pace, avg speed, avg power, distance, calories, RPE).

## Records-list findings (cheap cardio discriminator)

`get_training_records` returns fields incl. `type`, `courseType`, `mileage`,
`totalEnergy`, `totalCapacity`, `bikeType`, but **not** `totalDistance` / `rpe`.
Across 49 sessions:

- `mileage` is `0` for every record (not populated at record level) — useless.
- The two rowing sessions ("30 Minutes HIIT Rowing Workout", "Row & Flow") are
  the **only** records with `courseType == 2`. A strength Program ("Elite
  Fat-Burning Program") is `courseType == 0`.
- `totalCapacity == 0` matches the rowing sessions but ALSO matches short/skipped
  strength sessions — not a clean discriminator on its own.

**Conclusion:** `courseType == 2` cleanly identifies rowing today. Encode it as
an extensible constant `CARDIO_COURSE_TYPES = {2}`; widen when a bike/ski example
appears.

## Design

### Part A — Per-session cardio stats panel

**Where:** `renderDetail(data, rec)` in `templates/history.html`.

**Trigger:** when `exercises.length === 0` (no strength breakdown) AND the session
carries a cardio signal:
`session.existBoatingSkiDataGraph === true || session.totalDistance > 0 || session.totalEnergy > 0`.
→ render the cardio stats panel. Otherwise keep the existing "no breakdown"
message (a genuinely empty strength session, e.g. session_info unavailable).

**Pure function** `deriveCardioStats(session)` in `static/workout-logic.js`
(mirrors the tested-pure-module pattern; exported to `module.exports` and
`window.WorkoutLogic`). Input: the `session` object. Output object, each field
null when its inputs are missing/zero (never `NaN`, never `Infinity`):

| Field         | Formula / source                                  | Example (2023440) |
|---------------|---------------------------------------------------|-------------------|
| `durationSec` | `trainingTime`                                    | 530               |
| `distanceM`   | `totalDistance`                                   | 892.71            |
| `pace500`     | `durationSec / (distanceM/500)` seconds/500m      | 296.8 → 4:57      |
| `speedMs`     | `distanceM / durationSec`                         | 1.68              |
| `calorie`     | `calorie`                                          | 161               |
| `calPerMin`   | `calorie / (durationSec/60)`                       | 18.2              |
| `energyKJ`    | `totalEnergy / 1000`                              | 29.6              |
| `avgWatts`    | `totalEnergy / durationSec` (assumes energy in J) | 55.8              |
| `completion`  | `completionRate` (percent)                        | 29                |
| `rpe`         | `rpe`                                              | 6                 |

Guards: `pace500`/`speedMs` require `distanceM>0 && durationSec>0`; `calPerMin`
requires `durationSec>0`; `avgWatts` requires `totalEnergy>0 && durationSec>0`.

**Presentation:** reuse the existing dark stat-tile styling. Tiles rendered only
for non-null fields. `avgWatts` labeled "Avg power" with a subtle hint that it's
derived (so a wrong energy-unit assumption is obvious and removable). Pace shown
`m:ss /500m`; speed shown `m/s` (with `km/h` in parentheses).

### Part B — Cross-session cardio trend chart

**Backend route** `GET /api/cardio/trend` in `app.py`:

1. Unauthorized guard (mirror existing routes).
2. Pull records over a wide window via `get_training_records(start, end)` where
   `start` is a fixed early date (e.g. `"2020-01-01"`) and `end` is today.
   (Single call returns full history as observed.)
3. Filter to `rec['courseType'] in CARDIO_COURSE_TYPES`.
4. For each candidate, obtain per-session stats:
   - Check the on-disk cache first (keyed by `trainingId`; past sessions are
     immutable).
   - On miss, fetch `session_info` **guarded**: a non-auth error (e.g. 403
     "You do not have access") skips that session; an auth error re-raises to the
     outer handler → 401. Never 500 the whole route for one bad session.
   - Compute the same derived metrics as Part A (shared pure helper — see below).
   - Store `{trainingId, startTimestamp, title, ...metrics}` in cache.
5. Return `{ "sessions": [...] }` sorted ascending by `startTimestamp`.

**Cache:** a JSON file next to the other persisted state (pattern of
`WORKOUT_GEN_LAST_FILE`), e.g. `CARDIO_TREND_CACHE_FILE`, mapping
`str(trainingId) -> stats dict`. Load/merge/save with the same defensive
try/except used elsewhere. No TTL needed — completed sessions don't change.

**Shared derivation:** the metric math (pace/speed/power/cal-min) is defined once.
`deriveCardioStats` is JS; the backend needs the same math for the trend. To
avoid drift, put the backend copy in a small pure Python helper
`cardio_stats.py` (`derive_cardio_stats(session_info) -> dict`) with its own unit
tests, and keep the JS `deriveCardioStats` as the client-side twin (both covered
by tests using the same worked example, 2023440, as the oracle).

**Frontend chart:** a section under the stats tiles, shown only when the trend
has ≥1 cardio session.
- Metric switcher (buttons/segmented control): Pace /500m · Speed · Power ·
  Distance · Calories · RPE. Default: Pace /500m.
- Dependency-free inline **SVG line chart** (no external lib; app only loads
  Tailwind). X = time (session order), Y = selected metric. The **opened
  session's point is highlighted** (larger dot / distinct color).
- Note for pace: lower is better; axis/label should make direction clear (e.g.
  "lower = faster"). Do not invert other metrics.
- Empty state (no other cardio sessions): show just the single point / a "first
  cardio session logged" note. Single-point and flat-series must not divide by
  zero.

**Pure geometry helper** `chartGeometry(values, width, height, opts)` in
`static/workout-logic.js`: maps an array of numbers to `{points: [{x,y}...],
path: "M...L..."}` scaled to the box, with padding. Handles: empty array →
empty; single value → centered point; all-equal values → flat mid-line (no
divide-by-zero). Unit-tested.

## Testing

- **`deriveCardioStats` (JS):** normal session (2023440 oracle), zero-distance
  (pace/speed null), missing fields (all-null, no NaN), zero-duration.
- **`derive_cardio_stats` (Py):** same oracle + edge cases; assert JS/Py agree on
  the worked example values.
- **`chartGeometry` (JS):** empty, single point (centered), flat series
  (mid-line), normal series (endpoints at padding box), monotonic mapping.
- **Route resilience (Py):** `/api/cardio/trend` with one candidate's
  `session_info` raising a non-auth error → that session skipped, status 200,
  others present; an auth error → 401.
- **Cardio filter (Py):** records with `courseType` 2 included, 0/other excluded.
- **Regression:** existing history-detail tests still pass; strength sessions
  with real breakdowns unaffected; genuinely empty strength session still shows
  the "no breakdown" message.

## Files touched

- `templates/history.html` — cardio panel + trend chart section + metric switcher
  + fetch `/api/cardio/trend`; branch in `renderDetail`.
- `static/workout-logic.js` — `deriveCardioStats`, `chartGeometry` (+ exports).
- `tests/workout-logic.test.mjs` — JS unit tests for both.
- `cardio_stats.py` (new) — `derive_cardio_stats`, `CARDIO_COURSE_TYPES`.
- `app.py` — `/api/cardio/trend` route + cache load/save helpers.
- `tests/test_cardio_trend.py` (new) — route + filter + Py derivation tests.
- `README.md` — document the feature.

## Out of scope (YAGNI)

- Within-session per-second graph (unreachable — see above).
- Bike/ski course-types until a real example is observed (`CARDIO_COURSE_TYPES`
  is the single extension point).
- External charting libraries.
- A dedicated Cardio Trends page (kept in the detail modal per decision).
