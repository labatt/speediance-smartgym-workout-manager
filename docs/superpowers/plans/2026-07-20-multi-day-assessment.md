# Multi-day Assessment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An Assessment page where the athlete picks a 1/3/7/14-day window and gets one LLM read over every completed workout in that window — strengths, weaknesses, trends, and where to add load.

**Architecture:** Extends the existing single-session coach. A new pure prompt builder (`build_assessment_prompt`) over a *list* of session snapshots reuses the same per-exercise fact formatting and the same provider dispatch (`coach.chat`, given an assessment-specific system prompt). A dedicated `/assessment` page gathers the sessions server-side and caches the latest result.

**Tech Stack:** Python (Flask), stdlib `urllib` LLM client, Jinja2 templates, Tailwind (CDN), vanilla JS, `unittest`.

## Global Constraints

- Pure core stays pure: nothing below `coach.SYSTEM_PROMPT` may do I/O; everything in the "PURE PROMPT" region is unit-tested.
- Never leak API keys: `assessment.json` holds no keys; the coach config remains chmod 600.
- Felt rating outranks every sensor metric; the model may cite only facts it is given (encoded in the system prompt).
- Auth-gate every new route exactly like siblings (`if not client.credentials.get("token"): 401`), and map auth errors via `_is_auth_error` to 401.
- `startTimestamp` on a record is **Unix seconds**.
- Existing tests must stay green — the `build_prompt` refactor is behaviour-preserving.

---

### Task 1: `coach.py` — extract `_exercise_line`, add `system` override to `chat`

**Files:**
- Modify: `coach.py` (`build_prompt` ~351-394; `chat` ~271-275; `_chat_provider` ~224-268)
- Test: `tests/test_coach.py`

**Interfaces:**
- Produces: `coach._exercise_line(e, notes, cmp_by=None) -> str` — one `"- ..."` fact line.
- Produces: `coach.chat(prompt, config=None, timeout=120, system=None) -> (bool, str)` — `system` defaults to `SYSTEM_PROMPT`.

- [ ] **Step 1: Assert current single-session output is the baseline (guards the refactor)**

Existing `tests/test_coach.py::TestBuildPrompt` already asserts the content of `build_prompt(SNAPSHOT, NOTES)`. Run it first to capture the current pass:

Run: `cd /srv/speediance.labattsimon.com && python -m pytest tests/test_coach.py -q`
Expected: PASS (baseline).

- [ ] **Step 2: Extract `_exercise_line`**

In `coach.py`, add this helper directly above `build_prompt` (after `_feel`):

```python
def _exercise_line(e, notes, cmp_by=None):
    """One '- ...' fact line for an exercise. Pure. Shared by the single-session
    read and the multi-day assessment so both speak the facts identically."""
    cmp_by = cmp_by or {}
    felt = _feel(notes, e["name"])
    if e["kind"] == "level":
        sets = ", ".join(f"{s['done']}/{s['target']} in {s.get('seconds','?')}s"
                         for s in e["sets"] if not s["skipped"])
        return f"- {e['name']} (Vita, level-based): sets {sets}. Felt: {felt}."
    sets = ", ".join(
        f"{s['done']}/{s['target']} @ {s['load']:g}"
        + (f" (power {s['power_trend_pct']:+.0f}% peak->last)" if s.get("power_trend_pct") is not None else "")
        for s in e["sets"] if not s["skipped"]
    )
    sc = e["scores"]
    score_str = f"force {sc.get('force_control')}/5, amplitude-stability {sc.get('amplitude_stable')}/5"
    complete = "all reps completed" if e["all_complete"] else "MISSED some reps"
    rom = ""
    if e.get("rom_change_pct") is not None and abs(e["rom_change_pct"]) >= 8:
        rom = f", range {e['rom_change_pct']:+.0f}% across sets"
    cmp = cmp_by.get(e["name"])
    vs = ""
    if cmp and cmp.get("load_delta") not in (None, 0):
        vs = f", top load {cmp['load_delta']:+g} vs last session"
    return f"- {e['name']}: {complete}. Sets {sets}. {score_str}{rom}{vs}. Felt: {felt}."
```

