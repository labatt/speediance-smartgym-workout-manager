# In-app AI Workout Generation — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a workout in-app — describe it, a two-stage LLM call builds it, it loads into the existing builder, and you save it — no copy-paste.

**Architecture:** A new pure module `workout_gen.py` builds prompts and validates JSON (no I/O, unit-tested). `coach.py` gains a workout-generator provider/model config that shares the per-provider API keys, plus a `chat_with(provider, model, …)` that reuses the existing provider dispatch. `app.py` adds `/api/workout/config` and `/api/workout/generate` (stage-1 select → stage-2 generate → validate). The result loads into the existing `create.html` builder via a refactored `loadWorkoutIntoBuilder(data)`.

**Tech Stack:** Python (Flask), stdlib `urllib` LLM client (via coach.py), Jinja2, vanilla JS, `unittest`.

## Global Constraints

- Pure core stays pure: `workout_gen.py` does NO I/O; every function is unit-tested.
- Weights are already in the account's unit — LABEL them (`unit_label`), never convert.
- All model output is untrusted: validate server-side (`validate_workout`); the builder renders structured fields, never HTML.
- Reuse the existing provider dispatch (`coach._chat_provider`) and its SSRF allowlist — do not add a second HTTP path.
- Auth-gate every new route (`if not client.credentials.get("token"): 401`); map Speediance auth errors via `_is_auth_error` to 401.
- Run Python with `.venv/bin/python` (the venv has Flask + pytest; system python does not).
- Candidate pool is capped at 60 exercises.

---

### Task 1: `workout_gen.py` pure core

**Files:**
- Create: `workout_gen.py`
- Test: `tests/test_workout_gen.py`

**Interfaces:**
- Produces: `MUSCLE_MAP: dict[int,str]`
- Produces: `exercise_tags(lib_item) -> (is_level: bool, is_timed: bool, is_unilateral: bool)`
- Produces: `merge_exercise(lib_item, detail=None) -> dict` with keys `id,title,category,focus,target,is_level,is_timed,is_unilateral,description`
- Produces: `compact_catalog(library) -> str`
- Produces: `build_selection_prompt(user_request, catalog) -> str`
- Produces: `parse_selected_ids(text, library, request="", limit=60) -> list[int]`
- Produces: `build_generation_system_prompt(exercises, unit_label) -> str` (exercises = list of merged dicts)
- Produces: `build_generation_user_prompt(user_request, references=None, assessment=None) -> str`
- Produces: `validate_workout(obj, library) -> (ok: bool, cleaned: dict, warnings: list[str])`

- [ ] **Step 1: Write failing tests**

Create `tests/test_workout_gen.py`:

