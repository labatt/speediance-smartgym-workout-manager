# AI Refinement Loop (stateless) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refine a workout in the builder by comment ("make leg day harder", "swap the squat for a hinge") — the model returns the adjusted workout, never undoing earlier comments or manual edits.

**Architecture:** Stateless, all five providers. A pure `workout_gen.build_refinement_user_prompt()` frames an edit of the current workout + the cumulative comment log; `app.py` adds `POST /api/workout/refine` mirroring generation's machinery (select on the comment, pool = current exercises + candidates, same system prompt + recent-performance, validate). The Build Workout page gets a refinement panel that serializes the current builder state each round.

**Tech Stack:** Python (Flask), Jinja2, vanilla JS, `unittest`.

## Global Constraints

- `workout_gen.py` does NO I/O; pure + unit-tested.
- No-reversion is structural: every round sends the current builder state + full comment log; nothing relies on hidden server state.
- Reuse generation's pool/validation/weight discipline and recent-performance; no new provider code, no Gemini Interactions API.
- Current workout's exercise IDs are prepended into the pool (kept available), capped at 60.
- Auth errors → 401 via `_is_auth_error`; recent-perf/detail failures degrade but never block (auth still propagates).
- Run Python with `.venv/bin/python`.

---

### Task 1: `workout_gen.py` — `build_refinement_user_prompt` (pure, TDD)

**Files:**
- Modify: `workout_gen.py`
- Test: `tests/test_workout_gen.py`

**Interfaces:**
- Produces: `workout_gen.build_refinement_user_prompt(current_workout, comment, comment_log=None) -> str`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_workout_gen.py` before `if __name__`:

```python
class TestRefinementPrompt(unittest.TestCase):
    def setUp(self):
        self.cur = {"name": "Back Day", "exercises": [
            {"id": 1001, "presetId": -1, "sets": [{"reps": 10, "weight": 40, "mode": 1, "rest": 60}]},
        ]}

    def test_frames_as_edit_and_returns_full(self):
        p = wg.build_refinement_user_prompt(self.cur, "add a set to the row", [])
        low = p.lower()
        self.assertIn("edit of an existing workout", low)
        self.assertIn("add a set to the row", p)
        self.assertIn("full updated workout", low)

    def test_includes_current_workout_json(self):
        p = wg.build_refinement_user_prompt(self.cur, "heavier", [])
        self.assertIn("1001", p)          # the current workout's exercise id appears
        self.assertIn("Back Day", p)

    def test_includes_full_comment_log(self):
        p = wg.build_refinement_user_prompt(self.cur, "now add abs", ["make it harder", "swap squat for hinge"])
        self.assertIn("make it harder", p)
        self.assertIn("swap squat for hinge", p)
        self.assertIn("keep honoring", p.lower())

    def test_empty_log_no_section_no_crash(self):
        p = wg.build_refinement_user_prompt(self.cur, "lighter", None)
        self.assertNotIn("KEEP honoring", p)
        self.assertIn("lighter", p)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -m pytest tests/test_workout_gen.py::TestRefinementPrompt -q`
Expected: FAIL — `AttributeError: module 'workout_gen' has no attribute 'build_refinement_user_prompt'`.

- [ ] **Step 3: Implement**

In `workout_gen.py` (which already `import json` at the top), add near the other builders:

```python
def build_refinement_user_prompt(current_workout, comment, comment_log=None):
    """Frame an EDIT of an existing workout. Pure. current_workout is the generation-schema
    dict {name, exercises:[...]}; comment_log holds prior applied comments to keep honoring."""
    parts = [
        "This is an EDIT of an existing workout, not a new one.",
        "",
        "CURRENT WORKOUT (JSON, in the output format):",
        json.dumps(current_workout, ensure_ascii=False),
        "",
        f'Apply this change: "{comment}"',
    ]
    log = [c for c in (comment_log or []) if c]
    if log:
        parts.append("")
        parts.append("Earlier instructions you must KEEP honoring (do not undo them):")
        parts.extend(f"- {c}" for c in log)
    parts.append("")
    parts.append("Return the FULL updated workout in the same JSON format. Preserve every exercise, "
                 "set, and value not affected by the change (including any I edited by hand); change "
                 "only what the instruction requires.")
    return "\n".join(parts)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -m pytest tests/test_workout_gen.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add workout_gen.py tests/test_workout_gen.py