- [ ] **Step 3: Rewrite `build_prompt`'s inner loop to call the helper**

Replace the per-exercise body of the region loop in `build_prompt` so the loop reads:

```python
    for region in sorted({e["region"] for e in snapshot["exercises"]}):
        lines.append(f"== {region} ==")
        for e in [x for x in snapshot["exercises"] if x["region"] == region]:
            lines.append(_exercise_line(e, notes, cmp_by))
        lines.append("")
```

Leave the header lines, the `cmp_by = {c["name"]: c ...}` line, and the trailing "power peak->last" note exactly as they are.

- [ ] **Step 4: Add `system` override to the dispatch**

Change `_chat_provider`'s signature to `def _chat_provider(provider, pc, prompt, timeout, system=None):` and, at the top of its body (after the `model`/key guards), add:

```python
    sys_prompt = system or SYSTEM_PROMPT
```

Then in each provider branch replace the literal `SYSTEM_PROMPT` with `sys_prompt` (openai/grok `messages[0].content`, anthropic `"system"`, gemini `system_instruction.parts[0].text`, ollama `messages[0].content`).

Change `chat` to:

```python
def chat(prompt, config=None, timeout=120, system=None):
    """Run a prompt through the ACTIVE provider. (ok, text_or_reason).
    `system` overrides the default single-session SYSTEM_PROMPT (used by assessments)."""
    config = config or load_config()
    provider = active_provider(config)
    return _chat_provider(provider, provider_cfg(config, provider), prompt, timeout, system)
```

- [ ] **Step 5: Run tests — output unchanged, dispatch unchanged**

Run: `cd /srv/speediance.labattsimon.com && python -m pytest tests/test_coach.py -q`
Expected: PASS (all existing tests, including `TestBuildPrompt` and `TestProviderDispatchOffline`, still green — proves the refactor is byte-for-byte).

- [ ] **Step 6: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add coach.py tests/test_coach.py
git commit -m "coach: extract _exercise_line, add system override to chat"
```

---

### Task 2: `coach.py` — `ASSESSMENT_SYSTEM_PROMPT` + `build_assessment_prompt` (pure, TDD)

**Files:**
- Modify: `coach.py` (pure region, below `build_prompt`)
- Test: `tests/test_coach.py`

**Interfaces:**
- Consumes: `coach._exercise_line`, `coach._feel`, `coach.FEEL_WORDS` (Task 1).
- Produces: `coach.ASSESSMENT_SYSTEM_PROMPT: str`
- Produces: `coach.build_assessment_prompt(sessions, days) -> str` where `sessions` is a list of `{"date": str, "title": str, "snapshot": {"exercises": [...]}, "notes": {...}}`, oldest first.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_coach.py`:

```python
class TestAssessmentPrompt(unittest.TestCase):
    def setUp(self):
        self.sessions = [
            {"date": "2026-07-18", "title": "Workout A", "snapshot": SNAPSHOT, "notes": NOTES},
            {"date": "2026-07-20", "title": "Workout B", "snapshot": SNAPSHOT, "notes": {}},
        ]
        self.p = coach.build_assessment_prompt(self.sessions, 7)

    def test_lists_each_session_date_and_title(self):
        self.assertIn("2026-07-18", self.p)
        self.assertIn("Workout A", self.p)
        self.assertIn("2026-07-20", self.p)
        self.assertIn("Workout B", self.p)

    def test_window_size_stated(self):
        self.assertIn("7 day", self.p)

    def test_vita_spoken_in_levels_not_weight(self):
        vita_lines = [l for l in self.p.splitlines() if l.startswith("- Vita Pull")]
        self.assertTrue(vita_lines)
        for l in vita_lines:
            self.assertIn("level-based", l)
            self.assertNotIn("@", l)

    def test_carries_felt_ratings(self):
        self.assertIn("Felt: easy", self.p)

    def test_asks_the_assessment_questions(self):
        low = self.p.lower()
        for kw in ("strong", "weak", "improving", "regress", "increase weight or resistance"):
            self.assertIn(kw, low)

    def test_empty_sessions_does_not_raise(self):
        out = coach.build_assessment_prompt([], 1)
        self.assertIn("1 day", out)


class TestAssessmentSystemPrompt(unittest.TestCase):
    def test_encodes_guardrails(self):
        s = coach.ASSESSMENT_SYSTEM_PROMPT.lower()
        self.assertIn("felt rating outranks", s)
        self.assertIn("never invent", s)
        self.assertIn("muscle region", s)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /srv/speediance.labattsimon.com && python -m pytest tests/test_coach.py::TestAssessmentPrompt tests/test_coach.py::TestAssessmentSystemPrompt -q`
