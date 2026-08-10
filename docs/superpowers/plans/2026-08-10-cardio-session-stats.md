# Cardio Session Stats + Cross-Session Trend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface cardio/rowing sessions in the history detail modal with a per-session stats panel and a dependency-free cross-session trend chart, instead of the misleading "No exercise breakdown available" dead-end.

**Architecture:** The per-session numbers already reach the browser as `data.session` (guaranteed by the 2026-08-09 session-info-403 fix), so the stats panel is pure frontend. Metric math lives once as a pure function, mirrored in Python (`cardio_stats.py`) for the trend endpoint and in JS (`static/workout-logic.js`) for the panel/chart. A new backend route `/api/cardio/trend` pulls the athlete's cardio sessions (filtered by `courseType`), computes per-session metrics (disk-cached, since past sessions are immutable), and returns a time-sorted series the frontend charts with inline SVG.

**Tech Stack:** Flask (Python), vanilla JS + Tailwind (no chart lib), `node --test` for JS unit tests, `pytest`/`unittest` for Python. Interpreter: `.venv/bin/python` (system python lacks Flask).

## Global Constraints

- All Python runs under `.venv/bin/python` (e.g. `.venv/bin/python -m pytest ...`). System python has no Flask.
- JS unit tests run with `node --test tests/` (Node ≥18 built-in runner).
- Pure logic goes in `static/workout-logic.js` (browser) / `cardio_stats.py` (server) — no DOM, no I/O — and is exported to BOTH `module.exports` and `window.WorkoutLogic` (JS) so tests and browser both see it.
- `CARDIO_COURSE_TYPES = {2}` is the single extension point for identifying cardio sessions; do not scatter the literal `2`.
- Never emit `NaN`/`Infinity`: any derived stat whose inputs are missing/zero must be `None`/`null` and omitted.
- Weights/units unrelated here; distances are meters, pace is seconds per 500m (rowing standard).
- Frontend strings that come from the model/API are inserted with `.textContent`, never `innerHTML`, per the app's XSS rule.
- Worked oracle for all derivation tests — trainingId 2023440: `trainingTime=530`, `calorie=161`, `totalEnergy=29580.29`, `totalDistance=892.71`, `completionRate=29.0`, `rpe=6` → `pace500≈296.9`, `speedMs≈1.68`, `calPerMin≈18.2`, `energyKJ≈29.6`, `avgWatts≈55.8`, `completion=29`, `rpe=6`.

---

### Task 1: Pure Python cardio derivation + cardio filter

**Files:**
- Create: `cardio_stats.py`
- Test: `tests/test_cardio_stats.py`

**Interfaces:**
- Consumes: nothing (pure).
- Produces:
  - `CARDIO_COURSE_TYPES` — a `set[int]`, `{2}`.
  - `is_cardio_record(rec: dict) -> bool` — True iff `rec.get('courseType') in CARDIO_COURSE_TYPES`.
  - `derive_cardio_stats(s: dict) -> dict` — maps a `session_info` dict to
    `{durationSec, distanceM, pace500, speedMs, calorie, calPerMin, energyKJ, avgWatts, completion, rpe}`.
    Each value is a number or `None`. Rounding: `pace500`→1dp, `speedMs`→2dp, `calPerMin`→1dp, `energyKJ`→1dp, `avgWatts`→0dp (int), others passthrough (numbers or None).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cardio_stats.py
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cardio_stats import derive_cardio_stats, is_cardio_record, CARDIO_COURSE_TYPES  # noqa: E402

ORACLE = {"trainingTime": 530, "calorie": 161, "totalEnergy": 29580.29,
          "totalDistance": 892.71, "completionRate": 29.0, "rpe": 6}


