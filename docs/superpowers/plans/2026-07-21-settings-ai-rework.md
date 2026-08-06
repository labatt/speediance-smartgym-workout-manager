# Settings AI Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework Settings so keys are entered + tested + model-listed per provider, and the Coach and Workout Generator each independently pick a provider+model (all five providers), with model dropdowns populated from the cached list (fixing the "only gpt-oss" display).

**Architecture:** Small `app.py` changes (cache model lists into `known_models`, expose `known_models` in the coach config, accept all five providers for the generator) plus a rewrite of the `settings.html` AI section into Part A (provider key rows) and Part B (Coach + Generator role selectors). No `coach.py` schema change.

**Tech Stack:** Python (Flask), Jinja2, vanilla JS, `unittest`.

## Global Constraints

- Run Python with `.venv/bin/python` (venv has Flask + pytest).
- Keys are never returned to the client; only `has_key` booleans and model lists.
- Only Ollama's endpoint is user-editable and it stays behind the existing SSRF allowlist.
- Model lists and error strings render via `.textContent`/structured DOM, never raw `innerHTML` of server strings (provider labels/model IDs are the trusted provider listing).
- Coach and Generator configs are stored independently and must remain independently settable.
- The five providers are `coach.PROVIDERS`: anthropic, openai, gemini, ollama, grok.

---

### Task 1: Backend — cache models, expose `known_models`, accept all five providers

**Files:**
- Modify: `app.py` (`api_coach_models` ~937-950; `_coach_public_config`; `api_workout_config` ~966-983)
- Test: `tests/test_ai_settings.py`

**Interfaces:**
- `/api/coach/models?provider=P` (GET): on success, caches `config.known_models[P]` and returns `{ok, models}`.
- `/api/coach/config` (GET): the payload additionally contains `known_models` (a `{provider: [ids]}` map).
- `/api/workout/config` (GET): `providers` covers all five (label + has_key). (POST): accepts any provider in `coach.PROVIDERS`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ai_settings.py`:

```python
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402
import coach  # noqa: E402


