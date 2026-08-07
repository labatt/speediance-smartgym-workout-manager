# Add Workout Reference — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the athlete reference existing workouts when generating — the model gets a readable summary of each and can reuse their exact exercises.

**Architecture:** A pure `workout_gen.build_reference_workouts()` formats referenced-workout digests; the generation prompts gain `has_refs`/`references`. `app.py` adds `GET /api/workout/list` and, in generate, fetches referenced workout details, merges their exercise IDs into the candidate pool (so they survive validation), and injects the summary. The Build Workout page gets an Add-reference modal + chips.

**Tech Stack:** Python (Flask), Jinja2, vanilla JS, `unittest`.

## Global Constraints

- `workout_gen.py` does NO I/O; pure + unit-tested. Reference digest is facts only.
- Referenced exercise IDs must reach the candidate pool (prioritised) so `validate_workout` doesn't drop them; keep the pool cap at 60.
- Vita/level exercises show levels×seconds with NO weight/unit; loads labelled in the account unit, never converted.
- Reference-fetch failures never block generation, but Speediance auth errors still map to 401 via `_is_auth_error`.
- Run Python with `.venv/bin/python`.
- Max 5 referenced workouts per request.

---

### Task 1: `workout_gen.py` — reference digest + prompt hooks (pure, TDD)

**Files:**
- Modify: `workout_gen.py`
- Test: `tests/test_workout_gen.py`

**Interfaces:**
- Produces: `workout_gen._csv_nums(s) -> list`, `workout_gen._summarize(nums) -> str`
- Produces: `workout_gen.build_reference_workouts(references, unit_label) -> str`
- Changes: `build_generation_system_prompt(exercises, unit_label, has_recent=False, has_refs=False)`
- Changes: `build_generation_user_prompt(user_request, references="", recent_performance="")` (drops the old list-based `references` and the unused `assessment` param)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_workout_gen.py` before `if __name__`:

```python
class TestReferenceWorkouts(unittest.TestCase):
    def setUp(self):
        self.refs = [{
            "name": "Back Day A",
            "exercises": [
                {"title": "Seated Row", "setsAndReps": "10,10,10", "weights": "40,40,40",
                 "level": "", "is_level": False, "is_timed": False},
                {"title": "Lat Pulldown", "setsAndReps": "12,10,8", "weights": "45,50,55",
                 "level": "", "is_level": False, "is_timed": False},
                {"title": "Vita Pull", "setsAndReps": "30,30,30", "weights": "0,0,0",
                 "level": "10,12,14", "is_level": True, "is_timed": True},
            ],
        }]
        self.p = wg.build_reference_workouts(self.refs, "LBS")

    def test_names_the_workout(self):
        self.assertIn("Back Day A", self.p)

    def test_uniform_sets_summarised(self):
        self.assertIn("Seated Row: 3×10 @ 40 LBS", self.p)

    def test_varying_sets_listed(self):
        self.assertIn("Lat Pulldown: 3×12/10/8 @ 45/50/55 LBS", self.p)

    def test_vita_shows_levels_seconds_no_unit(self):
        row = [l for l in self.p.splitlines() if l.startswith("- Vita Pull")][0]
        self.assertIn("30s", row)
        self.assertIn("levels 10/12/14", row)
        self.assertNotIn("LBS", row)

    def test_empty_returns_empty(self):
        self.assertEqual(wg.build_reference_workouts([], "LBS"), "")


