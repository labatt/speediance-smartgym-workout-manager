# Changelog

## v1.1.0 — Vita support, per-rep telemetry, and four silent data-corruption fixes

This release makes the app usable if you own a **Speediance Vita**, and surfaces the
per-rep performance data the API has always returned but the UI discarded.

Every claim below was verified against the live API on a real account — the API's
data model is documented in [`docs/API-NOTES.md`](docs/API-NOTES.md), including the
traps that caused these bugs.

---

### Fixed — Vita exercises were completely unusable

**The API version-gates Vita content, and the hardcoded `Versioncode` was too old.**

`api_client.py` announced itself as app **v4.3.4** (`Versioncode: 40304`). Vita shipped
in **v4.4.0**. Any request whose response would contain a Vita exercise was rejected with:

```
code: 98
message: "Please upgrade the APP version in System Setting"
```

surfacing in the UI as `Error loading data: Please upgrade the APP version in System Setting`.

Two consequences, one loud and one silent:

1. **Any saved workout containing a Vita movement would not open.** `/edit/<code>` failed
   and bounced to the dashboard.
2. **All 7 Vita exercises were invisible in the exercise library** — so they could not be
   added to a workout at all. This failed *silently*: the library just returned 885
   exercises instead of 892, with no error anywhere.

Threshold confirmed by bisection: `40399` blocked, `40400` accepted. Now set to `40400`.

| | `Versioncode: 40304` | `Versioncode: 40400` |
|---|---|---|
| Library size | 885 | **892** |
| Vita exercises present | 0 | **7** |

### Fixed — Vita levels were displayed as `0` and destroyed on save

Vita intensity is a **level**, stored by the API in a `level` field. `weights` is sent as
all zeros:

```
Vita Twist   setsAndReps "20,20,20,20"   level "10,12,14,16"   weights "0,0,0,0"
```

Two bugs, the second much worse than the first:

1. **The workout builder read `weights` instead of `level`**, so every Vita set displayed
   an intensity of **0**.
2. **`save_workout` clamped level to `1-10`.** A device-authored workout legitimately uses
   levels 10, 12, 14, 16 — opening it in this app and pressing Save silently crushed the
   12/14/16 down to 10, producing a flat level-10 workout with no warning.

The `1-10` range was never real. The API accepts levels up to at least 100 and stores them
verbatim; it does not clamp. **This app no longer clamps either** — level is floored at 1
with no ceiling, because inventing a ceiling is precisely what destroyed real data.

Fixed in five places: the load path, the save clamp, the `Level (1-10)` column header, the
level input's `max` attribute, and the input clamp function.

### Fixed — timed sets were rendered as failed rep targets in History

A Vita set is a fixed **seconds** window in which reps are counted. The history view
decoded only one value of the `completionMethod` enum:

```js
const isTimer = ex.completionMethod === 0;   // Vita is 5 — so this was false
```

Vita therefore fell through to the rep-based branch and rendered `15 / 20`, which reads as
"15 of 20 reps". It is actually **15 reps in a 20-second window**. Worse, the branch then
computed `completed = reps >= target` → `15 >= 20` → `false`, and painted the set **red as
a failure** — when the full 20 seconds had in fact been completed.

`completionMethod` decides what `targetCount` *means*:

| Value | Set completes when… | `targetCount` is | `finishedCount` is |
|---|---|---|---|
| `1` | a rep target is hit | reps | reps done |
| `0` | a duration elapses | **seconds** | always `0` |
| `2` | a duration elapses (Row/Ski) | **seconds** | always `0` |
| `5` | a duration elapses (**Vita**) | **seconds** | **reps achieved in the window** |

History now reads `15 reps in 20s`, judges completion on *holding the window* rather than
on a rep count, and degrades honestly to `12 reps in 14s of 20s` or `skipped`.

### Fixed — the AI prompt's `presetId` was silently discarded

The generated prompt asks the model for `"presetId"`, but the importer read `ex.preset`.
Every preset an AI chose was dropped and replaced with **Custom (-1)** — so an RM
prescription like "9 RM" was re-read as **9 kg**. Silent, and wrong. The importer now
accepts either key.

### Fixed — `completionMethod: 5` was mapped to `kcal` instead of `sec`

`getSetGoalUnit()` treated Vita as "burn-to-complete", so the builder labelled Vita sets
**Kcal** with a 1–9999 range. It is a seconds window. (History returns `targetCount=20`
with `time=20` for a 20s set, and `{reps: 20, unit: "sec"}` round-trips as
`setsAndReps="20"` with `completionMethod=5`.)

### Fixed — exporting a timed workout lost its `unit`

`buildExportJSON` dropped the `unit` field, so exporting a Vita workout and re-importing it
turned seconds back into reps.

---

### Added — per-rep performance telemetry in History

The device records **one value per rep** for power, rope speed, range of motion, time under
tension and resistance, plus its own computed form scores. None of it was shown.

Each exercise in a session now gets an inline SVG chart (no new dependencies — same
approach as the existing radar chart) plotting **every rep in sequence**, with dotted
dividers at set boundaries, so within-set fatigue and across-set decline read in one glance:

- **Power** per rep (split left/right when both cables work)
- **Resistance** per rep — flat for rep-based work, visibly ramping on Vita
- A summary line: `avg 115 W · peak 139 W · 35 lbs · 0.78 m/s · ROM 0.56 m · TUT 201s`
- The device's own form scores: `force 5/5 · ROM 4/5 · balance 3/5`
- PR badges when `maxWeightPr` / `oneRepMaxPr` / `totalCapacityPr` fire

### Added — the AI prompt now understands Vita and unilateral exercises

`Generate Prompt` previously emitted every exercise as if it took reps and a weight. With
Vita now in the library, the model would confidently write "12 reps @ 40 kg" for Vita Pull —
and `save_workout` would turn that 40 into a level. Exercises are now tagged and the rules
explained:

```
[455212933054465] Vita Pull [TIMED+LEVEL] (Category: Training, Focus: Abs, ...)
[437972850049025] Archer Rows [UNILATERAL] (Category: Training, Focus: Abs, ...)
```

- **`[TIMED]` / `[TIMED+LEVEL]`** — `reps` carries the duration in **seconds**, `unit` must
  be `"sec"`, and for Vita `weight` is the **intensity level** (stepping up across sets,
  e.g. 10 → 12 → 14 → 16, is the normal pattern). `presetId` must be `-1`.
- **`[UNILATERAL]`** — one set entry is applied to **both** sides by default. To prescribe a
  different load per side, opt in with `"isUnilateralExpanded": true` and list sets
  alternating **Left, Right, Left, Right**.

### Added — `docs/API-NOTES.md`

The API's data-model traps, written down so nobody has to rediscover them: the ragged
telemetry arrays, the `weights`-is-not-resistance trap, the `completionMethod` enum, the
`Versioncode` gate, and the unilateral/level/timed write contracts.