class AISettingsRoutes(unittest.TestCase):
    def setUp(self):
        # Isolate the on-disk config and satisfy the auth gate without the real token.
        self._tok = app.client.credentials.get("token")
        app.client.credentials["token"] = "test-token"
        self._cfgfile = coach._CONFIG_FILE
        fd, self._tmp = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        coach._CONFIG_FILE = self._tmp
        coach.save_config(coach.load_config())   # seed a clean default config on disk
        self._list_models = coach.list_models
        self.c = app.app.test_client()

    def tearDown(self):
        coach.list_models = self._list_models
        coach._CONFIG_FILE = self._cfgfile
        if self._tok is None:
            app.client.credentials.pop("token", None)
        else:
            app.client.credentials["token"] = self._tok
        try:
            os.remove(self._tmp)
        except OSError:
            pass

    def test_workout_config_accepts_all_five_providers(self):
        for p in ("anthropic", "openai", "gemini", "ollama", "grok"):
            r = self.c.post("/api/workout/config", json={"provider": p, "model": "m1"})
            self.assertEqual(r.status_code, 200, p)
            self.assertTrue(r.get_json().get("saved"), p)

    def test_workout_config_rejects_unknown_provider(self):
        r = self.c.post("/api/workout/config", json={"provider": "bogus", "model": "m"})
        self.assertEqual(r.status_code, 400)

    def test_workout_config_get_lists_all_five(self):
        d = self.c.get("/api/workout/config").get_json()
        self.assertEqual(set(d["providers"]), set(coach.PROVIDERS))

    def test_models_route_caches_known_models(self):
        coach.list_models = lambda provider, pc: (True, ["m-a", "m-b"])
        r = self.c.get("/api/coach/models?provider=anthropic").get_json()
        self.assertTrue(r["ok"])
        self.assertEqual(r["models"], ["m-a", "m-b"])
        on_disk = json.load(open(self._tmp))
        self.assertEqual(on_disk["known_models"]["anthropic"], ["m-a", "m-b"])

    def test_coach_config_get_exposes_known_models(self):
        coach.list_models = lambda provider, pc: (True, ["x1"])
        self.c.get("/api/coach/models?provider=openai")           # populate cache
        d = self.c.get("/api/coach/config").get_json()
        self.assertIn("known_models", d)
        self.assertEqual(d["known_models"].get("openai"), ["x1"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -m pytest tests/test_ai_settings.py -q`
Expected: FAIL — `test_workout_config_accepts_all_five_providers` (grok/ollama → 400), `test_models_route_caches_known_models` (no `known_models` written), `test_coach_config_get_exposes_known_models` (key absent).

- [ ] **Step 3: Cache models in `/api/coach/models`**

In `app.py`, in `api_coach_models`, replace the success return:

```python
    ok, result = coach.list_models(provider, coach.provider_cfg(cfg, provider))
    if not ok:
        return jsonify({"ok": False, "error": result})
    cfg.setdefault("known_models", {})[provider] = result
    coach.save_config(cfg)
    return jsonify({"ok": True, "models": result})
```

- [ ] **Step 4: Expose `known_models` in the coach config**

In `_coach_public_config`, add `known_models` to the returned dict. Change the `return` so it includes:

```python
    return {"provider": coach.active_provider(cfg), "providers": providers,
            "known_models": cfg.get("known_models", {}),
            "status": coach.status(cfg)}
```

(Keep whatever other keys the return already had; only add `known_models`.)

- [ ] **Step 5: Accept all five providers in the workout config**

In `api_workout_config`, change the GET `providers` comprehension and the POST validation:

```python
    if request.method == 'GET':
        return jsonify({"provider": coach.workout_provider(cfg),
                        "model": coach.workout_model(cfg),
                        "providers": {p: {"label": coach.PROVIDERS[p]["label"],
                                          "has_key": bool(coach.provider_cfg(cfg, p).get("api_key"))}
                                      for p in coach.PROVIDERS}})
    incoming = request.get_json(silent=True) or {}
    provider = incoming.get("provider")
    if provider not in coach.PROVIDERS:
        return jsonify({"error": "unknown provider"}), 400
    cfg["workout_generator"] = {"provider": provider, "model": incoming.get("model", "") or ""}
    coach.save_config(cfg)
    return jsonify({"saved": True, "provider": provider, "model": cfg["workout_generator"]["model"]})
```

- [ ] **Step 6: Run to verify pass**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -m pytest tests/test_ai_settings.py -q`
Expected: PASS (5 tests). Then the full suite: `.venv/bin/python -m pytest tests/ -q` → all pass.

- [ ] **Step 7: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add app.py tests/test_ai_settings.py
git commit -m "app: cache model lists, expose known_models, accept all five providers for generator"
```

---

### Task 2: Settings — rewrite the AI section into Part A (keys) + Part B (roles)

**Files:**
- Modify: `templates/settings.html` (markup ~201-274; the AI `<script>` functions ~294-438)

**Interfaces:**
- Consumes: `/api/coach/config` (GET now includes `known_models`), `/api/coach/models?provider=`, `/api/coach/config` (POST), `/api/workout/config` (GET/POST) from Task 1.

- [ ] **Step 1: Replace the two AI cards' markup**

In `templates/settings.html`, replace the two blocks — the `AI Coach` card (starts `<div class="mt-8 pt-6 border-t border-gray-700">` with `<h3 ...>AI Coach</h3>`, ~line 201) and the `AI Workout Generator` card (~line 252) through its closing `</div>` (~line 274) — with:

```html
    <div class="mt-8 pt-6 border-t border-gray-700">
        <h3 class="text-lg font-bold text-white mb-1">AI providers &amp; keys</h3>
        <p class="text-xs text-gray-500 mb-3">
            Add an API key for each provider you want to use, then <strong>Test &amp; load models</strong>
            to verify the key and download its model list. Keys live in <code>coach_config.json</code>
            on this machine (owner-only) and never leave it except in the model call. Ollama can point at
            the cloud (default) or a local daemon.
        </p>
        <div id="provider-rows" class="space-y-2"></div>
        <div id="coach-new-models" class="hidden mt-3 p-2 rounded bg-green-900/30 border border-green-700 text-xs text-green-300"></div>
    </div>

    <div class="mt-8 pt-6 border-t border-gray-700">
        <h3 class="text-lg font-bold text-white mb-1">Assign models</h3>
        <p class="text-xs text-gray-500 mb-3">Pick which provider and model powers each feature — they can differ.</p>

        <div class="mb-4">
            <label class="block text-xs font-bold mb-1 text-gray-400">Coach <span class="text-gray-600 font-normal">— the "Coach's read" on each History session</span></label>
            <div class="flex flex-wrap gap-2 items-center">
                <select id="coach-provider" onchange="onRoleProviderChange('coach')" class="p-2 bg-gray-700 rounded text-white border border-gray-600 text-sm"></select>
                <select id="coach-model" class="flex-grow min-w-[12rem] p-2 bg-gray-700 rounded text-white border border-gray-600 text-sm"></select>
                <button type="button" onclick="refreshRole('coach')" title="Reload this provider's models" class="px-2 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm border border-gray-600">&#8635;</button>
                <button type="button" onclick="saveCoach()" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 rounded text-sm font-bold">Save</button>
                <span id="coach-status" class="text-xs text-gray-400"></span>
            </div>
        </div>

        <div class="mb-2">
            <label class="block text-xs font-bold mb-1 text-gray-400">Workout Generator <span class="text-gray-600 font-normal">— "Generate Workout" on the Build Workout page</span></label>
            <div class="flex flex-wrap gap-2 items-center">
                <select id="wg-provider" onchange="onRoleProviderChange('wg')" class="p-2 bg-gray-700 rounded text-white border border-gray-600 text-sm"></select>
                <select id="wg-model" class="flex-grow min-w-[12rem] p-2 bg-gray-700 rounded text-white border border-gray-600 text-sm"></select>
                <button type="button" onclick="refreshRole('wg')" title="Reload this provider's models" class="px-2 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm border border-gray-600">&#8635;</button>
                <button type="button" onclick="wgSave()" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 rounded text-sm font-bold">Save</button>
                <span id="wg-status" class="text-xs text-gray-400"></span>
            </div>
        </div>
    </div>
```

- [ ] **Step 2: Replace the AI `<script>` functions**

The AI script begins with `const KEY_LINKS = {` (~line 285) and runs through the end of `wgSave` (~line 438), including `loadCoach`, `onProviderChange`, `showStatus`, `currentProvider`, `pcfg`, `saveKeyAndLoadModels`, `loadModels`, `saveCoach`, `checkNewModels`, `wgInit`, `wgLoadModels`, `wgSave`, and the `loadCoach().then(checkNewModels)` line. Replace **all of that** (keep the `KEY_LINKS` object) with:

```javascript
    const KEY_LINKS = {
        ollama:    ['ollama.com/settings/keys',        'https://ollama.com/settings/keys'],
        anthropic: ['console.anthropic.com',           'https://console.anthropic.com/settings/keys'],
        openai:    ['platform.openai.com',             'https://platform.openai.com/api-keys'],
        gemini:    ['aistudio.google.com',             'https://aistudio.google.com/app/apikey'],
        grok:      ['console.x.ai',                     'https://console.x.ai'],
    };

    let coachCfg = null;                 // /api/coach/config: {provider, providers, known_models, status}
    let wgCfg = null;                    // /api/workout/config: {provider, model, providers}
    const modelsByProvider = {};         // provider -> [model ids], seeded from known_models

    function pcfg(p) { return (coachCfg && coachCfg.providers[p]) || {}; }
    function keyed(p) { return pcfg(p).has_key || p === 'ollama'; }

    // ---------- Part A: provider key rows ----------
    function renderProviderRows() {
        const box = document.getElementById('provider-rows');
        box.innerHTML = '';
        for (const [p, v] of Object.entries(coachCfg.providers)) {
            const [linkLabel, url] = KEY_LINKS[p] || ['', '#'];
            const row = document.createElement('div');
            row.className = 'p-2 rounded border border-gray-700 bg-gray-800/40';
            row.innerHTML = `
                <div class="flex flex-wrap items-center gap-2">
                    <span class="w-28 text-sm text-gray-200 font-medium">${v.label}</span>
                    ${v.editable ? `<input type="text" id="ep-${p}" placeholder="https://ollama.com" class="w-44 p-2 bg-gray-700 rounded text-white border border-gray-600 text-xs font-mono">` : ''}
                    <input type="password" id="key-${p}" placeholder="${v.has_key ? 'key set — paste to change' : 'paste API key'}" class="flex-grow min-w-[10rem] p-2 bg-gray-700 rounded text-white border border-gray-600 text-sm font-mono">
                    <button type="button" data-p="${p}" class="test-btn px-3 py-2 bg-gray-600 hover:bg-gray-500 rounded text-sm font-bold whitespace-nowrap">Test &amp; load models</button>
                </div>
                <div class="flex items-center gap-2 mt-1 pl-1">
                    <span id="pstat-${p}" class="text-[11px]"></span>
                    ${linkLabel ? `<a href="${url}" target="_blank" class="text-indigo-400 hover:underline text-[11px]">get one &#8594; ${linkLabel}</a>` : ''}
                </div>`;
            box.appendChild(row);
            if (v.editable) document.getElementById(`ep-${p}`).value = v.endpoint || '';
            paintProviderStatus(p);
        }
        box.querySelectorAll('.test-btn').forEach(b => b.addEventListener('click', () => testProvider(b.dataset.p)));
    }

    function paintProviderStatus(p, override) {
        const st = document.getElementById(`pstat-${p}`);
        if (!st) return;
        if (override) { st.className = 'text-[11px] ' + override.cls; st.textContent = override.text; return; }
        const n = (modelsByProvider[p] || []).length;
        if (n) { st.className = 'text-[11px] text-green-400'; st.textContent = `✓ ${n} models cached`; }
        else if (keyed(p)) { st.className = 'text-[11px] text-yellow-400'; st.textContent = '● key set — Test & load models'; }
        else { st.className = 'text-[11px] text-gray-500'; st.textContent = '● no key'; }
    }

    async function testProvider(p) {
        paintProviderStatus(p, { cls: 'text-gray-400', text: 'Testing…' });
        const keyEl = document.getElementById(`key-${p}`);
        const epEl = document.getElementById(`ep-${p}`);
        const fields = {};
        if (keyEl && keyEl.value.trim()) fields.api_key = keyEl.value.trim();
        if (epEl) fields.endpoint = epEl.value.trim();
        try {
            if (Object.keys(fields).length) {
                const s = await (await fetch('/api/coach/config', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ providers: { [p]: fields } }) })).json();
                if (s.error) { paintProviderStatus(p, { cls: 'text-red-400', text: '✗ ' + s.error }); return; }
                coachCfg = s;
                if (keyEl) keyEl.value = '';
            }
            const d = await (await fetch('/api/coach/models?provider=' + encodeURIComponent(p))).json();
            if (!d.ok) { paintProviderStatus(p, { cls: 'text-red-400', text: '✗ ' + (d.error || 'key rejected') }); return; }
            modelsByProvider[p] = d.models;
            paintProviderStatus(p, { cls: 'text-green-400', text: `✓ key valid · ${d.models.length} models` });
            markKeyedProviders();
            if (document.getElementById('coach-provider').value === p) fillRoleModels('coach');
            if (document.getElementById('wg-provider').value === p) fillRoleModels('wg');
        } catch (e) {
            paintProviderStatus(p, { cls: 'text-red-400', text: '✗ ' + e });
        }
    }

    // ---------- Part B: role selectors ----------
    function providerOptions(selected) {
        return Object.entries(coachCfg.providers).map(([p, v]) =>
            `<option value="${p}" ${p === selected ? 'selected' : ''}>${v.label}${keyed(p) ? '' : ' (no key)'}</option>`).join('');
    }
    function markKeyedProviders() {
        const cs = document.getElementById('coach-provider'), ws = document.getElementById('wg-provider');
        const cp = cs.value, wp = ws.value;
        cs.innerHTML = providerOptions(cp);
        ws.innerHTML = providerOptions(wp);
    }
    function fillRoleModels(role) {
        const p = document.getElementById(`${role}-provider`).value;
        const sel = document.getElementById(`${role}-model`);
        const models = modelsByProvider[p] || [];
        const saved = role === 'coach' ? pcfg(p).model : (wgCfg && wgCfg.provider === p ? wgCfg.model : '');
        sel.innerHTML = models.length
            ? models.map(m => `<option value="${m}" ${m === saved ? 'selected' : ''}>${m}</option>`).join('')
            : `<option value="">— Test & load models above —</option>`;
    }
    function onRoleProviderChange(role) { fillRoleModels(role); }
    async function refreshRole(role) {
        await testProvider(document.getElementById(`${role}-provider`).value);
        fillRoleModels(role);
    }

    async function saveCoach() {
        const p = document.getElementById('coach-provider').value;
        const model = document.getElementById('coach-model').value;
        const st = document.getElementById('coach-status');
        st.className = 'text-xs text-gray-400'; st.textContent = 'Saving…';
        const d = await (await fetch('/api/coach/config', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider: p, providers: { [p]: { model } } }) })).json();
        if (d.error) { st.className = 'text-xs text-red-400'; st.textContent = d.error; return; }
        coachCfg = d;
        st.className = 'text-xs text-green-400';
        st.textContent = `Saved · ${d.status.label} · ${d.status.model || 'no model'}`;
    }
    async function wgSave() {
        const p = document.getElementById('wg-provider').value;
        const model = document.getElementById('wg-model').value;
        const st = document.getElementById('wg-status');
        st.className = 'text-xs text-gray-400'; st.textContent = 'Saving…';
        const d = await (await fetch('/api/workout/config', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider: p, model }) })).json();
        if (d.error) { st.className = 'text-xs text-red-400'; st.textContent = d.error; return; }
        wgCfg = { provider: d.provider, model: d.model, providers: (wgCfg || {}).providers };
        st.className = 'text-xs text-green-400';
        st.textContent = `Saved · ${d.provider} · ${d.model || 'no model'}`;
    }

    async function checkNewModels() {
        try {
            const d = await (await fetch('/api/coach/check_updates', { method: 'POST' })).json();
            const box = document.getElementById('coach-new-models');
            const entries = Object.entries(d.new || {});
            if (entries.length) {
                box.textContent = 'New models available: ' +
                    entries.map(([p, ms]) => `${(pcfg(p).label || p)}: ${ms.slice(0, 6).join(', ')}`).join(' · ');
                box.classList.remove('hidden');
            }
        } catch (e) { /* best effort */ }
    }

    async function initAI() {
        try { coachCfg = await (await fetch('/api/coach/config')).json(); } catch (e) { return; }
        try { wgCfg = await (await fetch('/api/workout/config')).json(); } catch (e) { wgCfg = null; }
        Object.assign(modelsByProvider, coachCfg.known_models || {});
        renderProviderRows();
        document.getElementById('coach-provider').innerHTML = providerOptions(coachCfg.provider);
        document.getElementById('wg-provider').innerHTML = providerOptions(wgCfg && wgCfg.provider);
        fillRoleModels('coach');
        fillRoleModels('wg');
    }
    initAI().then(checkNewModels);
```

- [ ] **Step 3: Verify the page renders and old IDs are gone**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -c "import app; print(app.app.test_client().get('/settings').status_code)"`
Expected: `200`.
Run: `grep -c "saveKeyAndLoadModels\|onProviderChange\|coach-endpoint-row\|wgLoadModels\|wgInit" templates/settings.html`
Expected: `0` (all old identifiers removed).
Run: `grep -c "provider-rows\|testProvider\|fillRoleModels\|initAI" templates/settings.html`
Expected: non-zero (new code present).

- [ ] **Step 4: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add templates/settings.html
git commit -m "settings: per-provider key rows + independent coach/generator model pickers"
```

---

### Task 3: Full-suite verification, live smoke, docs

**Files:**
- Modify: `README.md` (AI sections — note the new per-provider key/test flow and independent roles)

- [ ] **Step 1: Full suite**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -m pytest tests/ -q`
Expected: all pass (prior suite + the 5 new `test_ai_settings.py`).

- [ ] **Step 2: Live smoke (Ollama model list + independence)**

Confirm the model cache/list works end-to-end and coach vs generator save independently, using the real Ollama key already present:

```bash
cd /srv/speediance.labattsimon.com && .venv/bin/python -c "
import app, coach, json
c = app.app.test_client()
# models route returns the full list and caches it
m = c.get('/api/coach/models?provider=ollama').get_json()
print('ollama ok:', m.get('ok'), 'count:', len(m.get('models', [])))
cfg = coach.load_config()
print('cached known_models[ollama] count:', len(cfg.get('known_models', {}).get('ollama', [])))
# coach config GET now exposes known_models
cc = c.get('/api/coach/config').get_json()
print('coach config exposes known_models:', 'known_models' in cc, '| providers:', list(cc['providers'].keys()))
# workout config accepts ollama
w = c.post('/api/workout/config', json={'provider':'ollama','model': (m.get('models') or ['gpt-oss:120b'])[0]}).get_json()
print('workout saved:', w.get('saved'), w.get('provider'), w.get('model'))
" 2>&1 | grep -v '^DEBUG:'
```

Expected: `ollama ok: True count: 18` (or similar), cached count matches, coach config exposes `known_models` with all five providers listed, and the workout config saves with provider `ollama`.
Then restore the generator to its prior value:
```bash
cd /srv/speediance.labattsimon.com && .venv/bin/python -c "
import coach; cfg=coach.load_config(); cfg['workout_generator']={'provider':'anthropic','model':''}; coach.save_config(cfg); print('restored')"
```
Also load `/settings` in the browser and confirm: five provider rows, each with a key field + Test & load models; the Coach and Generator selectors each show all five providers and a full model dropdown for Ollama (not just gpt-oss).

- [ ] **Step 3: Update README**

In the AI-related sections of `README.md`, note that Settings now has per-provider key rows (enter a key, "Test & load models" validates it and downloads the model list) and independent Coach and Workout Generator model pickers (any of Anthropic/OpenAI/Google/Ollama/xAI), with model lists cached so they populate immediately. Match the README's existing voice.

- [ ] **Step 4: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add README.md
git commit -m "docs: document the reworked Settings AI provider/role UI"
```

---

## Self-Review

- **Spec coverage:** cache models + expose known_models + accept all five (T1); Part A key rows with Test & load models + Part B independent Coach/Generator selectors populated from cache, all five providers, Ollama added, "only gpt-oss" fixed via cache-seeded dropdowns (T2); suite + live smoke proving Ollama's full list and independent saves + README (T3). All spec sections covered.
- **Placeholder scan:** none — full code in every step.
- **Type consistency:** `/api/coach/config` GET returns `{provider, providers, known_models, status}` (T1) consumed by `initAI`/`pcfg`/`fillRoleModels` (T2); `/api/coach/models` returns `{ok, models}` (T1) consumed by `testProvider` (T2); `/api/workout/config` GET `{provider, model, providers}` and POST `{saved, provider, model}` (T1) consumed by `initAI`/`wgSave` (T2); `modelsByProvider`, `paintProviderStatus`, `fillRoleModels`, `markKeyedProviders` all defined and used within T2.
