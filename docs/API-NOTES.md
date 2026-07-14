# Speediance API — data model notes

Everything here was verified against the live API on a real account. These are the traps
that caused the bugs fixed in [v1.1.0](../CHANGELOG.md) — most of them fail *silently*,
which is what makes them expensive.

---

## 1. `Versioncode` gates content — it is not cosmetic

`api_client.py` sends a `Versioncode` header claiming which app release the client is.
**Speediance gates newer content behind newer version codes.** Any request whose response
would contain a gated exercise is rejected outright:

```
code: 98
message: "Please upgrade the APP version in System Setting"
```

Vita shipped in app **v4.4.0**, so `Versioncode` must be **>= 40400**. Confirmed by
bisection: `40399` blocked, `40400` accepted.

The nasty part is the *silent* half. The workout-detail endpoint returns a loud error, but
the **library endpoint just omits the gated exercises** — 885 results instead of 892, no
error, no warning. If a movement you know exists is missing from the library, suspect this
first.

**Expect this to recur.** Anything Speediance ships after v4.4.0 will be invisible the same
way.

## 2. `completionMethod` decides what `targetCount` means

On the exercise object. Read it before interpreting any set.

| Value | Set completes when… | `targetCount` is | `finishedCount` is |
|---|---|---|---|
| `1` | a rep target is hit | **reps** | reps done |
| `0` | a duration elapses | **seconds** | always `0` (no reps counted) |
| `2` | a duration elapses (Row/Ski) | **seconds** | always `0` |
| `5` | a duration elapses (**Vita**) | **seconds** | **reps achieved inside the window** |

So a Vita set reading `finishedCount: 15, targetCount: 20` is **15 reps in a 20-second
window** — not 15 of 20 reps, and not a failed set.

Per set, `time` is the seconds actually worked. `time: 0` with `finishedCount: 0` means the
set was skipped. Across 90 days of history, every set where `time != targetCount` was a
skipped set — which is what confirms `time` is *actual* and `targetCount` is *target*.

`completionMethod: 5` is **seconds, not kcal.**

## 3. Vita intensity is a LEVEL, in `level` — and it has no ceiling

Vita exercises (`dataStatType: 6`) carry intensity in a **`level`** CSV. `weights` is sent
as all zeros:

```
Vita Twist   setsAndReps "20,20,20,20"   level "10,12,14,16"   weights "0,0,0,0"
```

Read `level`, not `weights`, or every Vita set shows an intensity of `0`.

**Do not clamp level.** A device-authored workout legitimately uses levels 10, 12, 14, 16,
and stepping the level up across sets is normal. The API accepts levels up to at least 100
and stores them verbatim — it does not clamp. A client-side ceiling of 10 silently crushed
real workouts to a flat level 10 on save.

The library exposes `recommendedLevel` (5 for Vita Pull) but no min/max.

## 4. `weights` is NOT the resistance on dual-cable exercises

On a **single**-cable exercise, `weights` is byte-identical to the populated side array. On
a **dual**-cable exercise it is something else entirely — a derived force series (cable
tension, which spikes during acceleration):

```
Vita Pull, set 1
  leftWeights  (13) : [7.5, 11.5, 11.5, 12, 12, 12, ...]              -> 7.5-12
  rightWeights (14) : [7.5, 11, 11.5, 12, 12.5, 12.5, ...]            -> 7.5-12.5
  weights      (27) : [7.5, 7.5, 48.5, 47, 47.5, 48.5, 12, 30.5, ...] -> 7.5-48.5
```

`weights` holds values (48.5, 47, 30.5) present in **neither** side array, and it is not
their concatenation or even the same multiset. Reading it as resistance makes it look like
Vita *drops* the load from 48.5 → 11.5. It does not: it **ramps up** 7.5 → 12 and settles
~11.5.

Use `leftWeights` / `rightWeights`. Treat `weights` as a fallback only on single-cable
exercises.

## 5. Per-rep telemetry arrays are RAGGED — never zip them by index

`finishedReps[].trainingInfoDetail` carries one value per rep for each channel — but the
channels **do not agree on length**, even within one set. Vita Pull, set 1,
`finishedCount = 13`:

```
leftAmplitudes  -> 13 values
leftWatts       -> 12 values
rightAmplitudes -> 14 values
rightWatts      -> 13 values
```

The obvious loop is quietly wrong:

```js
for (let i = 0; i < reps; i++) plot(watts[i], weights[i]);   // WRONG
```

It does not crash. It draws rep 12's power against rep 11's weight and produces a chart
that looks plausible and **lies**. Treat each series independently, scaled over its own
length; never pair two channels positionally.

Available per-rep channels: `leftWatts`/`rightWatts` (power), `leftRopeSpeeds`/`rightRopeSpeeds`
(m/s), `leftAmplitudes`/`rightAmplitudes` (ROM, metres), `leftFinishedTimes` (time under
tension), `leftBreakTimes` (pause between reps), `leftMaxRopeLengths`, `leftWeights`/`rightWeights`,
`leftTimestamps`.

`leftMinRopeLengths` / `rightMinRopeLengths` are **not** per-rep — they are 48–78 raw
high-frequency position samples.

Unused-but-available on the exercise object: `forceControlScore`, `amplitudeStableScore`,
`bilateralBalanceScore`, `completionScore`, and PR flags `maxWeightPr`, `oneRepMaxPr`,
`totalCapacityPr`.

## 6. Unilateral exercises: sides are assigned by index parity

For `isLeftRight === 1`, `save_workout` assigns sides by position — **even index = Left (1),
odd index = Right (2)** — and the server stores `leftRight: "1,2,1,2"`.

The JSON importer duplicates each set to both sides by default. To prescribe a **different
load per side**, opt in:

```json
{
  "id": 437972850049025,
  "presetId": -1,
  "isUnilateralExpanded": true,
  "sets": [
    { "reps": 12, "weight": 35, "mode": 1, "rest": 60 },
    { "reps": 10, "weight": 30, "mode": 1, "rest": 60 },
    { "reps": 11, "weight": 34, "mode": 1, "rest": 60 },
    { "reps":  9, "weight": 29, "mode": 1, "rest": 60 }
  ]
}
```

Verified round-trip: stored as `leftRight "1,2,1,2"`, `12@35 L / 10@30 R / 11@34 L / 9@29 R`.

Two working sets become **four** entries. Do not set the flag unless you are listing both
sides, or you get double the volume you intended.

## 7. Writing a timed / Vita set

```json
{ "reps": 30, "weight": 12, "mode": 1, "rest": 60, "unit": "sec" }
```

- `reps` = **duration in seconds** (not a rep count)
- `weight` = the **level** (Vita only); it lands in `level`, and `weights` is written as 0
- `unit` = `"sec"`
- `presetId` = **-1** — timed exercises have no RM presets

Round-trips as `setsAndReps "30"`, `level "12"`, `weights "0"`, `completionMethod 5`.

Note `completionMethod` and `countType` are **normalised server-side** from the exercise
library, so the per-set values the client sends for those two are effectively advisory.

## 8. Weights are in the account's unit, on BOTH read and write — nothing converts

The API stores and returns workout weights in the unit configured on the account
(`config.json` `unit: 1` = lbs, `0` = kg). **No conversion happens anywhere in this app:**

- **Read** — the raw value is displayed with a unit label. `35` on an imperial account means
  35 lbs. Do not add a kg→lbs conversion here.
- **Write** — the value is sent verbatim (`api_client.py`, `api_weight = weight_val`). An old
  comment there claimed *"JS already converted LBS→KG before sending"*; it is **false**.
  `lbsToKg()` exists in `workout-logic.js` and is aliased in `create.html`, but is never
  called on the save path.

So **import JSON must be in the account's unit**, not kg. The generated AI prompt used to
hardcode `Custom (KG)` and "absolute weight (kg)" — on an imperial account the model
prescribed kilograms, they were saved verbatim as pounds, and the workout came out at
roughly **45% of the intended load**, silently. The prompt now states the account's actual
unit.

The one genuine exception: the **library's** `recommendedWeight` *is* in kg, which is why
`kgToLbs()` is applied to it (and only to it) when populating a default weight.

RM-based presets (`presetId != -1`) are unitless — they go in `counterweight2`, not
`weights`.

## 9. The importer accepts `preset` or `presetId`

The app's own export writes `preset`; the generated AI prompt asks the model for
`presetId`. The importer historically read only `preset`, so **every AI-chosen preset was
silently dropped to Custom (-1)** — meaning an RM prescription got re-read as raw kg/lbs.
Both keys are now accepted.