git commit -m "workout_gen: refinement user prompt (edit current workout + comment log)"
```

---

### Task 2: `app.py` — `POST /api/workout/refine`

**Files:**
- Modify: `app.py` (add route after `api_workout_generate`)
- Test: `tests/test_workout_refine.py`

**Interfaces:**
- Consumes: `workout_gen.build_refinement_user_prompt`, `build_generation_system_prompt`, `build_selection_prompt`, `parse_selected_ids`, `compact_catalog`, `merge_exercise`, `validate_workout`, `build_recent_performance`; `coach.chat_with`/`workout_provider`/`workout_model`/`provider_cfg`; `client.get_library`/`get_batch_details`; `_extract_json`, `_gather_recent_sessions`, `save_workout_gen_last`, `_unit_label`, `_is_auth_error`, `RECENT_PERF_DAYS`.
- Produces: `POST /api/workout/refine`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_workout_refine.py`:

```python
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402


class WorkoutRefineRoute(unittest.TestCase):
    def setUp(self):
        self._tok = app.client.credentials.get("token")
        app.client.credentials["token"] = "test-token"
        self.c = app.app.test_client()

    def tearDown(self):
        if self._tok is None:
            app.client.credentials.pop("token", None)
        else:
            app.client.credentials["token"] = self._tok

    def test_empty_comment_rejected(self):
        r = self.c.post("/api/workout/refine",
                        json={"current_workout": {"exercises": [{"id": 1}]}, "comment": "  "})
        self.assertEqual(r.status_code, 400)

    def test_empty_current_workout_rejected(self):
        r = self.c.post("/api/workout/refine",
                        json={"current_workout": {"exercises": []}, "comment": "harder"})
        self.assertEqual(r.status_code, 400)

    def test_requires_auth(self):
        app.client.credentials.pop("token", None)
        r = self.c.post("/api/workout/refine", json={"comment": "x"})
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -m pytest tests/test_workout_refine.py -q`
Expected: FAIL — 404/405 because `/api/workout/refine` doesn't exist yet.

- [ ] **Step 3: Add the route**

In `app.py`, immediately AFTER the `api_workout_generate` function (before the next `@app.route`), add:

```python
@app.route('/api/workout/refine', methods=['POST'])
def api_workout_refine():
    """Adjust the current workout by a natural-language comment, statelessly: the current
    builder state + the full comment log are the source of truth every round, so nothing the
    athlete changed (by AI or by hand) is silently reverted."""
    if not client.credentials.get("token"):
        return jsonify({"error": "Unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    current = body.get('current_workout') or {}
    comment = (body.get('comment') or "").strip()
    if not comment:
        return jsonify({"error": "Describe the change you want."}), 400
    cur_exs = current.get('exercises') if isinstance(current, dict) else None
    if not cur_exs:
        return jsonify({"error": "No current workout to refine."}), 400

    cfg = coach.load_config()
    provider, model = coach.workout_provider(cfg), coach.workout_model(cfg)
    if not model or not coach.provider_cfg(cfg, provider).get("api_key"):
        return jsonify({"ok": False,
                        "text": "The AI Workout Generator isn't set up yet — pick a provider, add its key, "
                                "and choose a model in Settings."}), 200
    try:
        library = client.get_library()
        catalog = workout_gen.compact_catalog(library)

        ok, sel = coach.chat_with(provider, model, workout_gen.build_selection_prompt(comment, catalog), cfg)
        selected = workout_gen.parse_selected_ids(sel if ok else "", library, request=comment)
        cur_ids = []
        for e in cur_exs:
            try:
                cur_ids.append(int(e.get('id')))
            except (TypeError, ValueError):
                pass
        pool_ids = list(dict.fromkeys(cur_ids + selected))[:60]   # keep current exercises, then candidates

        details = {}
        try:
            for d in (client.get_batch_details(pool_ids) or []):
                if d.get("id") is not None:
                    details[int(d["id"])] = d
        except Exception as e:
            if _is_auth_error(e):
                raise
            details = {}
        libmap = {int(e["id"]): e for e in library}
        merged = [workout_gen.merge_exercise(libmap[i], details.get(i)) for i in pool_ids if i in libmap]

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
                    raise
                recent_txt = ""
        system = workout_gen.build_generation_system_prompt(
            merged, _unit_label().upper(), has_recent=bool(recent_txt))
        user = workout_gen.build_refinement_user_prompt(current, comment, body.get('comment_log') or [])
        ok, text = coach.chat_with(provider, model, user, cfg, system=system)
        if not ok:
            return jsonify({"ok": False, "text": text}), 200

        parsed = _extract_json(text)
        if parsed is None:
            ok, text = coach.chat_with(provider, model,
                                       "Return ONLY the workout as valid JSON, nothing else:\n" + text, cfg,
                                       system=system)
            parsed = _extract_json(text) if ok else None
        if parsed is None:
            return jsonify({"ok": False, "text": "The model did not return valid JSON. Try again or rephrase."}), 200

        ok, cleaned, warnings = workout_gen.validate_workout(parsed, library)
        if not ok:
            return jsonify({"ok": False, "text": "The adjusted workout had no usable exercises. Try again.",
                            "warnings": warnings}), 200
        save_workout_gen_last({
            "request": comment, "kind": "refine",
            "provider": provider, "model": model,
            "at": datetime.datetime.now().isoformat(timespec='seconds'),
            "system_prompt": system, "user_prompt": user,
        })
        return jsonify({"ok": True, "workout": cleaned, "warnings": warnings})
    except Exception as e:
        if _is_auth_error(e):
            return jsonify({"error": str(e)}), 401
        return jsonify({"error": str(e)}), 500
```

