# Changelog

## v1.1.0 — Workout insight, and compatibility with newer machine software

Two themes:

**Get more insight out of your training.** The Gym Monster records a great deal about every rep
you perform — power, rope speed, range of motion, time under tension, per-rep resistance — plus
its own form scores. Almost all of it was being fetched and discarded. It is now charted.

**Keep working as Speediance ships new software.** The API gates newer content behind newer app
versions, and this client announced an outdated one. Anything added to the machine after that
release was rejected or silently invisible — and once it did load, several features were
misreading the newer data models, in two cases corrupting real workouts on save.

Every claim below was verified against the live API on a real account. The data model, and the
traps that caused these bugs, are documented in [`docs/API-NOTES.md`](docs/API-NOTES.md).

---

## Fixed

### The client announced an outdated app version, hiding newer content

`api_client.py` sent `Versioncode: 40304` — app **v4.3.4**. The API version-gates content: any
request whose response would contain an exercise introduced in a later release was rejected with

```
code: 98
message: "Please upgrade the APP version in System Setting"
```

surfacing in the UI as `Error loading data: Please upgrade the APP version in System Setting`.

Two consequences, one loud and one silent:

1. **Any saved workout containing a newer exercise would not open.** `/edit/<code>` failed and
   bounced back to the dashboard.
2. **Those exercises were invisible in the library**, so they could not be added to a workout at
   all. This failed *silently* — the library simply returned a shorter list, with no error
   anywhere. The Vita movements, added in app v4.4.0, were the visible casualty: 885 exercises
   returned instead of 892.

Threshold confirmed by bisection: `40399` blocked, `40400` accepted. Now set to `40400`.

**Expect this to recur.** `Versioncode` is a hardcoded claim about which app release this client
is, and anything Speediance ships behind a newer gate will disappear the same way — silently, in
the library's case.

### Intensity levels were displayed as `0` and destroyed on save

Some exercises are scored by an intensity **level** rather than a weight (`dataStatType: 6` — the
Vita movements). The API carries the level in a `level` field and sends `weights` as all zeros:

```
setsAndReps "20,20,20,20"   level "10,12,14,16"   weights "0,0,0,0"
```

Two bugs, the second far worse:

1. **The builder read `weights` instead of `level`**, so every such set displayed an intensity of
   **0**.
2. **`save_workout` clamped level to `1-10`.** A workout authored on the machine legitimately uses
   levels 10, 12, 14, 16 — opening it here and pressing Save silently crushed the 12/14/16 down to
   10, producing a flat level-10 workout with no warning.

The `1-10` range was never real. The API accepts levels up to at least 100 and stores them
verbatim; it does not clamp. **Neither do we now** — level is floored at 1 with no ceiling, because
inventing a ceiling is exactly what destroyed real data.

Fixed in five places: the load path, the save clamp, the `Level (1-10)` column header, the level
input's `max` attribute, and the input clamp function.

### Timed sets were rendered as failed rep targets

A timed set is a fixed **seconds** window in which reps are counted. History decoded only one value
of the `completionMethod` enum:

```js
const isTimer = ex.completionMethod === 0;   // timed-with-reps is 5 — so this was false
```

Those sets therefore fell through to the rep-based branch and rendered `15 / 20`, which reads as
"15 of 20 reps". It is actually **15 reps inside a 20-second window**. Worse, that branch then
computed `completed = reps >= target` → `15 >= 20` → `false`, and painted the set **red as a
failure** — when the full 20 seconds had in fact been completed.

`completionMethod` decides what `targetCount` *means*:

| Value | Set completes when… | `targetCount` is | `finishedCount` is |
|---|---|---|---|
| `1` | a rep target is hit | reps | reps done |
| `0` | a duration elapses | **seconds** | always `0` |
| `2` | a duration elapses (row/ski) | **seconds** | always `0` |
| `5` | a duration elapses (Vita) | **seconds** | **reps achieved in the window** |

History now reads `15 reps in 20s`, judges completion on *holding the window* rather than against a
rep target it never had, and degrades honestly to `12 reps in 14s of 20s` or `skipped`.

### The AI-chosen preset was silently discarded

The generated prompt asks the model for `"presetId"`, but the importer read `ex.preset`. Every
preset an AI chose was dropped and replaced with **Custom (-1)** — so an RM prescription like
"9 RM" was re-read as **9 kg**. Silent, and wrong. The importer now accepts either key.

### `completionMethod: 5` was mapped to `kcal` instead of `sec`

`getSetGoalUnit()` treated it as burn-to-complete, so the builder labelled those sets **Kcal** with
a 1–9999 range. It is a seconds window. (History returns `targetCount=20` with `time=20` for a 20s
set, and `{reps: 20, unit: "sec"}` round-trips as `setsAndReps="20"` with `completionMethod=5`.)

### Exporting a timed workout lost its `unit`

`buildExportJSON` dropped the `unit` field, so exporting a timed workout and re-importing it turned
seconds back into reps.

---

## Added

### Per-rep performance telemetry in history

The machine records **one value per rep** for power, rope speed, range of motion, time under
tension and resistance, plus its own computed form scores. None of it was shown.

Each exercise in a session now gets an inline SVG chart (no new dependencies) plotting **every rep
in sequence**, with dotted dividers at set boundaries, so within-set fatigue and across-set decline
read in one glance:

- **Power** per rep, split left/right when both cables are working
- **Resistance** per rep — flat on rep-based work, visibly ramping where the machine auto-regulates
- A summary line: `avg 115 W · peak 139 W · 35 lbs · 0.78 m/s · ROM 0.56 m · TUT 201s`
- The machine's own form scores: `force 5/5 · ROM 4/5 · balance 3/5`
- PR badges when `maxWeightPr` / `oneRepMaxPr` / `totalCapacityPr` fire

### The AI prompt now states each exercise's contract

`Generate Prompt` previously described every exercise as if it took reps and a weight. Exercises
that don't work that way are now tagged, and the rules spelled out:

```
[455212933054465] Vita Pull [TIMED+LEVEL] (Category: Training, Focus: Abs, ...)
[437972850049025] Archer Rows [UNILATERAL] (Category: Training, Focus: Abs, ...)
```

- **`[TIMED]` / `[TIMED+LEVEL]`** — `reps` carries the duration in **seconds**, `unit` must be
  `"sec"`, and for level-based exercises `weight` is an **intensity level** (stepping up across
  sets, e.g. 10 → 12 → 14 → 16, is the normal pattern). `presetId` must be `-1`.
- **`[UNILATERAL]`** — one set entry applies to **both** sides by default. To prescribe a different
  load per side, opt in with `"isUnilateralExpanded": true` and list sets alternating **Left,
  Right, Left, Right**.

### `docs/API-NOTES.md`

The API's data-model traps, written down so nobody has to rediscover them: the `Versioncode` gate,
the `completionMethod` enum, level-vs-weight, the ragged per-rep telemetry arrays, the
`weights`-is-not-resistance trap on dual-cable exercises, the unilateral index-parity contract, and
the units asymmetry between read and write.