```python
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import workout_gen as wg  # noqa: E402

# Minimal library fixtures shaped like get_library() items.
LIB = [
    {"id": 1001, "title": "Seated Row", "category_name": "Back", "trainingPartId2": 13,
     "mainMuscleGroupName": "Lats", "auxiliaryMuscleGroupList": [{"muscleGroupName": "Biceps"}],
     "dataStatType": 1, "completionMethod": 1, "isLeftRight": 0},
    {"id": 1002, "title": "Vita Twist", "category_name": "Core", "trainingPartId2": 17,
     "mainMuscleGroupName": "Abs", "auxiliaryMuscleGroupList": [],
     "dataStatType": 6, "completionMethod": 5, "isLeftRight": 0},
    {"id": 1003, "title": "Archer Row", "category_name": "Back", "trainingPartId2": 13,
     "mainMuscleGroupName": "Lats", "auxiliaryMuscleGroupList": [],
     "dataStatType": 1, "completionMethod": 1, "isLeftRight": 1},
]


class TestTagsAndCatalog(unittest.TestCase):
    def test_tags(self):
        self.assertEqual(wg.exercise_tags(LIB[0]), (False, False, False))
        self.assertEqual(wg.exercise_tags(LIB[1]), (True, True, False))   # Vita: level + timed
        self.assertEqual(wg.exercise_tags(LIB[2]), (False, False, True))  # unilateral

    def test_catalog_has_ids_titles_and_tags(self):
        cat = wg.compact_catalog(LIB)
        self.assertIn("[1001] Seated Row", cat)
        self.assertIn("[TIMED+LEVEL]", cat)          # Vita line
        self.assertIn("[UNILATERAL]", cat)           # Archer line
        self.assertIn("Back", cat)                   # category present


class TestSelection(unittest.TestCase):
    def test_parse_ids_from_json_array_keeps_only_known(self):
        text = 'Sure! [1001, 1002, 999999]'
        self.assertEqual(sorted(wg.parse_selected_ids(text, LIB)), [1001, 1002])

    def test_parse_ids_fallback_keyword_match(self):
        # No parseable IDs -> fall back to matching request words against titles/muscles.
        ids = wg.parse_selected_ids("no ids here", LIB, request="I want a row for my back")
        self.assertIn(1001, ids)

    def test_parse_ids_respects_limit(self):
        big = [{"id": i, "title": f"Ex{i}", "category_name": "X", "trainingPartId2": 13,
                "mainMuscleGroupName": "M", "auxiliaryMuscleGroupList": [],
                "dataStatType": 1, "completionMethod": 1, "isLeftRight": 0} for i in range(2000, 2200)]
        text = "[" + ",".join(str(i) for i in range(2000, 2200)) + "]"
        self.assertEqual(len(wg.parse_selected_ids(text, big, limit=60)), 60)


class TestGenerationPrompt(unittest.TestCase):
    def setUp(self):
        self.merged = [wg.merge_exercise(LIB[0], {"context": "Pull the handles to your torso."}),
                       wg.merge_exercise(LIB[1]),
                       wg.merge_exercise(LIB[2])]

    def test_system_prompt_states_unit_and_forbids_conversion(self):
        p = wg.build_generation_system_prompt(self.merged, "LBS")
        self.assertIn("LBS", p)
        self.assertIn("do not", p.lower())          # a do-not-convert instruction exists
        self.assertNotIn("KG", p.replace("LBS", ""))  # KG not prescribed when unit is LBS

    def test_system_prompt_includes_timed_and_unilateral_sections_when_relevant(self):
        p = wg.build_generation_system_prompt(self.merged, "LBS")
        self.assertIn("TIMED", p)
        self.assertIn("UNILATERAL", p)
        self.assertIn("OUTPUT", p.upper())          # schema section present

    def test_system_prompt_omits_sections_when_not_relevant(self):
        only_plain = [wg.merge_exercise(LIB[0])]
        p = wg.build_generation_system_prompt(only_plain, "KG")
        self.assertNotIn("[TIMED+LEVEL]", p)
        self.assertNotIn("UNILATERAL EXERCISES", p)

    def test_system_prompt_carries_description(self):
        p = wg.build_generation_system_prompt(self.merged, "LBS")
        self.assertIn("Pull the handles to your torso.", p)

    def test_user_prompt_has_request(self):
        u = wg.build_generation_user_prompt("30 minute back day")
        self.assertIn("30 minute back day", u)


class TestValidateWorkout(unittest.TestCase):
    def test_drops_unknown_ids_and_warns(self):
        obj = {"name": "W", "exercises": [
            {"id": 1001, "sets": [{"reps": 10, "weight": 40, "mode": 1, "rest": 60}]},
            {"id": 424242, "sets": [{"reps": 10, "weight": 40, "mode": 1, "rest": 60}]},
        ]}
        ok, cleaned, warnings = wg.validate_workout(obj, LIB)
        self.assertTrue(ok)
        self.assertEqual([e["id"] for e in cleaned["exercises"]], [1001])
        self.assertTrue(any("424242" in w for w in warnings))

    def test_drops_exercise_with_no_sets(self):
        obj = {"name": "W", "exercises": [{"id": 1001, "sets": []}]}
        ok, cleaned, warnings = wg.validate_workout(obj, LIB)
        self.assertFalse(ok)                         # nothing valid left
        self.assertEqual(cleaned["exercises"], [])

    def test_not_a_dict_is_rejected(self):
        ok, cleaned, warnings = wg.validate_workout(["nope"], LIB)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -m pytest tests/test_workout_gen.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'workout_gen'`.

- [ ] **Step 3: Implement `workout_gen.py`**

Create `workout_gen.py`:

```python
"""Build the prompts for in-app AI workout generation and validate the model's JSON.

Pure and unit-tested — NO I/O here (app.py fetches the library/details and dispatches the
LLM call via coach.py). The generation prompt is the server-side port of the old
create.html `generateFullPrompt`: it lists the available exercises with IDs and
[TIMED]/[TIMED+LEVEL]/[UNILATERAL] tags, the modes/presets/unit rules, and the output
JSON schema. Loads are LABELLED in the athlete's unit and never converted.
"""

import json
import re

MUSCLE_MAP = {11: "Chest", 12: "Shoulder", 13: "Back", 14: "Glutes",
              15: "Legs", 16: "Arms", 17: "Abs"}


def exercise_tags(lib_item):
    """(is_level, is_timed, is_unilateral) from a library item. Vita (dataStatType 6) is
    both level-based and timed; completionMethod 0/2/5 are timed windows."""
    is_level = lib_item.get("dataStatType") == 6
    is_timed = is_level or lib_item.get("completionMethod") in (0, 2, 5)
    is_unilateral = lib_item.get("isLeftRight") == 1
    return is_level, is_timed, is_unilateral


def _target(lib_item):
    target = lib_item.get("mainMuscleGroupName") or ""
    aux = ", ".join(a.get("muscleGroupName", "") for a in (lib_item.get("auxiliaryMuscleGroupList") or []))
    if aux:
        target = (target + ", " + aux) if target else aux
    return target


def _tag_str(is_level, is_timed, is_unilateral):
    t = ""
    if is_level:
        t += " [TIMED+LEVEL]"
    elif is_timed:
        t += " [TIMED]"
    if is_unilateral:
        t += " [UNILATERAL]"
    return t


def merge_exercise(lib_item, detail=None):
    """Merge a library item with its optional detail (for the description) into the compact
    dict the generation prompt renders."""
    is_level, is_timed, is_unilateral = exercise_tags(lib_item)
    desc = ""
    if detail:
        desc = (detail.get("context") or detail.get("motionFeeling") or "").strip()
    return {
        "id": int(lib_item["id"]),
        "title": lib_item.get("title", "Exercise"),
        "category": lib_item.get("category_name", ""),
        "focus": MUSCLE_MAP.get(lib_item.get("trainingPartId2"), "General"),
        "target": _target(lib_item),
        "is_level": is_level, "is_timed": is_timed, "is_unilateral": is_unilateral,
        "description": desc,
    }


def compact_catalog(library):
    """One name-only line per exercise for the cheap stage-1 selection pass."""
    lines = []
    for e in library:
        il, it, iu = exercise_tags(e)
        lines.append(f"[{e['id']}] {e.get('title','')}{_tag_str(il, it, iu)} "
                     f"(Category: {e.get('category_name','')}, Focus: "
                     f"{MUSCLE_MAP.get(e.get('trainingPartId2'), 'General')}, Target: {_target(e)})")
    return "\n".join(lines)


def build_selection_prompt(user_request, catalog):
    return (f'A user wants this workout: "{user_request}"\n\n'
            "From the exercise catalog below, choose the ones RELEVANT to that request "
            "(cover the target muscles, include sensible variety, at most 60).\n"
            "Reply with ONLY a JSON array of their numeric IDs, e.g. [1001, 1002]. No prose.\n\n"
            "CATALOG:\n" + catalog)


def parse_selected_ids(text, library, request="", limit=60):
    """Pull known exercise IDs out of the model's reply. Falls back to a keyword match of
    the request against titles/muscles so stage 2 always has a pool."""
    known = {int(e["id"]) for e in library}
    ids = []
    for m in re.findall(r"\d+", text or ""):
        v = int(m)
        if v in known and v not in ids:
            ids.append(v)
        if len(ids) >= limit:
            return ids
    if ids:
        return ids
    # Fallback: keyword match.
    words = {w for w in re.findall(r"[a-z]+", (request or "").lower()) if len(w) > 2}
    if not words:
        return [int(e["id"]) for e in library[:limit]]
    scored = []
    for e in library:
        hay = (e.get("title", "") + " " + _target(e) + " " + e.get("category_name", "")).lower()
        if any(w in hay for w in words):
            scored.append(int(e["id"]))
        if len(scored) >= limit:
            break
    return scored or [int(e["id"]) for e in library[:limit]]


def build_generation_system_prompt(exercises, unit_label):
    """Full 'professional fitness coach' system prompt for the selected exercise pool."""
    other = "kilograms" if unit_label == "LBS" else "pounds"
    has_timed = any(e["is_timed"] for e in exercises)
    has_uni = any(e["is_unilateral"] for e in exercises)

    p = [
        "You are a professional fitness coach using the Speediance Gym Monster.",
        "Create a custom workout using ONLY the exercises listed below, by their exact numeric id.",
        "",
        "AVAILABLE EXERCISES:",
        "Format: [ID] Title [tags] (Category, Focus, Target) — description",
    ]
    for e in exercises:
        line = (f"[{e['id']}] {e['title']}{_tag_str(e['is_level'], e['is_timed'], e['is_unilateral'])} "
                f"(Category: {e['category']}, Focus: {e['focus']}, Target: {e['target']})")
        if e["description"]:
            line += f" — {e['description']}"
        p.append(line)
    p += [
        "",
        "MODES:",
        "- 1: Standard  - 2: Chains (harder at top)  - 3: Eccentric (harder on the lowering).",
        "",
        "PRESET IDS:",
        f"- -1: Custom (absolute weight in {unit_label})",
        "- 1: Gain Muscle (RM 9-13, 8-12 reps)  - 3: Stamina (RM 15-20, 13-20 reps)  - 5: Strength (RM 4-9, 4-9 reps).",
        "Pick the preset that fits the goal; use -1 for absolute-weight/custom work.",
        "",
        "WEIGHT UNIT:",
        f"Absolute weights MUST be in {unit_label}. This account is configured for {unit_label} and the "
        f"value is stored verbatim — nothing converts it. Do NOT prescribe in {other}.",
        "Keep about one rep in reserve on RM prescriptions.",
    ]
    if has_timed:
        p += [
            "",
            "TIMED EXERCISES (tagged [TIMED] or [TIMED+LEVEL]):",
            "- Not rep-based: \"reps\" carries a DURATION IN SECONDS (typically 20-60) and \"unit\" MUST be \"sec\".",
            "- [TIMED+LEVEL] (Vita): \"weight\" is an INTENSITY LEVEL (start at 1; typical 10-16, often stepping up "
            "across sets), NOT a weight and NOT an RM. \"presetId\" MUST be -1.",
            "  Example: { \"reps\": 30, \"weight\": 12, \"mode\": 1, \"rest\": 60, \"unit\": \"sec\" }",
        ]
    if has_uni:
        p += [
            "",
            "UNILATERAL EXERCISES (tagged [UNILATERAL]):",
            "Write ONE set per working set and it is applied to BOTH sides identically. Only if you want a "
            "different load/reps per side, add \"isUnilateralExpanded\": true and list sides ALTERNATING "
            "left, right, left, right (first = left).",
        ]
    p += [
        "",
        "OUTPUT FORMAT — output ONLY a JSON object, no prose:",
        '{ "name": "Workout Name", "exercises": [',
        '  { "id": 1001, "presetId": -1, "sets": [ { "reps": 10, "weight": 40, "mode": 1, "rest": 60 } ] }',
        "] }",
        "For a normal exercise omit \"unit\" (defaults to reps). For [TIMED]/[TIMED+LEVEL], \"reps\" is seconds "
        "and \"unit\":\"sec\" is required.",
    ]
    return "\n".join(p)


def build_generation_user_prompt(user_request, references=None, assessment=None):
    """The user's request, plus optional referenced-workout context and an assessment
    summary (both wired in Phase 2; empty here)."""
    parts = [f'Build this workout: "{user_request}"']
    for ref in (references or []):
        parts.append("")
        parts.append(f"REFERENCE WORKOUT \"{ref.get('name','')}\" (JSON + exercise notes):")
        parts.append(json.dumps(ref.get("detail", {}), ensure_ascii=False))
        if ref.get("notes"):
            parts.append(ref["notes"])
    if assessment:
        parts.append("")
        parts.append("RECENT PERFORMANCE ASSESSMENT (use it to tune difficulty and progression):")
        parts.append(assessment)
    return "\n".join(parts)


def validate_workout(obj, library):
    """(ok, cleaned, warnings). Keep only exercises whose id is in the library and that have
    at least one set. Structure/coercion of timed/unilateral fields happens client-side on
    import against live metadata; here we guard IDs and shape."""
    warnings = []
    if not isinstance(obj, dict) or not isinstance(obj.get("exercises"), list):
        return False, {"name": "", "exercises": []}, ["Model did not return a workout object."]
    known = {int(e["id"]) for e in library}
    kept = []
    for ex in obj["exercises"]:
        if not isinstance(ex, dict):
            continue
        try:
            eid = int(ex.get("id"))
        except (TypeError, ValueError):
            warnings.append("Dropped an exercise with a non-numeric id.")
            continue
        if eid not in known:
            warnings.append(f"Dropped unknown exercise id {eid}.")
            continue
        sets = ex.get("sets")
        if not isinstance(sets, list) or not sets:
            warnings.append(f"Dropped exercise {eid} — no sets.")
            continue
        kept.append(ex)
    cleaned = {"name": obj.get("name", "AI Workout"), "exercises": kept}
    return bool(kept), cleaned, warnings
```