- [ ] **Step 4: Run tests + smoke**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -m pytest tests/test_workout_refine.py -q`
Expected: PASS (3).
Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -c "import app; c=app.app.test_client(); print(c.post('/api/workout/refine', json={'current_workout':{'exercises':[]},'comment':'x'}).status_code)"`
Expected: `400`.
Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add app.py tests/test_workout_refine.py
git commit -m "app: POST /api/workout/refine (stateless comment-driven adjustment)"
```

---

### Task 3: `templates/create.html` — refinement panel

**Files:**
- Modify: `templates/create.html` (add panel markup in the builder column; JS: `serializeBuilderForAI`, `applyRefinement`, `commentLog`, `renderCommentLog`; toggle panel in `renderBuilder`; reset log on new generation/import)

**Interfaces:**
- Consumes: `POST /api/workout/refine`; existing `loadWorkoutIntoBuilder`, `workoutData`, `renderBuilder`.

- [ ] **Step 1: Add the panel markup**

Find the builder column's Save area (the block containing `id="plan-name"` and the Save button `onclick="saveWorkout()"`, ~lines 133-146). Immediately AFTER that header block's closing tag (before the exercise list container), add:

```html
    <div id="refine-panel" class="hidden mb-4 p-3 rounded-lg border border-gray-700 bg-gray-900/40">
        <label class="block text-sm text-gray-300 mb-1">Refine with AI</label>
        <div class="flex gap-2">
            <input id="refine-comment" type="text"
                   class="flex-grow bg-gray-900 text-white p-2 rounded border border-gray-600 focus:border-purple-500 outline-none text-sm"
                   placeholder="e.g. make leg day harder · swap the squat for a hinge · add a set to the rows">
            <button onclick="applyRefinement()" id="refine-btn"
                    class="bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded font-bold text-sm whitespace-nowrap">Apply AI adjustment</button>
        </div>
        <div id="refine-log" class="flex flex-wrap gap-1 mt-2"></div>
        <span id="refine-msg" class="text-xs text-gray-400"></span>
    </div>
```

(If the builder markup makes "immediately after the header block" ambiguous, place the panel as the first child of the same container that holds the exercise list / `renderBuilder` output, so it sits above the exercises. Report the exact placement in your report.)

- [ ] **Step 2: Add the JS (serializer, apply, log)**

Near `window.generateWorkout` (or `loadWorkoutIntoBuilder`), add:

```javascript
    let commentLog = [];
    function renderCommentLog() {
        const box = document.getElementById('refine-log');
        if (!box) return;
        box.innerHTML = '';
        commentLog.forEach(cmt => {
            const chip = document.createElement('span');
            chip.className = 'inline-block px-2 py-1 text-xs rounded bg-gray-700 border border-gray-600 text-gray-300';
            chip.textContent = cmt;                     // textContent — never HTML
            box.appendChild(chip);
        });
    }
    function serializeBuilderForAI() {
        return {
            name: document.getElementById('plan-name').value || 'Custom Workout',
            exercises: workoutData.map(ex => ({
                id: ex.groupId,
                presetId: ex.selectedPresetId,
                isUnilateralExpanded: ex.isUnilateral || undefined,   // sets already hold L/R
                sets: ex.sets.map(s => ({ reps: s.reps, weight: s.weight, mode: s.mode, rest: s.rest, unit: s.unit })),
            })),
        };
    }
    window.applyRefinement = async () => {
        const comment = document.getElementById('refine-comment').value.trim();
        const msg = document.getElementById('refine-msg');
        const btn = document.getElementById('refine-btn');
        if (!comment) { msg.textContent = 'Describe the change first.'; return; }
        if (!workoutData.length) { msg.textContent = 'Nothing to refine yet.'; return; }
        btn.disabled = true; msg.textContent = 'Adjusting… this can take a moment.';
        try {
            const recentDays = parseInt((document.getElementById('wg-recent-days') || {}).value, 10) || 0;
            const r = await fetch('/api/workout/refine', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ current_workout: serializeBuilderForAI(), comment,
                                       comment_log: commentLog, recent_days: recentDays })
            });
            const d = await r.json();
            if (d.error) { msg.textContent = d.error; return; }
            if (!d.ok) { msg.textContent = d.text || 'Adjustment failed.'; return; }
            const loaded = await loadWorkoutIntoBuilder(d.workout);
            if (loaded) {
                commentLog.push(comment);
                renderCommentLog();
                document.getElementById('refine-comment').value = '';
                msg.textContent = (d.warnings && d.warnings.length)
                    ? `Applied with notes: ${d.warnings.join(' ')}` : 'Applied — review below.';
                if (typeof loadLastGeneration === 'function') loadLastGeneration();
            }
        } catch (e) {
            msg.textContent = 'Request failed: ' + e;
        } finally {
            btn.disabled = false;
        }
    };
