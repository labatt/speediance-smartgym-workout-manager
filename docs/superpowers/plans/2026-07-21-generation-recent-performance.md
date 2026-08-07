# AI Generation — Recent-Performance Context — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Feed the workout generator the athlete's recent lifts (a per-exercise "what you last lifted" table, last 30 days by default) plus progression instructions, so it sets real weights instead of guessing.

**Architecture:** A pure `workout_gen.build_recent_performance()` formats gathered session snapshots into a compact per-exercise table with trend; the generation system prompt gains a PROGRESSION block (when recent data is present) and the user prompt appends the table. `app.py` refactors the assessment session-gather into a shared `_gather_recent_sessions(days)` and wires a `recent_days` param (default 30) into `/api/workout/generate`. The Build Workout page gets a window control.

**Tech Stack:** Python (Flask), Jinja2, vanilla JS, `unittest`.

## Global Constraints

- `workout_gen.py` does NO I/O; every function is pure and unit-tested.
- Facts only in the data (no verdicts); the "how to progress" lives in the system prompt's PROGRESSION block.
- The athlete's FELT rating outranks the raw numbers; never output weight 0.
- Loads are labelled in the account's unit and never converted.
- Reuse the assessment gather logic (don't duplicate it); recent-performance failures must never block generation, but auth errors still map to 401 via `_is_auth_error`.
- Run Python with `.venv/bin/python`.
- Generation recent-perf windows: `{7, 14, 30}`, default 30. The Assessment page keeps its own `{1,3,7,14}`.

---

### Task 1: `workout_gen.py` — recent-performance table + prompt hooks (pure, TDD)

**Files:**
- Modify: `workout_gen.py`
- Test: `tests/test_workout_gen.py`

**Interfaces:**
- Produces: `workout_gen.FEEL: dict`
- Produces: `workout_gen._top_set(ex) -> (load|None, reps:int, seconds:int)`
- Produces: `workout_gen.build_recent_performance(sessions, unit_label, days) -> str`
- Changes: `build_generation_system_prompt(exercises, unit_label, has_recent=False) -> str`
- Changes: `build_generation_user_prompt(user_request, references=None, assessment=None, recent_performance="") -> str`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_workout_gen.py` before `if __name__`:

```python
class TestRecentPerformance(unittest.TestCase):
    def _ex(self, name, kind, sets, all_complete=True):
        return {"name": name, "kind": kind, "all_complete": all_complete, "sets": sets}

    def setUp(self):
        # Seated Row done twice (load rose 33 -> 36.5); Vita once; Leg Curl once.
        self.sessions = [
            {"date": "2026-07-11", "title": "A", "notes": {"exercises": {"Seated Row": "right"}},
             "snapshot": {"exercises": [
                 self._ex("Seated Row", "reps", [{"done": 10, "target": 10, "complete": True, "skipped": False, "load": 33}]),
             ]}},
            {"date": "2026-07-18", "title": "B", "notes": {"exercises": {"Seated Row": "easy"}},
             "snapshot": {"exercises": [
                 self._ex("Seated Row", "reps", [{"done": 10, "target": 10, "complete": True, "skipped": False, "load": 36.5}]),
                 self._ex("Standing Leg Curl", "reps", [{"done": 12, "target": 12, "complete": True, "skipped": False, "load": 15.5}]),
                 self._ex("Vita Twist", "level", [{"done": 4, "target": 4, "complete": True, "skipped": False, "load": None, "seconds": 20}]),
             ]}},
        ]
        self.p = wg.build_recent_performance(self.sessions, "LBS", 30)

    def test_header_names_window_and_unit(self):
        self.assertIn("last 30 days", self.p)
        self.assertIn("LBS", self.p)

    def test_exercise_appears_once_newest(self):
        rows = [l for l in self.p.splitlines() if l.startswith("- Seated Row")]
        self.assertEqual(len(rows), 1)           # deduped to most-recent
        self.assertIn("2026-07-18", rows[0])     # the newer date
        self.assertIn("36.5 LBS", rows[0])       # newest load, labelled

    def test_trend_up_shows_prior(self):
        row = [l for l in self.p.splitlines() if l.startswith("- Seated Row")][0]
        self.assertIn("↑", row)
        self.assertIn("33", row)                 # prior load referenced

    def test_new_exercise_marked_new(self):
        row = [l for l in self.p.splitlines() if l.startswith("- Standing Leg Curl")][0]
        self.assertIn("(new)", row)

    def test_carries_felt(self):
        row = [l for l in self.p.splitlines() if l.startswith("- Seated Row")][0]
        self.assertIn("felt easy", row)

    def test_vita_timed_no_weight_unit(self):
        row = [l for l in self.p.splitlines() if l.startswith("- Vita Twist")][0]
        self.assertIn("timed", row)
        self.assertNotIn("LBS", row)

    def test_empty_sessions_empty_string(self):
        self.assertEqual(wg.build_recent_performance([], "LBS", 30), "")


class TestProgressionBlock(unittest.TestCase):
    def setUp(self):
        self.merged = [wg.merge_exercise(LIB[0])]   # one rep-based exercise

    def test_progression_block_present_when_has_recent(self):
        p = wg.build_generation_system_prompt(self.merged, "LBS", has_recent=True).lower()
        self.assertIn("progression", p)
        self.assertIn("felt rating outranks", p)
        self.assertIn("never output weight 0", p)

    def test_progression_block_absent_by_default(self):
        p = wg.build_generation_system_prompt(self.merged, "LBS").lower()
        self.assertNotIn("progression —", p)

    def test_user_prompt_appends_recent_performance(self):
        u = wg.build_generation_user_prompt("back day", recent_performance="RECENT PERFORMANCE (last 30 days...)\n- Row")
        self.assertIn("RECENT PERFORMANCE", u)
        self.assertIn("- Row", u)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -m pytest tests/test_workout_gen.py::TestRecentPerformance tests/test_workout_gen.py::TestProgressionBlock -q`
Expected: FAIL — `AttributeError: module 'workout_gen' has no attribute 'build_recent_performance'` (and the system/user-prompt signature tests fail on the new kwargs).

- [ ] **Step 3: Implement the table builder + FEEL + _top_set**

In `workout_gen.py`, add near the top (after `MUSCLE_MAP`):

```python
FEEL = {"too_easy": "too easy", "easy": "easy", "right": "just right",
        "hard": "hard", "too_hard": "too hard", None: "not rated"}
```

And add these functions (place `build_recent_performance` next to the other builders):

```python
def _top_set(ex):
    """The notable set of one exercise occurrence, as (load|None, reps, seconds).
    reps-based: the worked set with the highest load. level/timed: the worked set with the
    most reps done (load is None — the read snapshot doesn't expose the Vita level)."""
    worked = [s for s in ex.get("sets", []) if not s.get("skipped")]
    if not worked:
        return None, 0, 0
    if ex.get("kind") == "reps":
        best = max(worked, key=lambda s: (s.get("load") or 0))
        return (best.get("load") or 0), (best.get("done") or 0), 0
    best = max(worked, key=lambda s: (s.get("done") or 0))
    return None, (best.get("done") or 0), (best.get("seconds") or 0)


def build_recent_performance(sessions, unit_label, days):
    """Compact per-exercise table of the athlete's most recent lifts, with trend vs the
    prior occurrence. Pure — facts only; the 'how to progress' rules live in the system
    prompt. sessions: [{date, title, snapshot:{exercises:[...]}, notes:{...}}], any order."""
    occ = {}
    for s in sessions:
        date = s.get("date", "?")
        feels = (s.get("notes") or {}).get("exercises") or {}
        for ex in (s.get("snapshot") or {}).get("exercises", []):
            name = ex.get("name")
            if not name:
                continue
            occ.setdefault(name, []).append((date, ex, feels.get(name)))
    if not occ:
        return ""

    lines = [f"RECENT PERFORMANCE (last {days} days; most recent per exercise, with trend). "
             f"Loads are in {unit_label}."]
    for name in sorted(occ, key=lambda n: max(o[0] for o in occ[n]), reverse=True):
        entries = sorted(occ[name], key=lambda o: o[0], reverse=True)
        date, ex, feel_key = entries[0]
        felt = FEEL.get(feel_key, "not rated")
        prev = entries[1] if len(entries) > 1 else None
        load, reps, secs = _top_set(ex)
        if ex.get("kind") == "reps":
            done_note = "all reps" if ex.get("all_complete") else "missed some"
            line = f"- {name} — {date}: top set {load:g} {unit_label} × {reps}, {done_note}, felt {felt}"
            if prev:
                pl, pr, _ = _top_set(prev[1])
                arrow = "↑" if (load or 0) > (pl or 0) else ("↓" if (load or 0) < (pl or 0) else "→")
                line += f" ({arrow} from {pl:g} {unit_label} × {pr} on {prev[0]})"
            else:
                line += " (new)"
        else:
            line = f"- {name} — {date}: {reps} reps × {secs}s (timed), felt {felt}"
            if prev:
                _, pr, ps = _top_set(prev[1])
                line += f" (prev {pr} × {ps}s on {prev[0]})"
            else:
                line += " (new)"
        lines.append(line)
    return "\n".join(lines)
```

- [ ] **Step 4: Add `has_recent` PROGRESSION block to the system prompt**

In `build_generation_system_prompt`, change the signature to
`def build_generation_system_prompt(exercises, unit_label, has_recent=False):` and, right
BEFORE the `p += [ "", "OUTPUT FORMAT ...` block, insert:

```python
    if has_recent:
        p += [
            "",
            "PROGRESSION — the user prompt includes a RECENT PERFORMANCE table of the athlete's recent lifts:",
            "- Set each weight from that data, not a guess. The athlete's FELT rating outranks the numbers.",
            "- Completed in full AND felt easy/too-easy (trend flat or up) -> progress: add a little load, a rep, or a Vita level.",
            "- Reps missed or it felt hard -> hold or reduce.",
            "- No recent entry for an exercise -> estimate conservatively from similar lifts.",
            "- Still never output weight 0.",
        ]
```

- [ ] **Step 5: Add `recent_performance` to the user prompt**

Change `build_generation_user_prompt`'s signature to
`def build_generation_user_prompt(user_request, references=None, assessment=None, recent_performance=""):`
and, immediately before `return "\n".join(parts)`, insert:

```python
    if recent_performance:
        parts.append("")
        parts.append(recent_performance)
```

- [ ] **Step 6: Run to verify pass**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -m pytest tests/test_workout_gen.py -q`
Expected: PASS (all — old + new).

- [ ] **Step 7: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add workout_gen.py tests/test_workout_gen.py
git commit -m "workout_gen: recent-performance table + progression prompt hooks"
```

---

### Task 2: `app.py` — shared session gather + wire recent_days into generation

**Files:**
- Modify: `app.py` (`api_assessment` gather ~1324-1347; `api_workout_generate` ~1027-1028; add helper + constant near `ASSESSMENT_MAX_SESSIONS` ~695)

**Interfaces:**
- Consumes: `workout_gen.build_recent_performance`, `build_generation_system_prompt(..., has_recent=)`, `build_generation_user_prompt(..., recent_performance=)` (Task 1); existing `_analyze_training`, `_assessment_date`, `load_journal`, `_unit_label`, `_is_auth_error`, `client.get_training_records`.
- Produces: `_gather_recent_sessions(days) -> (list, bool)`; `RECENT_PERF_DAYS = {7, 14, 30}`.

- [ ] **Step 1: Add the shared gather helper + constant**

In `app.py`, just below `ASSESSMENT_MAX_SESSIONS = 40`, add:

```python
RECENT_PERF_DAYS = {7, 14, 30}   # windows offered to the workout generator (default 30)


def _gather_recent_sessions(days):
    """Completed sessions in the last `days`, oldest->newest, each {date,title,snapshot,notes}.
    Shared by the assessment and the workout generator. Returns (sessions, truncated)."""
    end = datetime.date.today()
    start = end - datetime.timedelta(days=days - 1)
    records = [r for r in (client.get_training_records(start.isoformat(), end.isoformat()) or [])
               if r.get('trainingId')]
    truncated = len(records) > ASSESSMENT_MAX_SESSIONS
    records = records[:ASSESSMENT_MAX_SESSIONS]   # API returns newest first
    journal = load_journal()
    sessions = []
    for r in records:
        tid = r.get('trainingId')
        try:
            snap = _analyze_training(tid)
        except Exception:
            continue
        if not snap or not snap.get('exercises'):
            continue
        sessions.append({
            "date": _assessment_date(r.get('startTimestamp')),
            "title": r.get('title') or 'Workout',
            "snapshot": snap,
            "notes": journal.get(str(tid), {}),
        })
    sessions.reverse()   # oldest -> newest
    return sessions, truncated
```

(Confirm `_gather_recent_sessions` is defined AFTER `_analyze_training`/`_assessment_date`/`load_journal` exist — those are near lines 675-756; if placing at ~696 is above them, instead place this helper immediately after `_assessment_date`'s definition. It only needs to exist before the routes that call it.)

- [ ] **Step 2: Make `api_assessment` use the helper**

In `api_assessment`, replace the inline gather (from `end = datetime.date.today()` through
`sessions.reverse()   # oldest -> newest for the read`) with:

```python
        sessions, truncated = _gather_recent_sessions(days)
```

Leave everything after it (the `if not sessions:` empty check, `build_assessment_prompt`,
save, return) unchanged.

- [ ] **Step 3: Wire recent-performance into the generate route**

In `api_workout_generate`, replace these two lines:

```python
        system = workout_gen.build_generation_system_prompt(merged, _unit_label().upper())
        user = workout_gen.build_generation_user_prompt(user_request)
```

with:

```python
        recent_txt = ""
        try:
            rd = int(body.get('recent_days', 30))
        except (TypeError, ValueError):
            rd = 30
        if rd in RECENT_PERF_DAYS:
            try:
                rsessions, _ = _gather_recent_sessions(rd)
                recent_txt = workout_gen.build_recent_performance(rsessions, _unit_label().upper(), rd)
            except Exception as e:
                if _is_auth_error(e):
                    raise                 # a mid-request auth loss must still 401
                recent_txt = ""           # otherwise recent-perf is a nicety; never block
        system = workout_gen.build_generation_system_prompt(
            merged, _unit_label().upper(), has_recent=bool(recent_txt))
        user = workout_gen.build_generation_user_prompt(user_request, recent_performance=recent_txt)
```

- [ ] **Step 4: Smoke-test import + assessment still works + full suite**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -c "import app; c=app.app.test_client(); print('gen', c.post('/api/workout/generate', json={}).status_code); print('assess', c.post('/api/assessment', json={'days':7}).status_code)"`
Expected: `gen 400` (empty request rejected — route imports cleanly) and `assess` is `200` or `401`/`200` depending on token/provider (proves the refactored gather didn't break assessment). A 400 on gen and no import error is the target.
Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add app.py
git commit -m "app: shared _gather_recent_sessions; default 30-day recent-performance in generation"
```

---

### Task 3: `templates/create.html` — recent-performance window control

**Files:**
- Modify: `templates/create.html` (the Generate Workout button block + `generateWorkout()`)

**Interfaces:**
- Consumes: `POST /api/workout/generate` now accepts `recent_days` (Task 2).

- [ ] **Step 1: Add the control next to the Generate button**

Find the Generate Workout button block (contains `id="wg-generate-btn"` and
`id="wg-generate-msg"`). Immediately AFTER the `<button ...>Generate Workout</button>` line
and before the `<span id="wg-generate-msg" ...>` (or right after the button, same container),
add:

```html
                            <label class="text-xs text-gray-400 ml-2">Recent performance:
                                <select id="wg-recent-days" class="ml-1 p-1 bg-gray-700 rounded text-white border border-gray-600 text-xs">
                                    <option value="30" selected>Last 30 days</option>
                                    <option value="14">Last 14 days</option>
                                    <option value="7">Last 7 days</option>
                                    <option value="0">Off</option>
                                </select>
                            </label>
```

- [ ] **Step 2: Send `recent_days` from `generateWorkout()`**

In `window.generateWorkout`, change the fetch body to include the selected window. Replace:

```javascript
            const r = await fetch('/api/workout/generate', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ request })
            });
```

with:

```javascript
            const recentDays = parseInt(document.getElementById('wg-recent-days').value, 10) || 0;
            const r = await fetch('/api/workout/generate', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ request, recent_days: recentDays })
            });
```

- [ ] **Step 3: Verify render**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -c "import app; print(app.app.test_client().get('/create').status_code)"`
Expected: `200`.
Run: `grep -c "wg-recent-days" templates/create.html`
Expected: `2` (the select + the JS read).

- [ ] **Step 4: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add templates/create.html
git commit -m "create: recent-performance window control on Generate Workout"
```

---

### Task 4: Full-suite verification, live smoke, README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Full suite**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -m pytest tests/ -q`
Expected: all pass (prior suite + Task 1's recent-performance/progression tests).

- [ ] **Step 2: Live end-to-end smoke (controller runs this)**

Confirm the table is built from real data and prescribed weights track recent loads. Uses the
configured generator (or falls back to a keyed provider):

```bash
cd /srv/speediance.labattsimon.com && .venv/bin/python -c "
import app, coach, workout_gen
c = app.app.test_client()
rs, _ = app._gather_recent_sessions(30)
print('recent sessions:', len(rs))
print(workout_gen.build_recent_performance(rs, app._unit_label().upper(), 30)[:600])
d = c.post('/api/workout/generate', json={'request':'a short 4-exercise workout using exercises I have done recently','recent_days':30}).get_json()
w = d.get('workout') or {}
print('ok', d.get('ok'), 'exercises', len(w.get('exercises', [])))
for e in w.get('exercises', [])[:6]:
    s0=(e.get('sets') or [{}])[0]; print('  id', e['id'], 'preset', e.get('presetId'), 'w', s0.get('weight'), 'reps', s0.get('reps'))
" 2>&1 | grep -v '^DEBUG:'
```

Expected: a non-empty recent-performance table prints, `ok True`, and prescribed weights are non-zero and plausibly near the recent loads shown in the table (not guesses).

- [ ] **Step 3: README**

Add a short note to the AI workout-generation section: generation now includes your recent
performance (last 30 days by default; a control offers 30/14/7/Off) as a per-exercise
table, and the model is instructed to set/progress weights from it (progress when you
completed everything and it felt easy; hold when it was hard) rather than guessing. Match the
README's voice.

- [ ] **Step 4: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add README.md
git commit -m "docs: document recent-performance context in AI generation"
```

---

## Self-Review

- **Spec coverage:** on-by-default 30-day recent perf (T2 `recent_days` default 30 + T3 control); per-exercise table with trend, Vita-as-timed, felt, unit label, empty→"" (T1 `build_recent_performance`); PROGRESSION instructions with felt-outranks + never-0 (T1 `has_recent`); user prompt appends table (T1); shared `_gather_recent_sessions` reused by assessment (T2); windows {7,14,30}, assessment unchanged (T2); tests (T1); live smoke + README (T4). All spec sections covered.
- **Placeholder scan:** none — full code in every step.
- **Type consistency:** `build_recent_performance(sessions, unit_label, days)`, `_top_set(ex) -> (load,reps,secs)`, `build_generation_system_prompt(exercises, unit_label, has_recent=False)`, `build_generation_user_prompt(..., recent_performance="")`, `_gather_recent_sessions(days) -> (sessions, truncated)` — defined in T1/T2 and consumed consistently in T2/T3/T4. Session dict shape `{date,title,snapshot,notes}` matches what `build_recent_performance` reads.