- [ ] **Step 4: Run to verify pass**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -m pytest tests/test_workout_gen.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add workout_gen.py tests/test_workout_gen.py
git commit -m "workout_gen: pure prompt-builder + JSON validator for in-app generation"
```

---

### Task 2: `coach.py` — workout-generator config + `chat_with`

**Files:**
- Modify: `coach.py` (`load_config` ~46-80, add helpers near `provider_cfg`/`chat`)
- Test: `tests/test_coach.py`

**Interfaces:**
- Consumes: `coach.PROVIDERS`, `coach._chat_provider`, `coach.provider_cfg` (existing).
- Produces: `coach.workout_provider(config) -> str`
- Produces: `coach.workout_model(config) -> str`
- Produces: `coach.chat_with(provider, model, prompt, config=None, system=None, timeout=120) -> (ok, text)`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_coach.py` (before `if __name__`):

```python
class TestWorkoutGeneratorConfig(unittest.TestCase):
    def _cfg(self):
        return {"provider": "ollama",
                "providers": {p: coach._blank_provider(p) for p in coach.PROVIDERS},
                "known_models": {}, "last_model_check": None,
                "workout_generator": {"provider": "anthropic", "model": "claude-x"}}

    def test_reads_workout_provider_and_model(self):
        cfg = self._cfg()
        self.assertEqual(coach.workout_provider(cfg), "anthropic")
        self.assertEqual(coach.workout_model(cfg), "claude-x")

    def test_defaults_when_missing(self):
        cfg = {"provider": "ollama",
               "providers": {p: coach._blank_provider(p) for p in coach.PROVIDERS}}
        self.assertIn(coach.workout_provider(cfg), coach.PROVIDERS)  # a valid provider
        self.assertEqual(coach.workout_model(cfg), "")

    def test_chat_with_refuses_without_model(self):
        cfg = self._cfg()
        ok, msg = coach.chat_with("anthropic", "", "hi", cfg, timeout=2)
        self.assertFalse(ok)
        self.assertIn("model", msg.lower())

    def test_chat_with_refuses_without_key(self):
        cfg = self._cfg()   # anthropic has a blank api_key
        ok, msg = coach.chat_with("anthropic", "claude-x", "hi", cfg, timeout=2)
        self.assertFalse(ok)
        self.assertIn("key", msg.lower())
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -m pytest tests/test_coach.py::TestWorkoutGeneratorConfig -q`
Expected: FAIL — `AttributeError: module 'coach' has no attribute 'workout_provider'`.

- [ ] **Step 3: Implement**

In `coach.py`, in `load_config()` after `cfg["last_model_check"] = saved.get("last_model_check")` (inside the `if "providers" in saved:` block) AND also ensure the key exists by default, change the default `cfg` dict (top of `load_config`) to include:

```python
        "workout_generator": {"provider": "anthropic", "model": ""},
```

and inside the `if "providers" in saved:` block add:

```python
            if isinstance(saved.get("workout_generator"), dict):
                cfg["workout_generator"].update({k: v for k, v in saved["workout_generator"].items() if v is not None})
```

Then add these helpers just below `provider_cfg` (~line 100):

```python
def workout_provider(config):
    wg = config.get("workout_generator") or {}
    p = wg.get("provider", "anthropic")
    return p if p in PROVIDERS else "anthropic"


def workout_model(config):
    return (config.get("workout_generator") or {}).get("model", "") or ""


def chat_with(provider, model, prompt, config=None, system=None, timeout=120):
    """Run a prompt through a SPECIFIC provider+model, using that provider's shared API key.
    Reuses the tested _chat_provider dispatch (and its SSRF allowlist)."""
    config = config or load_config()
    if provider not in PROVIDERS:
        return False, "Unknown provider."
    base = provider_cfg(config, provider)
    pc = {"api_key": base.get("api_key", ""), "endpoint": base.get("endpoint", PROVIDERS[provider]["endpoint"]),
          "model": model}
    return _chat_provider(provider, pc, prompt, timeout, system)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -m pytest tests/test_coach.py -q`
Expected: PASS (all — existing + the 4 new).

- [ ] **Step 5: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add coach.py tests/test_coach.py
git commit -m "coach: workout-generator provider/model config + chat_with dispatch"
```

---

### Task 3: `app.py` — `/api/workout/config` and `/api/workout/generate`

**Files:**
- Modify: `app.py` (near the coach routes ~836-900)

**Interfaces:**
- Consumes: `workout_gen.*` (Task 1), `coach.workout_provider/workout_model/chat_with` (Task 2), `client.get_library`, `client.get_batch_details`, `_unit_label`, `_is_auth_error`.
- Produces: routes `GET/POST /api/workout/config`, `POST /api/workout/generate`.

- [ ] **Step 1: Add the import**

At the top of `app.py`, next to `import coach`, add:

```python
import workout_gen
```

- [ ] **Step 2: Add config routes**

After the coach config route block (search for `@app.route('/api/coach/models')` and add above or below it):

```python
@app.route('/api/workout/config', methods=['GET', 'POST'])
def api_workout_config():
    if not client.credentials.get("token"):
        return jsonify({"error": "Unauthorized"}), 401
    cfg = coach.load_config()
    if request.method == 'GET':
        return jsonify({"provider": coach.workout_provider(cfg),
                        "model": coach.workout_model(cfg),
                        "providers": {p: {"label": coach.PROVIDERS[p]["label"],
                                          "has_key": bool(coach.provider_cfg(cfg, p).get("api_key"))}
                                      for p in ("anthropic", "openai", "gemini")}})
    incoming = request.get_json(silent=True) or {}
    provider = incoming.get("provider")
    if provider not in ("anthropic", "openai", "gemini"):
        return jsonify({"error": "provider must be anthropic, openai or gemini"}), 400
    cfg["workout_generator"] = {"provider": provider, "model": incoming.get("model", "") or ""}
    coach.save_config(cfg)
    return jsonify({"saved": True, "provider": provider, "model": cfg["workout_generator"]["model"]})