class TestDeriveCardioStats(unittest.TestCase):
    def test_oracle_session(self):
        r = derive_cardio_stats(ORACLE)
        self.assertEqual(r["durationSec"], 530)
        self.assertAlmostEqual(r["distanceM"], 892.71, places=2)
        self.assertAlmostEqual(r["pace500"], 296.9, delta=0.2)
        self.assertAlmostEqual(r["speedMs"], 1.68, delta=0.02)
        self.assertAlmostEqual(r["calPerMin"], 18.2, delta=0.2)
        self.assertAlmostEqual(r["energyKJ"], 29.6, delta=0.1)
        self.assertAlmostEqual(r["avgWatts"], 56, delta=1)
        self.assertEqual(r["completion"], 29.0)
        self.assertEqual(r["rpe"], 6)

    def test_zero_distance_nulls_pace_and_speed(self):
        r = derive_cardio_stats({"trainingTime": 300, "totalDistance": 0, "calorie": 50})
        self.assertIsNone(r["pace500"])
        self.assertIsNone(r["speedMs"])
        self.assertAlmostEqual(r["calPerMin"], 10.0, delta=0.1)

    def test_missing_fields_are_none_never_nan(self):
        r = derive_cardio_stats({})
        for k in ("pace500", "speedMs", "calPerMin", "avgWatts", "distanceM", "rpe"):
            self.assertIsNone(r[k], f"{k} should be None on empty input")

    def test_zero_duration_nulls_rate_stats(self):
        r = derive_cardio_stats({"trainingTime": 0, "totalDistance": 100, "totalEnergy": 500})
        self.assertIsNone(r["pace500"])
        self.assertIsNone(r["calPerMin"])
        self.assertIsNone(r["avgWatts"])


class TestIsCardioRecord(unittest.TestCase):
    def test_rowing_courseType_2_is_cardio(self):
        self.assertTrue(is_cardio_record({"courseType": 2}))

    def test_strength_courseType_0_is_not(self):
        self.assertFalse(is_cardio_record({"courseType": 0}))

    def test_missing_courseType_is_not(self):
        self.assertFalse(is_cardio_record({}))

    def test_extension_point_is_a_set(self):
        self.assertIn(2, CARDIO_COURSE_TYPES)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cardio_stats.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'cardio_stats'`.

- [ ] **Step 3: Write minimal implementation**

```python
# cardio_stats.py
"""Pure cardio/rowing session derivations. No I/O, no Flask — unit-tested.

Speediance logs cardio sessions (rowing/ski) as continuous telemetry rather than
reps x weight sets, so the strength breakdown is empty. The meaningful numbers
live in the session-info summary; this module turns that summary into display
and trend metrics. Mirrors static/workout-logic.js::deriveCardioStats — keep the
two in sync (both covered by the same worked oracle, trainingId 2023440).
"""

# The only signal that cleanly separates cardio courses from strength in the
# records list (mileage is always 0; totalCapacity==0 also matches skipped
# strength sessions). Widen when a bike/ski example is observed.
CARDIO_COURSE_TYPES = {2}


def is_cardio_record(rec):
    """True iff a training-records entry is a cardio session we can chart."""
    return rec.get("courseType") in CARDIO_COURSE_TYPES