```

- [ ] **Step 3: Toggle the panel + reset the log**

In `renderBuilder` (find `function renderBuilder`), at the END of the function add:

```javascript
        const rp = document.getElementById('refine-panel');
        if (rp) rp.classList.toggle('hidden', workoutData.length === 0);
```

A refinement thread belongs to one workout, so start a fresh log when a NEW workout is
generated or imported (NOT on refine, which calls `loadWorkoutIntoBuilder` too). In
`window.generateWorkout`, inside the `if (loaded) {` success branch, add before it focuses
the name field:

```javascript
                commentLog = []; renderCommentLog();
```

And in `window.processImport`, right after a successful `loadWorkoutIntoBuilder(data)` (in the
`if (await loadWorkoutIntoBuilder(data)) { ... }` block), add:

```javascript
                commentLog = []; renderCommentLog();
```

- [ ] **Step 4: Verify render + wiring**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -c "import app; print(app.app.test_client().get('/create').status_code)"`
Expected: `200`.
Run: `grep -c "refine-panel\|applyRefinement\|serializeBuilderForAI\|commentLog" templates/create.html`
Expected: non-zero for each (`applyRefinement` ≥ 2).

- [ ] **Step 5: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add templates/create.html
git commit -m "create: AI refinement panel (comment-driven adjustment with no-reversion log)"
```

---

### Task 4: Full-suite verification, live smoke, README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Full suite**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 2: Live smoke (controller runs this)**

Verify a refinement applies a change and a second refinement doesn't revert the first:

```bash
cd /srv/speediance.labattsimon.com && .venv/bin/python -c "
import app
c = app.app.test_client()
# start from a real generated workout
g = c.post('/api/workout/generate', json={'request':'a short 4-exercise upper body workout','recent_days':30}).get_json()
w = g['workout']
n0 = [len(e['sets']) for e in w['exercises']]
print('base sets per exercise:', n0)
# refine 1: add a set to every exercise
r1 = c.post('/api/workout/refine', json={'current_workout':w,'comment':'add one set to every exercise','comment_log':[]}).get_json()
w1 = r1['workout']; n1 = [len(e['sets']) for e in w1['exercises']]
print('after +1 set:', n1, '| ok', r1.get('ok'))
# refine 2: heavier first exercise, with log — must not drop the added sets
r2 = c.post('/api/workout/refine', json={'current_workout':w1,'comment':'make the first exercise heavier','comment_log':['add one set to every exercise']}).get_json()
w2 = r2['workout']; n2 = [len(e['sets']) for e in w2['exercises']]
print('after heavier-first:', n2, '| ok', r2.get('ok'))
print('no-reversion (sets kept):', all(b >= a for a,b in zip(n1,n2)))
" 2>&1 | grep -v '^DEBUG:'
```

Expected: `ok True` for both refinements; set counts increase after refine 1 and are retained
(not reverted) after refine 2.

- [ ] **Step 3: README**

Add a short note to the AI workout-generation section: after generating (or importing) a
workout you can refine it by comment — "Refine with AI" on the Build Workout page — and the
model adjusts it, keeping your earlier comments and manual edits (no reversion). Match the
README's voice.

- [ ] **Step 4: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add README.md
git commit -m "docs: document the AI refinement loop"
```

---

## Self-Review

- **Spec coverage:** refinement user prompt with current workout + comment + log + "return full updated workout" (T1); `/api/workout/refine` reusing generation machinery, current-ids-prepended pool, recent-performance, validation, history save with kind (T2); refinement panel + `serializeBuilderForAI` (generation schema, unilateral flag) + comment-log + no-reversion resend + panel toggle + log reset on new/imported workout (T3); tests (T1/T2); live no-reversion smoke + README (T4). All spec sections covered.
- **Placeholder scan:** none — full code in every step.
- **Type consistency:** `build_refinement_user_prompt(current_workout, comment, comment_log=None)` defined T1, called T2; `/api/workout/refine` body `{current_workout:{name,exercises:[{id,presetId,sets}]}, comment, comment_log, recent_days}` produced by `serializeBuilderForAI` (T3) and consumed by the route (T2); response `{ok, workout, warnings}` consumed by `applyRefinement` (T3); pool built from `int(e['id'])` matches the serializer's `id: ex.groupId`.