```

- [ ] **Step 3: Add the generate route**

```python
@app.route('/api/workout/generate', methods=['POST'])
def api_workout_generate():
    """Two-stage generation: cheap select pass narrows the pool, then a full generation pass
    writes the workout JSON, which is validated before it goes to the builder."""
    if not client.credentials.get("token"):
        return jsonify({"error": "Unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    user_request = (body.get("request") or "").strip()
    if not user_request:
        return jsonify({"error": "Describe the workout you want."}), 400

    cfg = coach.load_config()
    provider, model = coach.workout_provider(cfg), coach.workout_model(cfg)
    if not model or not coach.provider_cfg(cfg, provider).get("api_key"):
        return jsonify({"ok": False,
                        "text": "The AI Workout Generator isn't set up yet — pick a provider, add its key, "
                                "and choose a model in Settings."}), 200
    try:
        library = client.get_library()
        catalog = workout_gen.compact_catalog(library)

        ok, sel = coach.chat_with(provider, model, workout_gen.build_selection_prompt(user_request, catalog), cfg)
        pool_ids = workout_gen.parse_selected_ids(sel if ok else "", library, request=user_request)

        details = {}
        try:
            for d in (client.get_batch_details(pool_ids) or []):
                if d.get("id") is not None:
                    details[int(d["id"])] = d
        except Exception:
            details = {}   # descriptions are a nicety; proceed without them

        libmap = {int(e["id"]): e for e in library}
        merged = [workout_gen.merge_exercise(libmap[i], details.get(i)) for i in pool_ids if i in libmap]

        system = workout_gen.build_generation_system_prompt(merged, _unit_label().upper())
        user = workout_gen.build_generation_user_prompt(user_request)
        ok, text = coach.chat_with(provider, model, user, cfg, system=system)
        if not ok:
            return jsonify({"ok": False, "text": text}), 200

        parsed = _extract_json(text)
        if parsed is None:   # one repair retry
            ok, text = coach.chat_with(provider, model,
                                       "Return ONLY the workout as valid JSON, nothing else:\n" + text, cfg,
                                       system=system)
            parsed = _extract_json(text) if ok else None
        if parsed is None:
            return jsonify({"ok": False, "text": "The model did not return valid JSON. Try again or rephrase."}), 200

        ok, cleaned, warnings = workout_gen.validate_workout(parsed, library)
        if not ok:
            return jsonify({"ok": False, "text": "The generated workout had no usable exercises. Try again.",
                            "warnings": warnings}), 200
        return jsonify({"ok": True, "workout": cleaned, "pool_ids": pool_ids, "warnings": warnings})
    except Exception as e:
        if _is_auth_error(e):
            return jsonify({"error": str(e)}), 401
        return jsonify({"error": str(e)}), 500
```

- [ ] **Step 4: Add the JSON extractor helper**

Near `_unit_label` (search for `def _unit_label`), add:

```python
def _extract_json(text):
    """Best-effort parse of a JSON object out of a model reply (handles ```json fences and
    surrounding prose). Returns the dict or None."""
    if not text:
        return None
    import re as _re
    s = text.strip()
    s = _re.sub(r"^```(?:json)?", "", s).strip()
    s = _re.sub(r"```$", "", s).strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    start, depth = s.find("{"), 0
    if start == -1:
        return None
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(s[start:i + 1])
                except Exception:
                    return None
    return None
```

- [ ] **Step 5: Smoke-test import + validation gate**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -c "import app; c=app.app.test_client(); r=c.post('/api/workout/generate', json={}); print(r.status_code, r.get_json())"`
Expected: `400 {'error': 'Describe the workout you want.'}` (route wired, validation before any LLM/auth path). A 401 is also acceptable if no token is loaded in this process.

- [ ] **Step 6: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add app.py
git commit -m "app: /api/workout/config + two-stage /api/workout/generate"
```

---

### Task 4: Settings — "AI Workout Generator" card

**Files:**
- Modify: `templates/settings.html` (after the AI Coach card block; card ~202-241)

**Interfaces:**
- Consumes: `/api/workout/config` (GET/POST), `/api/coach/models?provider=` (existing live model list).

- [ ] **Step 1: Add the card markup**

Immediately after the AI Coach card's closing `</div>` (find the block that starts at the `<h3>AI Coach</h3>` card and ends its container), insert a sibling card:

```html
<div class="bg-gray-800 rounded-lg p-6 border border-gray-700 mt-6">
    <h3 class="text-lg font-bold text-white mb-1">AI Workout Generator</h3>
    <p class="text-gray-400 text-sm mb-4">Generate workouts in-app on the Build Workout page.
        Uses the same API keys as the coach; pick which provider and model to generate with.</p>
    <label class="block text-sm text-gray-300 mb-1">Provider</label>
    <select id="wg-provider" onchange="wgLoadModels()"
            class="w-full p-2 bg-gray-700 rounded text-white border border-gray-600 text-sm mb-3">
        <option value="anthropic">Anthropic (Claude)</option>
        <option value="openai">OpenAI (ChatGPT)</option>
        <option value="gemini">Google (Gemini)</option>
    </select>
    <div class="mb-3">
        <label class="block text-sm text-gray-300 mb-1">Model</label>
        <select id="wg-model" class="w-full p-2 bg-gray-700 rounded text-white border border-gray-600 text-sm"></select>
        <p id="wg-msg" class="text-[11px] text-gray-500 mt-1"></p>
    </div>
    <div class="flex gap-2">
        <button onclick="wgLoadModels()" type="button"
                class="px-3 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm border border-gray-600">Load models</button>
        <button onclick="wgSave()" type="button"
                class="px-3 py-2 bg-indigo-600 hover:bg-indigo-700 rounded text-sm font-bold">Save</button>
    </div>
</div>
```

- [ ] **Step 2: Add the card script**

Before the closing `</script>`/`{% endblock %}` of settings.html, add:

```javascript
async function wgInit() {
    try {
        const r = await fetch('/api/workout/config');
        const d = await r.json();
        if (d.provider) document.getElementById('wg-provider').value = d.provider;
        await wgLoadModels(d.model);
    } catch (e) { /* not configured yet */ }
}
async function wgLoadModels(selectModel) {
    const provider = document.getElementById('wg-provider').value;
    const sel = document.getElementById('wg-model');
    const msg = document.getElementById('wg-msg');
    msg.textContent = 'Loading models…';
    try {
        const r = await fetch('/api/coach/models?provider=' + encodeURIComponent(provider));
        const d = await r.json();
        if (!d.ok) { msg.textContent = d.error || 'Could not load models (is the key set for this provider?)'; sel.innerHTML = ''; return; }
        sel.innerHTML = d.models.map(m => `<option value="${m}">${m}</option>`).join('');
        if (selectModel && d.models.includes(selectModel)) sel.value = selectModel;
        msg.textContent = `${d.models.length} models`;
    } catch (e) { msg.textContent = 'Could not load models.'; }
}
async function wgSave() {
    const provider = document.getElementById('wg-provider').value;
    const model = document.getElementById('wg-model').value;
    const msg = document.getElementById('wg-msg');
    const r = await fetch('/api/workout/config', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ provider, model })
    });
    const d = await r.json();
    msg.textContent = d.saved ? `Saved · ${d.model || '(no model)'}` : (d.error || 'Save failed');
}
wgInit();
```

- [ ] **Step 3: Verify page renders**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -c "import app; print(app.app.test_client().get('/settings').status_code)"`
Expected: `200` (or `302` to settings-less redirect if no token; a clean render/无 error is the target).