def _num(v):
    """Coerce to float, or None if missing/non-numeric."""
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def derive_cardio_stats(s):
    """Map a session_info dict to display/trend metrics. Missing/zero inputs -> None."""
    dur = _num(s.get("trainingTime"))
    dist = _num(s.get("totalDistance"))
    cal = _num(s.get("calorie"))
    energy = _num(s.get("totalEnergy"))

    has_dur = dur is not None and dur > 0
    has_dist = dist is not None and dist > 0

    pace500 = round(dur / (dist / 500.0), 1) if has_dur and has_dist else None
    speed = round(dist / dur, 2) if has_dur and has_dist else None
    cal_min = round(cal / (dur / 60.0), 1) if has_dur and cal is not None else None
    energy_kj = round(energy / 1000.0, 1) if energy is not None else None
    watts = round(energy / dur, 0) if has_dur and energy is not None and energy > 0 else None

    return {
        "durationSec": int(dur) if dur is not None else None,
        "distanceM": round(dist, 2) if dist is not None else None,
        "pace500": pace500,
        "speedMs": speed,
        "calorie": cal,
        "calPerMin": cal_min,
        "energyKJ": energy_kj,
        "avgWatts": watts,
        "completion": _num(s.get("completionRate")),
        "rpe": _num(s.get("rpe")),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_cardio_stats.py -q`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add cardio_stats.py tests/test_cardio_stats.py
git commit -m "feat: pure cardio-stats derivation + cardio-course filter"
```

---

### Task 2: JS twin `deriveCardioStats`

**Files:**
- Modify: `static/workout-logic.js` (add function + both exports)
- Test: `tests/workout-logic.test.mjs` (add import + tests)

**Interfaces:**
- Consumes: nothing (pure).
- Produces: `deriveCardioStats(session)` — same fields/rounding/null-rules as the Python twin in Task 1. Exported in `module.exports` and `window.WorkoutLogic`.

- [ ] **Step 1: Write the failing test**

Add to `tests/workout-logic.test.mjs` — extend the destructure from `require(...)` to include `deriveCardioStats`, then append:

```js
// ---------------------------------------------------------------------------
// deriveCardioStats — mirrors cardio_stats.py (oracle trainingId 2023440)
// ---------------------------------------------------------------------------
const CARDIO_ORACLE = { trainingTime: 530, calorie: 161, totalEnergy: 29580.29,
                        totalDistance: 892.71, completionRate: 29.0, rpe: 6 };

test('deriveCardioStats: oracle session matches Python twin', () => {
    const r = deriveCardioStats(CARDIO_ORACLE);
    assert.equal(r.durationSec, 530);
    assert.ok(Math.abs(r.distanceM - 892.71) < 0.01);
    assert.ok(Math.abs(r.pace500 - 296.9) < 0.2, `pace500=${r.pace500}`);
    assert.ok(Math.abs(r.speedMs - 1.68) < 0.02, `speedMs=${r.speedMs}`);
    assert.ok(Math.abs(r.calPerMin - 18.2) < 0.2, `calPerMin=${r.calPerMin}`);
    assert.ok(Math.abs(r.energyKJ - 29.6) < 0.1, `energyKJ=${r.energyKJ}`);
    assert.ok(Math.abs(r.avgWatts - 56) < 1, `avgWatts=${r.avgWatts}`);
    assert.equal(r.completion, 29);
    assert.equal(r.rpe, 6);
});

test('deriveCardioStats: zero distance nulls pace and speed', () => {
    const r = deriveCardioStats({ trainingTime: 300, totalDistance: 0, calorie: 50 });
    assert.equal(r.pace500, null);
    assert.equal(r.speedMs, null);
    assert.ok(Math.abs(r.calPerMin - 10.0) < 0.1);
});

test('deriveCardioStats: missing fields are null, never NaN', () => {
    const r = deriveCardioStats({});
    for (const k of ['pace500', 'speedMs', 'calPerMin', 'avgWatts', 'distanceM', 'rpe']) {
        assert.equal(r[k], null, `${k} should be null`);
    }
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test tests/workout-logic.test.mjs`
Expected: FAIL — `deriveCardioStats is not a function` (undefined import).

- [ ] **Step 3: Write minimal implementation**

In `static/workout-logic.js`, add before the export block:

```js
/**
 * Map a session_info object to cardio display/trend metrics.
 * Twin of cardio_stats.py::derive_cardio_stats — keep in sync (same oracle 2023440).
 * Missing/zero inputs yield null (never NaN/Infinity).
 * @param {Object} s - session_info
 * @returns {Object}
 */
function deriveCardioStats(s) {
    s = s || {};
    const num = v => {
        if (v === null || v === undefined || v === '') return null;
        const n = Number(v);
        return Number.isFinite(n) ? n : null;
    };
    const r1 = (n, d) => n === null ? null : Math.round(n * 10 ** d) / 10 ** d;

    const dur = num(s.trainingTime);
    const dist = num(s.totalDistance);
    const cal = num(s.calorie);
    const energy = num(s.totalEnergy);
    const hasDur = dur !== null && dur > 0;
    const hasDist = dist !== null && dist > 0;

    return {
        durationSec: dur === null ? null : Math.trunc(dur),
        distanceM: dist === null ? null : r1(dist, 2),
        pace500: (hasDur && hasDist) ? r1(dur / (dist / 500), 1) : null,
        speedMs: (hasDur && hasDist) ? r1(dist / dur, 2) : null,
        calorie: cal,
        calPerMin: (hasDur && cal !== null) ? r1(cal / (dur / 60), 1) : null,
        energyKJ: energy === null ? null : r1(energy / 1000, 1),
        avgWatts: (hasDur && energy !== null && energy > 0) ? Math.round(energy / dur) : null,
        completion: num(s.completionRate),
        rpe: num(s.rpe),
    };
}
```

Then add `deriveCardioStats` to BOTH export lists (`module.exports = {... , deriveCardioStats}` and `window.WorkoutLogic = {... , deriveCardioStats}`).

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test tests/workout-logic.test.mjs`
Expected: PASS (all prior tests + 3 new).

- [ ] **Step 5: Commit**

```bash
git add static/workout-logic.js tests/workout-logic.test.mjs
git commit -m "feat: deriveCardioStats JS twin of cardio_stats.py"
```

---

### Task 3: Pure SVG chart geometry helper

**Files:**
- Modify: `static/workout-logic.js` (add function + both exports)
- Test: `tests/workout-logic.test.mjs`

**Interfaces:**
- Consumes: nothing (pure).
- Produces: `chartGeometry(values, width, height, pad=8)` →
  `{points: [{x, y}], path: "M x y L x y ..."}`. Higher value = higher on chart
  (smaller y). Empty → `{points: [], path: ''}`. Single value → one centered
  point. All-equal values → flat mid-line. No divide-by-zero.

- [ ] **Step 1: Write the failing test**

Add `chartGeometry` to the destructured import, then append to `tests/workout-logic.test.mjs`:

```js
// ---------------------------------------------------------------------------
// chartGeometry — pure SVG line-chart mapping
// ---------------------------------------------------------------------------
test('chartGeometry: empty values -> empty', () => {
    const g = chartGeometry([], 100, 50, 8);
    assert.deepEqual(g.points, []);
    assert.equal(g.path, '');
});

test('chartGeometry: single value -> one centered point', () => {
    const g = chartGeometry([5], 100, 50, 8);
    assert.equal(g.points.length, 1);
    assert.equal(g.points[0].x, 50);
    assert.equal(g.points[0].y, 25);
});

test('chartGeometry: flat series -> mid-line (no divide-by-zero)', () => {
    const g = chartGeometry([3, 3, 3], 100, 50, 8);
    g.points.forEach(p => assert.equal(p.y, 25));
    assert.ok(g.points.every(p => Number.isFinite(p.x) && Number.isFinite(p.y)));
});

test('chartGeometry: two values map min to bottom, max to top', () => {
    const g = chartGeometry([0, 10], 100, 100, 10);
    assert.equal(g.points[0].x, 10);   // first at left pad
    assert.equal(g.points[0].y, 90);   // min -> bottom
    assert.equal(g.points[1].x, 90);   // last at right pad
    assert.equal(g.points[1].y, 10);   // max -> top
});

test('chartGeometry: increasing values give strictly decreasing y', () => {
    const g = chartGeometry([1, 2, 3, 4], 120, 80, 8);
    for (let i = 1; i < g.points.length; i++) {
        assert.ok(g.points[i].y < g.points[i - 1].y);
    }
    assert.ok(g.path.startsWith('M '));
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test tests/workout-logic.test.mjs`
Expected: FAIL — `chartGeometry is not a function`.

- [ ] **Step 3: Write minimal implementation**

In `static/workout-logic.js`, add before the export block:

```js
/**
 * Map numeric values to SVG coordinates for a line chart.
 * Higher value -> higher on chart (smaller y). Pure; no DOM.
 * @param {number[]} values
 * @param {number} width
 * @param {number} height
 * @param {number} pad - inner padding in px (default 8)
 * @returns {{points: {x:number,y:number}[], path: string}}
 */
function chartGeometry(values, width, height, pad) {
    pad = (pad === undefined) ? 8 : pad;
    const pts = [];
    if (!values || values.length === 0) return { points: [], path: '' };

    const innerW = width - 2 * pad;
    const innerH = height - 2 * pad;
    const midY = height / 2;

    if (values.length === 1) {
        pts.push({ x: width / 2, y: midY });
    } else {
        const min = Math.min(...values);
        const max = Math.max(...values);
        const range = max - min;
        values.forEach((v, i) => {
            const x = pad + (innerW * i) / (values.length - 1);
            const y = range === 0 ? midY : pad + innerH * (1 - (v - min) / range);
            pts.push({ x, y });
        });
    }
    const path = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');
    return { points: pts, path };
}
```

Add `chartGeometry` to BOTH export lists.

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test tests/workout-logic.test.mjs`
Expected: PASS (all prior + 5 new).

- [ ] **Step 5: Commit**

```bash
git add static/workout-logic.js tests/workout-logic.test.mjs
git commit -m "feat: pure chartGeometry SVG line-chart mapping"
```

---

### Task 4: `/api/cardio/trend` route + disk cache

**Files:**
- Modify: `app.py` (imports from `cardio_stats`; add cache file + helpers; add route near `api_history_detail`, ~line 1614)
- Test: `tests/test_cardio_trend.py`

**Interfaces:**
- Consumes: `cardio_stats.is_cardio_record`, `cardio_stats.derive_cardio_stats`;
  `client.get_training_records(start, end)`, `client.get_training_session_info(id)`;
  `_is_auth_error` (app.py:39).
- Produces: `GET /api/cardio/trend` → `{"sessions": [ {trainingId, startTimestamp, title, ...deriveCardioStats fields} ]}` sorted ascending by `startTimestamp`. 401 when unauthorized. Cache helpers `load_cardio_cache()` / `save_cardio_cache(cache)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cardio_trend.py
"""The cardio trend endpoint returns a time-sorted series of the athlete's cardio
sessions, filtered by courseType, and never 500s when one session's info fails."""
import os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as app_module  # noqa: E402
from api_client import SpeedianceAPIError, SpeedianceAuthError  # noqa: E402

RECORDS = [
    {"trainingId": 1, "courseType": 2, "startTimestamp": 200, "title": "HIIT Rowing"},
    {"trainingId": 2, "courseType": 0, "startTimestamp": 150, "title": "Strength"},
    {"trainingId": 3, "courseType": 2, "startTimestamp": 100, "title": "Row & Flow"},
]
SESS = {
    1: {"trainingTime": 530, "totalDistance": 892.71, "totalEnergy": 29580.29, "calorie": 161, "completionRate": 29.0, "rpe": 6},
    3: {"trainingTime": 120, "totalDistance": 200.0, "totalEnergy": 1412.01, "calorie": 23, "completionRate": 10.0, "rpe": 4},
}


class TestCardioTrend(unittest.TestCase):
    def setUp(self):
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()

    def _run(self, session_side):
        # Isolate the cache so tests don't read/write the real file.
        with mock.patch.object(app_module, 'load_cardio_cache', return_value={}), \
             mock.patch.object(app_module, 'save_cardio_cache'), \
             mock.patch.object(app_module.client, 'credentials', {'token': 't', 'user_id': '1'}), \
             mock.patch.object(app_module.client, 'get_training_records', return_value=RECORDS), \
             mock.patch.object(app_module.client, 'get_training_session_info', side_effect=session_side):
            return self.client.get('/api/cardio/trend')

    def test_filters_to_cardio_and_sorts_by_time(self):
        resp = self._run(lambda tid: SESS[tid])
        self.assertEqual(resp.status_code, 200)
        s = resp.get_json()["sessions"]
        self.assertEqual([x["trainingId"] for x in s], [3, 1])  # sorted by startTimestamp asc
        self.assertAlmostEqual(s[1]["pace500"], 296.9, delta=0.2)

    def test_one_bad_session_is_skipped_not_fatal(self):
        def side(tid):
            if tid == 1:
                raise SpeedianceAPIError("Sorry. You do not have access.")
            return SESS[tid]
        resp = self._run(side)
        self.assertEqual(resp.status_code, 200)
        s = resp.get_json()["sessions"]
        self.assertEqual([x["trainingId"] for x in s], [3])

    def test_auth_error_propagates_as_401(self):
        resp = self._run(mock.Mock(side_effect=SpeedianceAuthError("Login expired.")))
        self.assertEqual(resp.status_code, 401)

    def test_unauthorized_when_no_token(self):
        with mock.patch.object(app_module.client, 'credentials', {}):
            resp = self.client.get('/api/cardio/trend')
        self.assertEqual(resp.status_code, 401)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cardio_trend.py -q`
Expected: FAIL — 404 (route missing) / AttributeError on `load_cardio_cache`.

- [ ] **Step 3: Write minimal implementation**

At the top of `app.py`, alongside other imports, add:

```python
from cardio_stats import is_cardio_record, derive_cardio_stats
```

Near `WORKOUT_GEN_LAST_FILE` (app.py:716), add the cache file + helpers:

```python
CARDIO_TREND_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cardio_trend_cache.json')


def load_cardio_cache():
    """Per-trainingId cardio stats. Completed sessions are immutable, so this never expires."""
    if os.path.exists(CARDIO_TREND_CACHE_FILE):
        try:
            with open(CARDIO_TREND_CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception as e:
            print(f"Could not read cardio cache: {e}")
    return {}


def save_cardio_cache(cache):
    try:
        with open(CARDIO_TREND_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"Could not write cardio cache: {e}")
```

After the `api_history_detail` route (app.py:1614), add:

```python
@app.route('/api/cardio/trend')
def api_cardio_trend():
    """Time-sorted series of the athlete's cardio sessions for the trend chart.
    Filters records by courseType, derives per-session metrics, and caches each
    (past sessions never change). One session's info failing must not 500 the route.
    """
    if not client.credentials.get("token"):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        records = client.get_training_records("2020-01-01", datetime.date.today().isoformat())
        cache = load_cardio_cache()
        dirty = False
        out = []
        for rec in records:
            if not is_cardio_record(rec):
                continue
            tid = rec.get("trainingId")
            key = str(tid)
            stats = cache.get(key)
            if stats is None:
                try:
                    info = client.get_training_session_info(tid)
                except Exception as se:
                    if _is_auth_error(se):
                        raise
                    continue  # skip a session we can't read; don't kill the series
                stats = derive_cardio_stats(info)
                cache[key] = stats
                dirty = True
            out.append({
                "trainingId": tid,
                "startTimestamp": rec.get("startTimestamp"),
                "title": rec.get("title"),
                **stats,
            })
        if dirty:
            save_cardio_cache(cache)
        out.sort(key=lambda x: x.get("startTimestamp") or 0)
        return jsonify({"sessions": out})
    except Exception as e:
        if _is_auth_error(e):
            return jsonify({"error": str(e)}), 401
        return jsonify({"error": str(e)}), 500
```

Note: app.py uses `import datetime` (the module), so use `datetime.date.today().isoformat()` — NOT `from datetime import datetime`. Already imported (app.py:8).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_cardio_trend.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_cardio_trend.py
git commit -m "feat: /api/cardio/trend route with per-session disk cache"
```

---

### Task 5: Frontend cardio stats panel

**Files:**
- Modify: `templates/history.html` (`renderDetail`, ~lines 675-697)

**Interfaces:**
- Consumes: `WorkoutLogic.deriveCardioStats` (Task 2); `data.session`.
- Produces: a `renderCardioPanel(session)` DOM helper and a branch in `renderDetail`
  that shows it when the breakdown is empty and a cardio signal is present.

- [ ] **Step 1: Add the cardio branch in `renderDetail`**

Replace the empty-breakdown block (history.html:690-697) so that, before the
generic message, it checks for cardio signals:

```js
if (exercises.length === 0) {
    const isCardio = session.existBoatingSkiDataGraph === true
        || (session.totalDistance || 0) > 0
        || (session.totalEnergy || 0) > 0;
    if (isCardio) {
        renderCardioPanel(session);   // fills #detailExercises with stats (+ trend in Task 6)
        return;
    }
    container.innerHTML = `
        <div class="text-center py-6 text-gray-500">
            <p>No exercise breakdown available for this session type.</p>
            <p class="text-xs mt-1">Detailed data is available for Program and Custom workouts.</p>
        </div>`;
    return;
}
```

- [ ] **Step 2: Implement `renderCardioPanel`**

Add near `renderDetail` in the `<script>` of history.html:

```js
function fmtPace(secPer500) {
    if (secPer500 == null) return null;
    const m = Math.floor(secPer500 / 60), s = Math.round(secPer500 % 60);
    return `${m}:${String(s).padStart(2, '0')} /500m`;
}

function cardioTile(label, value, hint) {
    const wrap = document.createElement('div');
    wrap.className = 'bg-gray-900 rounded p-3 text-center';
    const l = document.createElement('p'); l.className = 'text-xs text-gray-400'; l.textContent = label;
    const v = document.createElement('p'); v.className = 'text-lg font-bold text-blue-400'; v.textContent = value;
    wrap.appendChild(l); wrap.appendChild(v);
    if (hint) { const h = document.createElement('p'); h.className = 'text-[10px] text-gray-500 mt-0.5'; h.textContent = hint; wrap.appendChild(h); }
    return wrap;
}

function renderCardioPanel(session) {
    const c = WorkoutLogic.deriveCardioStats(session);
    const container = document.getElementById('detailExercises');
    container.innerHTML = '';

    const grid = document.createElement('div');
    grid.className = 'grid grid-cols-2 sm:grid-cols-3 gap-3';

    const tiles = [];
    if (c.distanceM != null)  tiles.push(['Distance', `${Math.round(c.distanceM)} m`]);
    if (c.pace500 != null)    tiles.push(['Avg pace', fmtPace(c.pace500), 'lower = faster']);
    if (c.speedMs != null)    tiles.push(['Avg speed', `${c.speedMs} m/s`, `${(c.speedMs * 3.6).toFixed(1)} km/h`]);
    if (c.avgWatts != null)   tiles.push(['Avg power', `${c.avgWatts} W`, 'derived']);
    if (c.calorie != null)    tiles.push(['Calories', `${Math.round(c.calorie)} kcal`]);
    if (c.calPerMin != null)  tiles.push(['Cal / min', `${c.calPerMin}`]);
    if (c.energyKJ != null)   tiles.push(['Total energy', `${c.energyKJ} kJ`]);
    if (c.completion != null) tiles.push(['Completion', `${Math.round(c.completion)}%`]);
    if (c.rpe != null)        tiles.push(['RPE', `${c.rpe}/10`]);

    tiles.forEach(([label, value, hint]) => grid.appendChild(cardioTile(label, value, hint)));
    container.appendChild(grid);
    // Task 6 appends the trend chart section here.
}
```

- [ ] **Step 3: Verify the page renders**

Run: `pm2 restart speediance && sleep 1 && curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5001/history`
Expected: `200`. Then manually open the "30 Minutes HIIT Rowing Workout" session and confirm the tiles show (Distance 893 m, Avg pace 4:57 /500m, etc.) instead of the dead-end message.

- [ ] **Step 4: Commit**

```bash
git add templates/history.html
git commit -m "feat: cardio stats panel in history detail modal"
```

---

### Task 6: Frontend trend chart + metric switcher

**Files:**
- Modify: `templates/history.html` (`renderCardioPanel`, plus a fetch + render helper)

**Interfaces:**
- Consumes: `GET /api/cardio/trend` (Task 4); `WorkoutLogic.chartGeometry` (Task 3).
- Produces: a trend section appended inside `renderCardioPanel`, with a metric
  switcher and an inline SVG chart highlighting the opened session.

- [ ] **Step 1: Append the trend section container in `renderCardioPanel`**

At the end of `renderCardioPanel(session)` (replacing the Task-5 comment), add:

```js
    const trend = document.createElement('div');
    trend.className = 'mt-4';
    trend.id = 'cardioTrend';
    container.appendChild(trend);
    loadCardioTrend(rec_currentTrainingId(session));
```

Add a tiny helper to resolve the current session's id from the modal payload:

```js
function rec_currentTrainingId(session) {
    return (currentDetailPayload && currentDetailPayload.summary && currentDetailPayload.summary.trainingId)
        || session.id || null;
}
```

- [ ] **Step 2: Implement the metrics list, fetch, and render**

```js
const CARDIO_METRICS = [
    { key: 'pace500',  label: 'Pace /500m', fmt: v => { const m = Math.floor(v/60), s = Math.round(v%60); return `${m}:${String(s).padStart(2,'0')}`; } },
    { key: 'speedMs',  label: 'Speed',      fmt: v => `${v} m/s` },
    { key: 'avgWatts', label: 'Power',      fmt: v => `${v} W` },
    { key: 'distanceM',label: 'Distance',   fmt: v => `${Math.round(v)} m` },
    { key: 'calorie',  label: 'Calories',   fmt: v => `${Math.round(v)} kcal` },
    { key: 'rpe',      label: 'RPE',        fmt: v => `${v}/10` },
];
let cardioTrendState = { sessions: [], currentId: null, metric: 'pace500' };

async function loadCardioTrend(currentId) {
    cardioTrendState.currentId = currentId;
    const box = document.getElementById('cardioTrend');
    box.innerHTML = '<p class="text-xs text-gray-500">Loading trend…</p>';
    try {
        const resp = await fetch('/api/cardio/trend');
        const data = await resp.json();
        cardioTrendState.sessions = Array.isArray(data.sessions) ? data.sessions : [];
        renderCardioTrend();
    } catch (e) {
        box.innerHTML = '';
    }
}

function renderCardioTrend() {
    const box = document.getElementById('cardioTrend');
    box.innerHTML = '';
    const sessions = cardioTrendState.sessions;
    if (!sessions.length) return;

    // Metric switcher
    const bar = document.createElement('div');
    bar.className = 'flex flex-wrap gap-1.5 mb-2';
    CARDIO_METRICS.forEach(m => {
        const b = document.createElement('button');
        const active = m.key === cardioTrendState.metric;
        b.className = `text-xs px-2 py-1 rounded ${active ? 'bg-blue-600 text-white font-bold' : 'bg-gray-800 text-gray-400 border border-gray-700 hover:bg-gray-700'}`;
        b.textContent = m.label;
        b.onclick = () => { cardioTrendState.metric = m.key; renderCardioTrend(); };
        bar.appendChild(b);
    });
    box.appendChild(bar);

    const metric = CARDIO_METRICS.find(m => m.key === cardioTrendState.metric);
    // Only sessions that have this metric; keep index alignment to find "current".
    const usable = sessions.filter(s => s[metric.key] != null);
    if (usable.length < 1) { const p = document.createElement('p'); p.className='text-xs text-gray-500'; p.textContent='No data for this metric yet.'; box.appendChild(p); return; }

    const W = 320, H = 120, PAD = 12;
    const values = usable.map(s => s[metric.key]);
    const g = WorkoutLogic.chartGeometry(values, W, H, PAD);

    const svgNS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('class', 'w-full bg-gray-900 rounded');

    const poly = document.createElementNS(svgNS, 'path');
    poly.setAttribute('d', g.path);
    poly.setAttribute('fill', 'none');
    poly.setAttribute('stroke', '#60a5fa');
    poly.setAttribute('stroke-width', '2');
    svg.appendChild(poly);

    g.points.forEach((p, i) => {
        const dot = document.createElementNS(svgNS, 'circle');
        const isCurrent = usable[i].trainingId === cardioTrendState.currentId;
        dot.setAttribute('cx', p.x); dot.setAttribute('cy', p.y);
        dot.setAttribute('r', isCurrent ? 5 : 3);
        dot.setAttribute('fill', isCurrent ? '#f59e0b' : '#60a5fa');
        const title = document.createElementNS(svgNS, 'title');
        title.textContent = metric.fmt(usable[i][metric.key]);
        dot.appendChild(title);
        svg.appendChild(dot);
    });
    box.appendChild(svg);

    const cap = document.createElement('p');
    cap.className = 'text-[11px] text-gray-500 mt-1';
    cap.textContent = `${metric.label} across ${usable.length} cardio session${usable.length === 1 ? '' : 's'} · orange = this one`
        + (metric.key === 'pace500' ? ' · lower = faster' : '');
    box.appendChild(cap);
}
```

- [ ] **Step 3: Verify the page renders and the chart appears**

Run: `pm2 restart speediance && sleep 1 && curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5001/history`
Expected: `200`. Manually open the rowing session: the trend chart shows with the metric switcher; the opened session's dot is orange; switching metrics re-renders; hovering a dot shows the value.

- [ ] **Step 4: Commit**

```bash
git add templates/history.html
git commit -m "feat: cross-session cardio trend chart with metric switcher"
```

---

### Task 7: Documentation + full-suite verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document the feature**

Add a short subsection under the history/features area of `README.md` describing:
cardio/rowing sessions now show a stats panel (distance, pace /500m, speed,
power, cal/min, energy, completion, RPE) and a cross-session trend chart; note
the within-session per-second graph is unavailable because Speediance exposes no
reachable endpoint for it, and that `CARDIO_COURSE_TYPES` in `cardio_stats.py` is
where new cardio course types (bike/ski) get added.

- [ ] **Step 2: Run the full suites**

Run: `.venv/bin/python -m pytest -q` and `node --test tests/`
Expected: all pass except the two pre-existing live-API failures in
`test_e2e_workouts.py` (`test_create_save_reload_custom_workout_matches`,
`test_create_save_reload_preset_workout_matches`) which fail identically on
clean `main` and are unrelated.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: cardio session stats + trend chart"
```

---

## Self-Review

**Spec coverage:**
- Part A per-session panel → Tasks 2 (derive) + 5 (render). ✓
- Trigger logic (empty breakdown + cardio signal) → Task 5 Step 1. ✓
- Part B backend route + cache + guarded session_info → Task 4. ✓
- `courseType` filter as extensible constant → Task 1 (`CARDIO_COURSE_TYPES`). ✓
- Trend chart + metric switcher + highlight current → Task 6. ✓
- Shared derivation (py + js twins, same oracle) → Tasks 1 + 2. ✓
- Pure geometry helper, edge cases → Task 3. ✓
- Testing (derive normal/zero/missing; geometry 1pt/flat/normal; route 403-skip/auth-401/filter) → Tasks 1-4. ✓
- Within-session graph out of scope → documented (Task 7). ✓

**Placeholder scan:** No TBD/TODO; all code steps carry real code. Task 7 Step 1 is prose-only by nature (README wording) but specifies exact content to include. ✓

**Type consistency:** `deriveCardioStats`/`derive_cardio_stats` field names identical across Tasks 1/2/5/6 (`pace500`, `speedMs`, `avgWatts`, `distanceM`, `calPerMin`, `energyKJ`, `completion`, `rpe`, `calorie`, `durationSec`). `chartGeometry(values,width,height,pad)` signature identical in Tasks 3/6. `/api/cardio/trend` shape (`{sessions:[{trainingId,startTimestamp,title,...stats}]}`) consistent Tasks 4/6. Cache helpers `load_cardio_cache`/`save_cardio_cache` consistent Task 4. ✓
```