Expected: FAIL — `AttributeError: module 'coach' has no attribute 'build_assessment_prompt'`.

- [ ] **Step 3: Implement the system prompt and builder**

In `coach.py`, below `build_prompt`, add:

```python
ASSESSMENT_SYSTEM_PROMPT = """You are a strength coach reviewing several training sessions on a Speediance cable machine across a period of days.

Rules you must follow:
- Use ONLY the facts given below. Never invent a number, a weight, or a rep count. If you cite a figure, it must appear in the facts.
- The athlete's own FELT rating outranks every sensor metric. A power/velocity sensor cannot measure effort. When a felt rating and a metric disagree, trust the felt rating and say so.
- Recommend adding weight or resistance ONLY where the evidence agrees across the period: reps consistently completed AND the athlete felt it easy/too-easy AND the device's form scores are solid (roughly 4-5 of 5). If form is low or range is shrinking, say hold and fix form first.
- For "level" exercises (Vita), talk in LEVELS and seconds, never weight.
- Judge trends only from the dated facts: an exercise's load or reps rising across sessions is improvement; falling or stalling with hard or failed sets is regression or a plateau.
- Prefer 'hold' over churn — most exercises should stay put.

Structure your assessment, grouped by muscle region, to cover:
- Where the athlete is STRONG.
- Where the athlete is WEAK or lagging.
- Where they are IMPROVING (cite the dated trend).
- Where they are REGRESSING or PLATEAUING.
- Where to INCREASE weight or resistance next — name the exercise and the felt/factual basis.
- Any other observations (imbalances, missed reps, form or range notes).

Be concise and specific. Cite exercises by name and cite the facts you rely on."""


def build_assessment_prompt(sessions, days):
    """Compact factual brief spanning several sessions. Pure — no I/O.

    sessions: list of {"date", "title", "snapshot": {"exercises": [...]}, "notes": {...}},
    oldest first. Reuses _exercise_line so the facts read identically to a single-session read.
    """
    lines = [f"Assessment window: the last {days} day(s). "
             f"{len(sessions)} completed session(s) with data, oldest first.", ""]
    for s in sessions:
        notes = s.get("notes") or {}
        snap = s.get("snapshot") or {}
        exercises = snap.get("exercises", [])
        overall = FEEL_WORDS.get(notes.get("overall"))
        lines.append(f"### {s.get('date', '?')} — {s.get('title', 'Workout')}")
        lines.append(f"Overall felt: {overall}.")
        if notes.get("note"):
            lines.append(f"Session note: {notes['note']}")
        for region in sorted({e["region"] for e in exercises}):
            lines.append(f"== {region} ==")
            for e in [x for x in exercises if x["region"] == region]:
                lines.append(_exercise_line(e, notes))
        lines.append("")
    lines.append("Note: 'power peak->last' is a raw sensor trend, NOT a measure of effort. "
                 "Weight it far below the athlete's felt rating and rep completion.")
    lines.append("")
    lines.append("Now assess performance across this whole window: where the athlete is strong, "
                 "where weak, where improving, where regressing or plateauing, where to increase "
                 "weight or resistance, plus other observations — grouped by muscle region.")
    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd /srv/speediance.labattsimon.com && python -m pytest tests/test_coach.py -q`