- [ ] **Step 4: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add templates/settings.html
git commit -m "settings: AI Workout Generator provider/model card"
```

---

### Task 5: Create page — request box, Generate Workout button, load-into-builder

**Files:**
- Modify: `templates/create.html` (buttons ~72-85; `processImport` ~1246-1325; add generate UI + JS)

**Interfaces:**
- Consumes: `/api/workout/generate` (Task 3).
- Produces: `loadWorkoutIntoBuilder(data)` (refactored out of `processImport`), `generateWorkout()`.

- [ ] **Step 1: Refactor `processImport` to reuse a loader**

In `templates/create.html`, change `processImport` so its body (from `if (data.name)` through `renderBuilder(); closeImportModal(); alert(...)`) is extracted. Replace the existing `window.processImport = async () => { ... }` so it becomes:

```javascript
    // Load a {name, exercises:[...]} object into the builder. Shared by manual JSON import
    // and AI generation. Fetches live metadata per exercise so timed/level/unilateral coercion
    // uses the machine's own truth, not the JSON's claims.
    window.loadWorkoutIntoBuilder = async (data) => {
        if (data.name) document.getElementById('plan-name').value = data.name;
        if (!data.exercises || !Array.isArray(data.exercises)) {
            alert("Invalid workout: missing 'exercises' array."); return false;
        }
        workoutData = [];
        for (const ex of data.exercises) {
            const groupId = ex.id;
            const meta = await fetchExerciseMetadata(groupId);
            const libEx = fullLibrary.find(e => e.id == groupId);
            const title = libEx ? libEx.title : (ex.title || "Unknown Exercise");
            const mandatedUnit = getSetGoalUnit(meta);
            const setsParsed = ex.sets.map(s => ({
                reps: parseInt(s.reps),
                weight: parseFloat(String(s.weight ?? 0).replace(',', '.')),
                mode: parseInt(s.mode || 1),
                rest: parseInt(s.rest || 60),
                unit: mandatedUnit || (String(s.unit || '').toLowerCase() === 'sec' ? 'sec' : 'reps')
            }));
            const alreadyExpanded = !!ex.isUnilateralExpanded;
            const finalSets = parseImportedSets(setsParsed, meta.isUnilateral, alreadyExpanded);
            const rawPreset = ex.preset ?? ex.presetId;
            const importedPresetId = (rawPreset !== undefined && rawPreset !== null && rawPreset !== '')
                ? parseInt(rawPreset) : -1;
            workoutData.push({
                internalId: Date.now() + Math.random(),
                groupId: parseInt(groupId), title: title,
                img: meta.variants?.[0]?.img || (libEx ? libEx.img : ""),
                isUnilateral: meta.isUnilateral, variants: meta.variants, presets: meta.presets,
                selectedVariantId: meta.variants?.[0]?.id || groupId,
                selectedPresetId: importedPresetId, sets: finalSets,
                cablePosition: meta.cablePosition, completionMethod: meta.completionMethod,
                selectCompletionMethod: meta.selectCompletionMethod, dataStatType: meta.dataStatType,
                metValue: meta.metValue, trainingPartId2: meta.trainingPartId2,
                auxiliaryMuscleGroupList: meta.auxiliaryMuscleGroupList
            });
        }
        renderBuilder();
        return true;
    };

    window.processImport = async () => {
        try {
            const data = JSON.parse(document.getElementById('import-json').value);
            if (await loadWorkoutIntoBuilder(data)) { closeImportModal(); alert("Workout imported successfully!"); }
        } catch (e) {
            alert("Invalid JSON: " + e.message);
        }
    };
```

- [ ] **Step 2: Replace the "Generate Prompt" button with the generator UI**

Find the "Generate Prompt" button (~72-80) and replace that single `<button>…Generate Prompt…</button>` with:

```html
                        <div class="w-full">
                            <label class="block text-sm text-gray-300 mb-1">Describe the workout you want the AI to build</label>
                            <textarea id="wg-request" rows="2"
                                class="w-full bg-gray-900 text-white p-3 rounded border border-gray-600 focus:border-purple-500 outline-none text-sm"
                                placeholder="e.g. A 40-minute back and biceps day, moderate volume, include some eccentric work."></textarea>
                            <button onclick="generateWorkout()" id="wg-generate-btn"
                                class="mt-2 bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded font-bold transition shadow-lg shadow-purple-900/20">
                                Generate Workout
                            </button>
                            <span id="wg-generate-msg" class="text-sm text-gray-400 ml-2"></span>
                        </div>