class TestReferencePromptHooks(unittest.TestCase):
    def setUp(self):
        self.merged = [wg.merge_exercise(LIB[0])]

    def test_system_prompt_refs_note_when_has_refs(self):
        p = wg.build_generation_system_prompt(self.merged, "LBS", has_refs=True).lower()
        self.assertIn("reference workout", p)

    def test_system_prompt_no_refs_note_by_default(self):
        p = wg.build_generation_system_prompt(self.merged, "LBS").lower()
        self.assertNotIn("reference workouts are provided", p)

    def test_user_prompt_includes_references_and_recent(self):
        u = wg.build_generation_user_prompt("back day", references="REFERENCE WORKOUTS...\n- Row",
                                            recent_performance="RECENT PERFORMANCE...\n- Curl")
        self.assertIn("REFERENCE WORKOUTS", u)
        self.assertIn("RECENT PERFORMANCE", u)
        self.assertIn("back day", u)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -m pytest tests/test_workout_gen.py::TestReferenceWorkouts tests/test_workout_gen.py::TestReferencePromptHooks -q`
Expected: FAIL — `AttributeError: module 'workout_gen' has no attribute 'build_reference_workouts'` and the user-prompt kwarg test fails.

- [ ] **Step 3: Implement the digest helpers**

In `workout_gen.py`, add near the other builders:

```python
def _csv_nums(s):
    """Parse a comma string like '10,10,8' into [10, 10, 8] (ints where whole)."""
    out = []
    for part in str(s or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            v = float(part)
            out.append(int(v) if v == int(v) else v)
        except ValueError:
            pass
    return out


def _summarize(nums):
    """'10' when every value is equal, else '12/10/8'."""
    if not nums:
        return "?"
    if all(n == nums[0] for n in nums):
        return f"{nums[0]:g}"
    return "/".join(f"{n:g}" for n in nums)


def build_reference_workouts(references, unit_label):
    """Readable digest of referenced workouts for the prompt. Pure — facts only.
    references: [{"name", "exercises":[{"title","setsAndReps","weights","level","is_level","is_timed"}]}]."""
    blocks = []
    for w in references:
        exs = w.get("exercises") or []
        if not exs:
            continue
        lines = [f"{w.get('name', 'Workout')}:"]
        for e in exs:
            title = e.get("title", "Exercise")
            reps = _csv_nums(e.get("setsAndReps"))
            n = len(reps)
            if e.get("is_level"):
                lines.append(f"- {title}: {n} sets × {_summarize(reps)}s, levels {_summarize(_csv_nums(e.get('level')))} (timed)")
            elif e.get("is_timed"):
                lines.append(f"- {title}: {n} sets × {_summarize(reps)}s (timed)")
            else:
                lines.append(f"- {title}: {n}×{_summarize(reps)} @ {_summarize(_csv_nums(e.get('weights')))} {unit_label}")
        blocks.append("\n".join(lines))
    if not blocks:
        return ""
    return ("REFERENCE WORKOUTS (structure/inspiration — adapt to the request, don't copy verbatim):\n"
            + "\n\n".join(blocks))
```

- [ ] **Step 4: Add `has_refs` to the system prompt**

In `build_generation_system_prompt`, change the signature to
`def build_generation_system_prompt(exercises, unit_label, has_recent=False, has_refs=False):`
and, right after the `if has_recent:` block (before the `OUTPUT FORMAT` block), add:

```python
    if has_refs:
        p += [
            "",
            "REFERENCE WORKOUTS are provided in the user prompt as structure to adapt: reuse their "
            "exercises where they fit the request, but tailor sets and loads to the request and the "
            "athlete's recent performance rather than copying them verbatim.",
        ]
```

- [ ] **Step 5: Simplify the user prompt**

Replace the whole `build_generation_user_prompt` with:

```python
def build_generation_user_prompt(user_request, references="", recent_performance=""):
    """The user's request, plus optional referenced-workout digest and recent-performance
    table (both preformatted strings; appended when non-empty)."""
    parts = [f'Build this workout: "{user_request}"']
    if references:
        parts.append("")
        parts.append(references)
    if recent_performance:
        parts.append("")
        parts.append(recent_performance)
    return "\n".join(parts)
```

- [ ] **Step 6: Run to verify pass**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -m pytest tests/test_workout_gen.py -q`
Expected: PASS (all — old + new). (The existing `test_user_prompt_has_request` still passes; it only asserts the request text.)

- [ ] **Step 7: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add workout_gen.py tests/test_workout_gen.py
git commit -m "workout_gen: reference-workout digest + prompt hooks"
```

---

### Task 2: `app.py` — `/api/workout/list` + reference handling in generation

**Files:**
- Modify: `app.py` (add `/api/workout/list` near `/api/workout/last`; reference block in `api_workout_generate` between `pool_ids = ...` and `details = {}`; the two prompt-builder calls)
- Test: `tests/test_workout_reference.py`

**Interfaces:**
- Consumes: `workout_gen.build_reference_workouts`, updated prompt signatures (Task 1); `client.get_user_workouts`, `client.get_workout_detail`, `_unit_label`, `_is_auth_error`.
- Produces: `GET /api/workout/list`; `references` handling in `POST /api/workout/generate`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_workout_reference.py`:

```python
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402


class WorkoutListRoute(unittest.TestCase):
    def setUp(self):
        self._tok = app.client.credentials.get("token")
        app.client.credentials["token"] = "test-token"
        self._orig = app.client.get_user_workouts
        self.c = app.app.test_client()

    def tearDown(self):
        app.client.get_user_workouts = self._orig
        if self._tok is None:
            app.client.credentials.pop("token", None)
        else:
            app.client.credentials["token"] = self._tok

    def test_list_returns_name_code_entries(self):
        app.client.get_user_workouts = lambda: [
            {"name": "Back Day A", "code": "abc", "actionNum": 8, "durationMinute": 42},
            {"name": "No Code", "actionNum": 3},   # dropped — no code
        ]
        d = self.c.get("/api/workout/list").get_json()
        self.assertEqual(len(d["workouts"]), 1)
        self.assertEqual(d["workouts"][0]["code"], "abc")
        self.assertEqual(d["workouts"][0]["name"], "Back Day A")

    def test_list_requires_auth(self):
        app.client.credentials.pop("token", None)
        self.assertEqual(self.c.get("/api/workout/list").status_code, 401)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -m pytest tests/test_workout_reference.py -q`
Expected: FAIL — 404/`KeyError` because `/api/workout/list` doesn't exist yet.

- [ ] **Step 3: Add `/api/workout/list`**

In `app.py`, right after the `api_workout_last` route, add:

```python
@app.route('/api/workout/list')
def api_workout_list():
    """The athlete's workouts, for the 'Add reference' picker."""
    if not client.credentials.get("token"):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        ws = client.get_user_workouts() or []
    except Exception as e:
        if _is_auth_error(e):
            return jsonify({"error": str(e)}), 401
        return jsonify({"error": str(e)}), 500
    return jsonify({"workouts": [
        {"name": w.get("name") or "Workout", "code": w.get("code"),
         "exercises": w.get("actionNum"), "duration": w.get("durationMinute")}
        for w in ws if w.get("code")]})
```

- [ ] **Step 4: Add reference handling in the generate route**

In `api_workout_generate`, immediately AFTER the line
`pool_ids = workout_gen.parse_selected_ids(sel if ok else "", library, request=user_request)`
and BEFORE `details = {}`, insert:

```python
        # Referenced workouts: build a readable summary AND make their exercises available to
        # the model (prepend their ids so they survive the pool cap and validation).
        ref_norm, ref_ids = [], []
        for code in (body.get('references') or [])[:5]:
            try:
                det = client.get_workout_detail(code)
            except Exception as e:
                if _is_auth_error(e):
                    raise
                continue
            if not det:
                continue
            exs = []
            for a in (det.get('actionLibraryList') or []):
                gid = a.get('groupId') or a.get('actionLibraryId')
                if gid:
                    ref_ids.append(int(gid))
                cm = a.get('completionMethod')
                exs.append({
                    "title": a.get('title', 'Exercise'),
                    "setsAndReps": a.get('setsAndReps'), "weights": a.get('weights'),
                    "level": a.get('level'), "is_level": cm == 5, "is_timed": cm in (0, 2, 5),
                })
            ref_norm.append({"name": det.get('name', 'Workout'), "exercises": exs})
        pool_ids = list(dict.fromkeys(ref_ids + pool_ids))[:60]   # referenced first, then selected
        ref_txt = workout_gen.build_reference_workouts(ref_norm, _unit_label().upper())
```

- [ ] **Step 5: Pass reference context to the prompts**

In the same route, replace the two prompt-builder lines:

```python
        system = workout_gen.build_generation_system_prompt(
            merged, _unit_label().upper(), has_recent=bool(recent_txt))
        user = workout_gen.build_generation_user_prompt(user_request, recent_performance=recent_txt)
```

with:

```python
        system = workout_gen.build_generation_system_prompt(
            merged, _unit_label().upper(), has_recent=bool(recent_txt), has_refs=bool(ref_txt))
        user = workout_gen.build_generation_user_prompt(
            user_request, references=ref_txt, recent_performance=recent_txt)
```

- [ ] **Step 6: Run tests + smoke**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -m pytest tests/test_workout_reference.py tests/test_workout_gen.py -q`
Expected: PASS.
Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -c "import app; c=app.app.test_client(); print('list', c.get('/api/workout/list').status_code); print('gen', c.post('/api/workout/generate', json={}).status_code)"`
Expected: `list` is `200` (or `401` without token) and `gen` is `400` (empty request) — proves imports/wiring are clean. Then the full suite: `.venv/bin/python -m pytest tests/ -q` → all pass.

- [ ] **Step 7: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add app.py tests/test_workout_reference.py
git commit -m "app: /api/workout/list + reference workouts in generation (summary + pool merge)"
```

---

### Task 3: `templates/create.html` — Add-reference button, modal, chips

**Files:**
- Modify: `templates/create.html` (button near Generate; a modal; chips container; `generateWorkout` body; JS)

**Interfaces:**
- Consumes: `/api/workout/list`, and `POST /api/workout/generate` now accepting `references: [codes]`.

- [ ] **Step 1: Add the button + chips container**

In the Generate box (after the `<select id="wg-recent-days">…</select></label>` and before `<span id="wg-generate-msg">`), add:

```html
                        <button type="button" onclick="openRefModal()" class="ml-2 px-3 py-2 text-xs rounded bg-gray-700 hover:bg-gray-600 border border-gray-600">+ Add reference</button>
                        <div id="ref-chips" class="flex flex-wrap gap-2 mt-2"></div>
```

- [ ] **Step 2: Add the reference modal**

Near the existing `#import-modal` block, add a sibling modal:

```html
<div id="ref-modal" class="fixed inset-0 bg-black/80 hidden items-center justify-center z-50">
    <div class="bg-gray-800 rounded-lg p-6 w-full max-w-lg max-h-[80vh] flex flex-col border border-gray-600">
        <div class="flex justify-between items-center mb-3">
            <h3 class="text-lg font-bold text-white">Reference a workout</h3>
            <button onclick="closeRefModal()" class="text-gray-400 hover:text-white">✕</button>
        </div>
        <p class="text-xs text-gray-500 mb-3">Pick one or more of your workouts. The AI will use them as structure and may reuse their exercises.</p>
        <div id="ref-list" class="flex-grow overflow-auto space-y-1 text-sm text-gray-300">Loading…</div>
    </div>
</div>
```

- [ ] **Step 3: Add the JS**

Near `window.generateWorkout`, add:

```javascript
    let references = [];   // [{code, name}]
    function renderRefChips() {
        const box = document.getElementById('ref-chips');
        box.innerHTML = '';
        references.forEach(r => {
            const chip = document.createElement('span');
            chip.className = 'inline-flex items-center gap-1 px-2 py-1 text-xs rounded bg-purple-900/40 border border-purple-700 text-purple-200';
            chip.textContent = r.name;                        // textContent — never HTML
            const x = document.createElement('button');
            x.type = 'button'; x.textContent = '✕'; x.className = 'text-purple-300 hover:text-white';
            x.onclick = () => { references = references.filter(z => z.code !== r.code); renderRefChips(); };
            chip.appendChild(x);
            box.appendChild(chip);
        });
    }
    window.openRefModal = async () => {
        document.getElementById('ref-modal').classList.remove('hidden');
        document.getElementById('ref-modal').classList.add('flex');
        const list = document.getElementById('ref-list');
        list.textContent = 'Loading…';
        try {
            const d = await (await fetch('/api/workout/list')).json();
            if (d.error) { list.textContent = d.error; return; }
            const ws = d.workouts || [];
            if (!ws.length) { list.textContent = 'No workouts found.'; return; }
            list.innerHTML = '';
            ws.forEach(w => {
                const row = document.createElement('button');
                row.type = 'button';
                row.className = 'block w-full text-left p-2 rounded hover:bg-gray-700 border border-gray-700';
                const meta = [w.exercises ? w.exercises + ' exercises' : null, w.duration ? '~' + w.duration + ' min' : null].filter(Boolean).join(' · ');
                row.textContent = w.name + (meta ? '  (' + meta + ')' : '');   // textContent — safe
                row.onclick = () => {
                    if (!references.some(z => z.code === w.code)) references.push({ code: w.code, name: w.name });
                    renderRefChips();
                    closeRefModal();
                };
                list.appendChild(row);
            });
        } catch (e) { list.textContent = 'Could not load workouts.'; }
    };
    window.closeRefModal = () => {
        document.getElementById('ref-modal').classList.add('hidden');
        document.getElementById('ref-modal').classList.remove('flex');
    };
```

- [ ] **Step 4: Send `references` from `generateWorkout`**

In `window.generateWorkout`, change the fetch body from
`body: JSON.stringify({ request, recent_days: recentDays })`
to:

```javascript
                body: JSON.stringify({ request, recent_days: recentDays, references: references.map(r => r.code) })
```

- [ ] **Step 5: Verify render**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -c "import app; print(app.app.test_client().get('/create').status_code)"`
Expected: `200`.
Run: `grep -c "ref-modal\|openRefModal\|ref-chips\|references.map" templates/create.html`
Expected: non-zero for each (`grep -c "openRefModal"` ≥ 2, `references.map` = 1).

- [ ] **Step 6: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add templates/create.html
git commit -m "create: Add-reference modal + chips; send references to generation"
```

---

### Task 4: Full-suite verification, live smoke, README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Full suite**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -m pytest tests/ -q`
Expected: all pass (prior + the new reference tests).

- [ ] **Step 2: Live smoke (controller runs this)**

Reference a real workout and confirm the summary is in the prompt and its exercises are available:

```bash
cd /srv/speediance.labattsimon.com && .venv/bin/python -c "
import app, coach, workout_gen
c = app.app.test_client()
ws = app.client.get_user_workouts()
code = ws[0]['code']; print('referencing:', ws[0]['name'], code)
d = c.post('/api/workout/generate', json={'request':'build something like this but 30 minutes','references':[code],'recent_days':30}).get_json()
w = d.get('workout') or {}
print('ok', d.get('ok'), 'exercises', len(w.get('exercises', [])))
# confirm the saved prompt carries the reference summary
last = app.load_workout_gen_history()[0]
print('reference summary in prompt:', 'REFERENCE WORKOUTS' in last.get('user_prompt',''))
" 2>&1 | grep -v '^DEBUG:'
```

Expected: `ok True`, a non-empty exercise list, and `reference summary in prompt: True`.

- [ ] **Step 3: README**

Add a short note to the AI workout-generation section: you can now reference one or more of
your own workouts when generating (Add reference → pick from your workouts → chips); the model
gets a readable summary of each and may reuse their exercises, adapting sets/loads to your
request and recent performance. Match the README's voice.

- [ ] **Step 4: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add README.md
git commit -m "docs: document Add Workout Reference in AI generation"
```

---

## Self-Review

- **Spec coverage:** reference digest (T1 `build_reference_workouts`), prompt hooks `has_refs`/`references` (T1), `/api/workout/list` (T2), reference fetch + normalize + pool merge (prioritised, capped) + prompt wiring (T2), chips UI + modal + send references (T3), tests (T1/T2), live smoke + README (T4). All spec sections covered.
- **Placeholder scan:** none — full code in every step.
- **Type consistency:** `build_reference_workouts(references, unit_label)` where references = `[{name, exercises:[{title,setsAndReps,weights,level,is_level,is_timed}]}]` — produced by the route in T2, consumed in T1; `build_generation_system_prompt(exercises, unit_label, has_recent=False, has_refs=False)` and `build_generation_user_prompt(user_request, references="", recent_performance="")` defined T1, called T2; `/api/workout/list` shape `{workouts:[{name,code,exercises,duration}]}` produced T2, consumed T3.