Expected: PASS (all, old and new).

- [ ] **Step 5: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add coach.py tests/test_coach.py
git commit -m "coach: assessment system prompt + build_assessment_prompt"
```

---

### Task 3: `app.py` — assessment routes + cache, and `.gitignore`

**Files:**
- Modify: `app.py` (near the journal helpers ~672-702 and routes)
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `coach.build_assessment_prompt`, `coach.ASSESSMENT_SYSTEM_PROMPT`, `coach.chat(..., system=...)`, `coach.status`, `_analyze_training`, `load_journal`, `_is_auth_error`, `client.get_training_records`.
- Produces: routes `GET /assessment`, `GET /api/assessment/last`, `POST /api/assessment`; helpers `load_assessment()`, `save_assessment(data)`, `_assessment_date(ts)`.

- [ ] **Step 1: Add cache helpers + constants**

In `app.py`, next to `JOURNAL_FILE`/`load_journal`/`save_journal`, add:

```python
ASSESSMENT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assessment.json')
ASSESSMENT_DAYS = {1, 3, 7, 14}
ASSESSMENT_MAX_SESSIONS = 40


def load_assessment():
    if os.path.exists(ASSESSMENT_FILE):
        try:
            with open(ASSESSMENT_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Could not read assessment: {e}")
    return None


def save_assessment(data):
    with open(ASSESSMENT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


def _assessment_date(ts):
    """A record's startTimestamp is Unix seconds; render it as YYYY-MM-DD."""
    try:
        return datetime.datetime.fromtimestamp(float(ts)).strftime('%Y-%m-%d')
    except Exception:
        return '?'
```

- [ ] **Step 2: Add the page + last-assessment routes**

Add near the `/history` route:

```python
@app.route('/assessment')
def assessment_page():
    if not client.credentials.get("token"):
        return redirect(url_for('settings'))
    unit = client.credentials.get('unit', 0)
    return render_template('assessment.html', unit=unit)


@app.route('/api/assessment/last')
def api_assessment_last():
    if not client.credentials.get("token"):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"last": load_assessment()})