```

- [ ] **Step 3: Add `generateWorkout()`**

Near `loadWorkoutIntoBuilder`, add:

```javascript
    window.generateWorkout = async () => {
        const request = document.getElementById('wg-request').value.trim();
        const msg = document.getElementById('wg-generate-msg');
        const btn = document.getElementById('wg-generate-btn');
        if (!request) { msg.textContent = 'Describe the workout first.'; return; }
        btn.disabled = true; msg.textContent = 'Generating… this can take a moment.';
        try {
            const r = await fetch('/api/workout/generate', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ request })
            });
            const d = await r.json();
            if (d.error) { msg.textContent = d.error; return; }
            if (!d.ok) { msg.textContent = d.text || 'Generation failed.'; return; }
            const loaded = await loadWorkoutIntoBuilder(d.workout);
            if (loaded) {
                msg.textContent = (d.warnings && d.warnings.length)
                    ? `Loaded with notes: ${d.warnings.join(' ')}`
                    : 'Loaded below — review, tweak, name it, and Save.';
                document.getElementById('plan-name').focus();
            }
        } catch (e) {
            msg.textContent = 'Request failed: ' + e;
        } finally {
            btn.disabled = false;
        }
    };
```

- [ ] **Step 4: Verify page renders and the old prompt path is gone**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -c "import app; print(app.app.test_client().get('/create').status_code)"`
Expected: `200` (or `302` if no token). Load `/create` in the browser and confirm the request box + Generate Workout button appear and Import JSON still works.

- [ ] **Step 5: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add templates/create.html
git commit -m "create: in-app Generate Workout box + shared loadWorkoutIntoBuilder"
```

---

### Task 6: Full-suite verification, live smoke, README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Run the whole suite**

Run: `cd /srv/speediance.labattsimon.com && .venv/bin/python -m pytest tests/ -q`
Expected: all pass (existing + `test_workout_gen.py` + the new coach tests). Note: `test_e2e_workouts.py` is a live-API test excluded from `tests/`; the pre-existing 2 failures there are unrelated.

- [ ] **Step 2: Configure + live end-to-end (real provider)**

Set the workout generator to a provider whose key is already saved, then generate one workout in-process:

```bash
cd /srv/speediance.labattsimon.com && .venv/bin/python -c "
import app, coach
cfg = coach.load_config()
# use whichever provider already has a key; fall back to the coach's active one
prov = next((p for p in ('anthropic','openai','gemini') if coach.provider_cfg(cfg,p).get('api_key')), None)
print('provider with key:', prov)
if prov:
    ok, models = coach.list_models(prov, coach.provider_cfg(cfg, prov))
    m = models[0] if ok and models else ''
    cfg['workout_generator'] = {'provider': prov, 'model': m}; coach.save_config(cfg)
    c = app.app.test_client()
    d = c.post('/api/workout/generate', json={'request':'a short 20-minute back workout, 4 exercises'}).get_json()
    print('ok', d.get('ok'), 'exercises', len((d.get('workout') or {}).get('exercises', [])), 'warnings', d.get('warnings'))
    print('name', (d.get('workout') or {}).get('name'))
" 2>&1 | grep -v '^DEBUG:'
```

Expected: `ok True`, a non-zero exercise count, and a name. (If no provider has a key yet, `provider with key: None` — then set one in Settings and re-run.)

- [ ] **Step 3: Update README**

Add an "AI workout generation (in-app)" bullet to the feature list and a short paragraph: describe a workout on the Build Workout page, pick the generator provider/model in Settings, the two-stage auto-pick, that loads/units follow the account's unit and are never converted, and that the result loads into the builder to review/edit/save. Note the old Generate-Prompt copy-paste flow is replaced (Import JSON remains as a manual fallback).

- [ ] **Step 4: Commit**

```bash
cd /srv/speediance.labattsimon.com
git add README.md
git commit -m "docs: document in-app AI workout generation (phase 1)"
```

---

## Self-Review

- **Spec coverage (Phase 1 scope):** `workout_gen.py` core + validation (T1); dedicated provider/model config sharing keys + `chat_with` (T2); `/api/workout/config` + two-stage `/api/workout/generate` with repair retry (T3); Settings card with live models (T4); create-page request box + Generate Workout + load-into-builder + save via existing `/create` (T5); tests + live smoke + README (T6). Parts 1, 2, 4, 7 covered. Parts 3, 5, 6 are Phase 2/3 (separate plans), as designed.
- **Placeholder scan:** none — every code step is complete.
- **Type consistency:** `merge_exercise` dict keys (`id,title,category,focus,target,is_level,is_timed,is_unilateral,description`) are produced in T1 and consumed by `build_generation_system_prompt` in T1 and the route in T3; `chat_with(provider, model, prompt, config, system, timeout)` defined T2, called T3; `validate_workout -> (ok, cleaned, warnings)` defined T1, used T3; `loadWorkoutIntoBuilder(data) -> bool` defined T5, called by `processImport` and `generateWorkout` in T5; `/api/workout/generate` returns `{ok, workout, pool_ids, warnings}` in T3, consumed in T5.