```

- [ ] **Step 3: Add the assessment-run route**

```python
@app.route('/api/assessment', methods=['POST'])
def api_assessment():
    """Assess performance over the last N days: gather every completed session in the
    window, build one factual multi-session prompt, and read it through the active provider."""
    if not client.credentials.get("token"):
        return jsonify({"error": "Unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    try:
        days = int(body.get('days'))
    except (TypeError, ValueError):
        days = None
    if days not in ASSESSMENT_DAYS:
        return jsonify({"error": "days must be one of 1, 3, 7, 14"}), 400

    try:
        cfg = coach.load_config()
        if not coach.status(cfg).get("ready"):
            return jsonify({"ok": False,
                            "text": "No AI provider is ready. Add a key and pick a model in Settings."}), 200

        end = datetime.date.today()
        start = end - datetime.timedelta(days=days - 1)
        records = [r for r in (client.get_training_records(start.isoformat(), end.isoformat()) or [])
                   if r.get('trainingId')]

        truncated = len(records) > ASSESSMENT_MAX_SESSIONS
        records = records[:ASSESSMENT_MAX_SESSIONS]      # API returns newest first

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
        sessions.reverse()   # oldest -> newest for the read

        if not sessions:
            return jsonify({"ok": True, "empty": True, "session_count": 0,
                            "text": f"No completed workouts with data in the last {days} day(s)."}), 200

        prompt = coach.build_assessment_prompt(sessions, days)
        ok, text = coach.chat(prompt, cfg, system=coach.ASSESSMENT_SYSTEM_PROMPT)
        if not ok:
            return jsonify({"ok": False, "text": text}), 200

        model = coach.provider_cfg(cfg, coach.active_provider(cfg)).get("model")
        result = {"text": text, "model": model,
                  "at": datetime.datetime.now().isoformat(timespec='seconds'),
                  "days": days, "session_count": len(sessions), "truncated": truncated}
        save_assessment(result)
        return jsonify({"ok": True, **result})
    except Exception as e:
        if _is_auth_error(e):
            return jsonify({"error": str(e)}), 401
        return jsonify({"error": str(e)}), 500
```

- [ ] **Step 4: Gitignore the cache**

Add a line to `.gitignore`:

```
assessment.json
```

- [ ] **Step 5: Smoke-test import and routing**

Run: `cd /srv/speediance.labattsimon.com && python -c "import app; c=app.app.test_client(); r=c.post('/api/assessment', json={'days':2}); print(r.status_code, r.get_json())"`
Expected: `400 {'error': 'days must be one of 1, 3, 7, 14'}` (validation fires before any auth/data path — confirms the route is wired and imports are clean). If token is set it may instead reach auth; a `400` on the invalid `days` is the target. Auth-gated 401 is also acceptable here.

- [ ] **Step 6: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add app.py .gitignore
git commit -m "app: assessment routes (page, run, last) + cached result"
```

---

### Task 4: Shared markdown renderer + `assessment.html` + nav link

**Files:**
- Create: `static/js/coach_markdown.js`
- Create: `templates/assessment.html`
- Modify: `templates/history.html` (remove inline `escHtml`+`coachMarkdown` ~576-605; add script include)
- Modify: `templates/layout.html` (nav link ~28)

**Interfaces:**
- Consumes: `POST /api/assessment`, `GET /api/assessment/last` (Task 3).
- Produces: global `window.escHtml`, `window.coachMarkdown` from the shared JS.

- [ ] **Step 1: Extract the shared renderer**

Create `static/js/coach_markdown.js` with exactly the two functions currently inline in `history.html` (escape-first — do not alter the logic):

```javascript
// Escape-first markdown renderer shared by the History and Assessment pages.
// Escapes HTML first, THEN applies a tiny markdown subset, so model output can never
// inject markup. Keep this the single source of truth for both pages.
function escHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function coachMarkdown(md) {
    const inline = s => escHtml(s)
        .replace(/\*\*([^*]+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*([^*]+?)\*/g, '<em>$1</em>')
        .replace(/`([^`]+?)`/g, '<code class="bg-gray-800 px-1 rounded">$1</code>');
    let html = '', listType = '';
    const close = () => { if (listType) { html += `</${listType}>`; listType = ''; } };
    for (const raw of (md || '').split('\n')) {
        const line = raw.replace(/\s+$/, '');
        if (!line.trim()) { close(); continue; }
        if (/^---+$/.test(line.trim())) { close(); html += '<hr class="border-gray-700 my-2">'; continue; }
        let m;
        if ((m = line.match(/^(#{1,4})\s+(.*)$/))) { close(); html += `<div class="font-bold text-indigo-100 mt-2 mb-1">${inline(m[2])}</div>`; continue; }
        if ((m = line.match(/^\s*[-*+]\s+(.*)$/))) {
            if (listType !== 'ul') { close(); html += '<ul class="list-disc ml-5 space-y-0.5 mb-1">'; listType = 'ul'; }
            html += `<li>${inline(m[1])}</li>`; continue;
        }
        if ((m = line.match(/^\s*\d+\.\s+(.*)$/))) {
            if (listType !== 'ol') { close(); html += '<ol class="list-decimal ml-5 space-y-0.5 mb-1">'; listType = 'ol'; }
            html += `<li>${inline(m[1])}</li>`; continue;
        }
        close();
        html += `<p class="mb-1.5">${inline(line)}</p>`;
    }
    close();
    return html;
}
```

- [ ] **Step 2: Point History at the shared file**

In `templates/history.html`, delete the inline `function escHtml(...) {...}` and `function coachMarkdown(md) {...}` (lines ~576-605). In its `{% block head %}` (or before the page's main `<script>`), add:

```html
<script src="{{ url_for('static', filename='js/coach_markdown.js') }}"></script>
```

- [ ] **Step 3: Verify History still renders (no regression)**

Run: `cd /srv/speediance.labattsimon.com && python -c "import app; print(app.app.test_client().get('/static/js/coach_markdown.js').status_code)"`
Expected: `200` (Flask serves the new static file).
Then load the History page in the browser and open a session with a saved coach read — it must still render formatted (bold, bullets). Manual check.

- [ ] **Step 4: Add the nav link**

In `templates/layout.html`, add after the History link (line ~28):

```html
                <a href="/assessment" class="hover:text-white">Assessment</a>
```

- [ ] **Step 5: Create the Assessment page**

Create `templates/assessment.html`:

```html
{% extends "layout.html" %}
{% block head %}
<script src="{{ url_for('static', filename='js/coach_markdown.js') }}"></script>
{% endblock %}
{% block content %}
<div class="max-w-3xl mx-auto">
    <h1 class="text-2xl font-bold text-white mb-1">Performance Assessment</h1>
    <p class="text-gray-400 text-sm mb-4">A coach's read over your recent workouts: where you're strong, weak,
        improving, plateauing, and where to add weight or resistance.</p>

    <div id="lastBanner" class="hidden mb-4 p-3 rounded bg-gray-800 border border-gray-700 text-sm text-gray-300"></div>

    <div class="flex flex-wrap items-center gap-2 mb-4">
        <span class="text-gray-400 text-sm mr-1" id="runLabel">Assess the last:</span>
        <button data-days="1"  class="dayBtn px-3 py-1.5 rounded bg-gray-800 border border-gray-700 hover:bg-gray-700 text-sm">1 day</button>
        <button data-days="3"  class="dayBtn px-3 py-1.5 rounded bg-gray-800 border border-gray-700 hover:bg-gray-700 text-sm">3 days</button>
        <button data-days="7"  class="dayBtn px-3 py-1.5 rounded bg-gray-800 border border-gray-700 hover:bg-gray-700 text-sm">7 days</button>
        <button data-days="14" class="dayBtn px-3 py-1.5 rounded bg-gray-800 border border-gray-700 hover:bg-gray-700 text-sm">14 days</button>
    </div>

    <div id="status" class="text-sm text-gray-400 mb-3"></div>
    <div id="assessmentOut" class="text-sm text-gray-200 leading-relaxed"></div>
</div>

<script>
    function relTime(iso) {
        try {
            const then = new Date(iso), now = new Date();
            const days = Math.floor((now - then) / 86400000);
            const d = then.toLocaleString(undefined, { month: 'short', day: 'numeric' });
            if (days <= 0) return `today (${d})`;
            if (days === 1) return `yesterday (${d})`;
            return `${days} days ago (${d})`;
        } catch (e) { return iso; }
    }

    function showLast(last) {
        const banner = document.getElementById('lastBanner');
        const out = document.getElementById('assessmentOut');
        if (!last) { banner.classList.add('hidden'); return; }
        banner.classList.remove('hidden');
        banner.textContent = `Last assessment: last ${last.days} day(s), run ${relTime(last.at)}`
            + (last.model ? ` · ${last.model}` : '')
            + `. Run a new one below.`;
        out.innerHTML = coachMarkdown(last.text || '');
    }

    async function loadLast() {
        try {
            const r = await fetch('/api/assessment/last');
            const d = await r.json();
            showLast(d.last);
        } catch (e) { /* first visit, nothing cached */ }
    }

    async function runAssessment(days) {
        const status = document.getElementById('status');
        const out = document.getElementById('assessmentOut');
        document.querySelectorAll('.dayBtn').forEach(b => b.disabled = true);
        status.className = 'text-sm text-indigo-300 mb-3';
        status.textContent = `Assessing your last ${days} day(s)… this can take a moment.`;
        out.textContent = '';
        try {
            const r = await fetch('/api/assessment', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ days })
            });
            const d = await r.json();
            // Errors carry raw values — render as TEXT, never innerHTML.
            if (d.error) { status.className = 'text-sm text-red-400 mb-3'; status.textContent = d.error; }
            else if (d.empty) { status.className = 'text-sm text-yellow-400 mb-3'; status.textContent = d.text; }
            else if (!d.ok) { status.className = 'text-sm text-yellow-400 mb-3'; status.textContent = d.text; }
            else {
                status.className = 'text-sm text-gray-500 mb-3';
                status.textContent = `Last ${d.days} day(s) · ${d.session_count} session(s)`
                    + (d.truncated ? ' (capped at 40 most recent)' : '')
                    + (d.model ? ` · ${d.model}` : '');
                out.innerHTML = coachMarkdown(d.text);
                document.getElementById('lastBanner').classList.add('hidden');
            }
        } catch (e) {
            status.className = 'text-sm text-red-400 mb-3';
            status.textContent = 'Request failed: ' + e;
        } finally {
            document.querySelectorAll('.dayBtn').forEach(b => b.disabled = false);
        }
    }

    document.querySelectorAll('.dayBtn').forEach(b =>
        b.addEventListener('click', () => runAssessment(parseInt(b.dataset.days, 10))));
    loadLast();
</script>
{% endblock %}
```

- [ ] **Step 6: Verify the page renders and the API is reachable**

Run: `cd /srv/speediance.labattsimon.com && python -c "import app; c=app.app.test_client(); print('page', c.get('/assessment').status_code); print('last', c.get('/api/assessment/last').status_code)"`
Expected: page is `200` (or `302` to settings if no token in this process); `/api/assessment/last` is `200` with `{"last": ...}` or `401` if unauthenticated. Both prove wiring.

- [ ] **Step 7: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add static/js/coach_markdown.js templates/assessment.html templates/history.html templates/layout.html
git commit -m "Assessment page + shared coach_markdown renderer + nav link"
```

---

### Task 5: Full-suite verification + live smoke + README

**Files:**
- Modify: `README.md` (feature list / coach section)

- [ ] **Step 1: Run the whole suite**

Run: `cd /srv/speediance.labattsimon.com && python -m pytest -q`
Expected: all tests pass (86 prior + the new assessment tests).

- [ ] **Step 2: Live smoke via pm2 (real login present)**

Reload the app and hit the page + a 7-day run:

```bash
cd /srv/speediance.labattsimon.com && pm2 restart speediance && sleep 2 \
  && curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/assessment
```

Expected: `200` (server up). Then in the browser: open **Assessment**, click **7 days**, confirm a rendered read appears, reload the page and confirm the "Last assessment…" banner shows with the prior read. Manual check.

- [ ] **Step 3: Update README**

Add an "Assessment" bullet to the feature list and a short paragraph under the AI-coach section describing the 1/3/7/14-day window, that it reuses the active provider, that the felt-rating-outranks-metrics guardrail applies, and that the latest result is cached and shown with its date.

- [ ] **Step 4: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add README.md
git commit -m "docs: document the multi-day Assessment feature"
```

---

## Self-Review

- **Spec coverage:** nav link (T4), dedicated page (T4), 1/3/7/14 dialog→buttons (T4), gather window + snapshots + notes (T3), multi-session prompt (T2), assessment system prompt (T2), provider dispatch with system override (T1), cache + "show last, ask to re-run" (T3 `/api/assessment/last` + T4 banner), empty/not-ready/auth handling (T3), shared escape-first renderer (T4), tests (T1/T2), `.gitignore` (T3), README (T5). All covered.
- **Placeholder scan:** none — every code step is complete.
- **Type consistency:** `build_assessment_prompt(sessions, days)`, `chat(..., system=...)`, `_exercise_line(e, notes, cmp_by=None)`, `_analyze_training`, `coach.status(...).get("ready")`, record fields `trainingId`/`title`/`startTimestamp` used consistently across tasks.
