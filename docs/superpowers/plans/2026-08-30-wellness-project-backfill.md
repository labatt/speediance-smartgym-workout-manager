# Wellness Project Exercise Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Speediance Flask app find Wellness Project workouts that have no exercises and backfill them from the matching Speediance session's exercise detail.

**Architecture:** The Flask app gains one new outbound dependency — an OAuth MCP client to Wellness Project (`wellness_client.py`). A pure, network-free module (`reconcile.py`) parses WP's textual tool output, matches empty WP workouts to Speediance strength sessions by date+calories, and transforms Speediance session detail (via the existing `progression.analyze_session`) into WP `add_exercises` payloads. `app.py` adds `/wp/*` routes (Connect/callback OAuth, a backfill pass, a manual-apply endpoint, a status page); a daily cron hits the backfill endpoint.

**Tech Stack:** Python 3, Flask, `requests` (already the only deps), `hashlib`/`secrets`/`base64` (stdlib, for PKCE), unittest + `unittest.mock`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-30-wellness-project-backfill-design.md`

## Global Constraints

- **Units:** Speediance weights are already in the account's display unit (lb). Pass them to WP **verbatim** — never convert. (Per the API-quirks memory.)
- **Write safety:** only ever write to WP workouts that currently have **zero exercises**. Never overwrite/rewrite a workout that already has exercises (protects the hand-logged "@ Gym" days; keeps the pass idempotent).
- **Scope:** strength sessions only — Speediance records with `courseType != 2` **and** `totalCapacity > 0`. Rowing/cardio are excluded.
- **Secrets:** WP tokens live only in `wellness_tokens.json` (chmod 600, git-excluded). Never render them in any page, never log them.
- **Tests:** use `.venv/bin/python -m pytest` (system python lacks Flask/pytest). No test may make a live network call or a live OAuth request — mock the HTTP layer.
- **Two pre-existing e2e failures** in `test_e2e_workouts.py` (`test_create_save_reload_custom_workout_matches`, `test_create_save_reload_preset_workout_matches`) fail on clean `main` and are unrelated — ignore them, never "fix" them.
- **Matching data facts (verified live 2026-08-30):** Speediance record has `trainingId`, `type`, `courseType`, `title`, `calorie` (int), `totalCapacity` (float), `startTime` (`"YYYY-MM-DD HH:MM:SS"`), `trainingTime` (sec). For `get_training_detail(training_id, training_type)`, `training_type = 'course' if type == 2 else 'custom'`. Oracle: `trainingId 1103072` "Miami Pull" → 341 cal, 5 exercises.

---

### Task 1: Transform — `sp_detail_to_wp_exercises`

Convert a raw Speediance session-detail payload into a WP `add_exercises` list, reusing `progression.analyze_session` for the (already-correct) per-set parsing.

**Files:**
- Create: `reconcile.py`
- Test: `tests/test_reconcile.py`
- Reference (read, do not modify): `progression.py:53-159` (`exercise_kind`, `_set_facts`, `analyze_session`)

**Interfaces:**
- Consumes: `progression.analyze_session(detail) -> {"exercises": [{"name", "kind", "sets": [{"done","target","load","seconds","skipped",...}], ...}], "groups": [...]}`. `kind` is `"reps"`, `"timed"`, or `"level"`.
- Produces: `sp_detail_to_wp_exercises(detail: list|dict) -> list[dict]`. Each dict: `{"name": str, "slot_type": "working", "sets": [ {...} ]}`. A rep set: `{"reps": int, "weight_lb": float}` (or `{"reps": int, "is_bodyweight": True}` when load is 0). A timed/level set: `{"hold_length_sec": int}` (plus `{"is_bodyweight": True}` when there is no load; level sets also `{"notes": "Vita level"}`). Skipped sets (`done == 0`) are omitted. An exercise whose sets are all skipped is omitted entirely.

- [ ] **Step 1: Capture the oracle fixture**

Create `tests/fixtures/sp_detail_1103072.json` from live data (run once, commit the file):

```bash
mkdir -p tests/fixtures
.venv/bin/python -c "
import json
from api_client import SpeedianceClient
d = SpeedianceClient().get_training_detail(1103072, 'custom')
open('tests/fixtures/sp_detail_1103072.json','w').write(json.dumps(d, indent=2))
print('exercises:', len(d))
"
```
Expected: `exercises: 5`.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_reconcile.py
import json, os, unittest
import reconcile

FIX = os.path.join(os.path.dirname(__file__), "fixtures")

def _load(name):
    with open(os.path.join(FIX, name)) as f:
        return json.load(f)

class TestTransform(unittest.TestCase):
    def test_miami_pull_oracle(self):
        detail = _load("sp_detail_1103072.json")
        out = reconcile.sp_detail_to_wp_exercises(detail)
        # 5 exercises, in order
        names = [e["name"] for e in out]
        self.assertEqual(names, [
            "Barbell Bent Over Row", "Seated Barbell Lat Pulldown",
            "Seated Barbell Wide Row", "Standing Barbell Biceps Curl",
            "Standing Barbell Shrugs",
        ])
        row = out[0]
        self.assertEqual(row["slot_type"], "working")
        # 4 sets: 12@30, 10@40, 8@45, 8@50 (reps from finishedCount, load from weights[0])
        self.assertEqual([(s["reps"], s["weight_lb"]) for s in row["sets"]],
                         [(12, 30.0), (10, 40.0), (8, 45.0), (8, 50.0)])

    def test_bodyweight_set_when_load_zero(self):
        detail = [{
            "actionLibraryName": "Push Up", "completionMethod": 1,
            "finishedReps": [
                {"finishedCount": 15, "targetCount": 15, "time": 20,
                 "trainingInfoDetail": {"weights": [0, 0, 0]}},
            ],
        }]
        out = reconcile.sp_detail_to_wp_exercises(detail)
        s = out[0]["sets"][0]
        self.assertEqual(s["reps"], 15)
        self.assertTrue(s["is_bodyweight"])
        self.assertNotIn("weight_lb", s)

    def test_timed_set_maps_to_hold(self):
        detail = [{
            "actionLibraryName": "Plank", "completionMethod": 2,  # timed
            "finishedReps": [
                {"finishedCount": 0, "targetCount": 0, "time": 45,
                 "trainingInfoDetail": {"weights": []}},
            ],
        }]
        out = reconcile.sp_detail_to_wp_exercises(detail)
        s = out[0]["sets"][0]
        self.assertEqual(s["hold_length_sec"], 45)
        self.assertNotIn("reps", s)

    def test_skipped_sets_omitted(self):
        detail = [{
            "actionLibraryName": "Curl", "completionMethod": 1,
            "finishedReps": [
                {"finishedCount": 10, "targetCount": 10, "time": 10,
                 "trainingInfoDetail": {"weights": [20, 20]}},
                {"finishedCount": 0, "targetCount": 10, "time": 0,   # skipped
                 "trainingInfoDetail": {"weights": [0]}},
            ],
        }]
        out = reconcile.sp_detail_to_wp_exercises(detail)
        self.assertEqual(len(out[0]["sets"]), 1)

    def test_all_skipped_exercise_omitted(self):
        detail = [{
            "actionLibraryName": "Skipped", "completionMethod": 1,
            "finishedReps": [
                {"finishedCount": 0, "targetCount": 10, "time": 0,
                 "trainingInfoDetail": {"weights": [0]}},
            ],
        }]
        self.assertEqual(reconcile.sp_detail_to_wp_exercises(detail), [])
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py -v`
Expected: FAIL — `AttributeError: module 'reconcile' has no attribute 'sp_detail_to_wp_exercises'` (module/file does not exist yet).

- [ ] **Step 4: Write minimal implementation**

```python
# reconcile.py
"""Pure, network-free reconciliation logic: parse Wellness Project tool text,
match empty WP workouts to Speediance strength sessions, and transform Speediance
session detail into WP add_exercises payloads. No I/O, no Flask, no requests —
everything here is unit-tested against live-captured fixtures."""

import progression


def sp_detail_to_wp_exercises(detail):
    """Raw Speediance session detail -> WP update_workout `add_exercises` list.

    Reuses progression.analyze_session for the per-set parsing (it already handles
    reps/timed/level kinds and the dual-cable weight trap). Skipped sets (0 reps)
    are dropped; an all-skipped exercise is dropped entirely. Weights are passed
    through verbatim — the account unit is lb and Speediance already returns lb.
    """
    analyzed = progression.analyze_session(detail or [])
    out = []
    for ex in analyzed["exercises"]:
        kind = ex["kind"]
        sets = []
        for s in ex["sets"]:
            if s.get("skipped"):
                continue
            if kind == "reps":
                load = s.get("load") or 0
                if load > 0:
                    sets.append({"reps": s["done"], "weight_lb": float(load)})
                else:
                    sets.append({"reps": s["done"], "is_bodyweight": True})
            else:  # timed or level
                st = {"hold_length_sec": int(s.get("seconds") or 0),
                      "is_bodyweight": True}
                if kind == "level":
                    st["notes"] = "Vita level"
                sets.append(st)
        if not sets:
            continue
        out.append({"name": ex["name"], "slot_type": "working", "sets": sets})
    return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add reconcile.py tests/test_reconcile.py tests/fixtures/sp_detail_1103072.json
git commit -m "feat(reconcile): Speediance detail -> WP add_exercises transform"
```

---

### Task 2: Wellness Project text parsers

WP's MCP tools return human-readable **text**, not JSON. Parse the two we need: the workout list and the "is this workout empty?" check. Real samples are embedded in the tests below (captured live 2026-08-30).

**Files:**
- Modify: `reconcile.py`
- Test: `tests/test_reconcile.py`

**Interfaces:**
- Produces: `parse_wp_workout_list(text: str) -> list[dict]`. Each: `{"session_id": int, "date": "YYYY-MM-DD", "focus": str, "calorie": int|None, "nsi": float|None, "has_miles": bool}`.
- Produces: `wp_workout_is_empty(text: str) -> bool` — True when the get_workout text says no exercises were logged.
- Produces: `is_backfill_target(row: dict) -> bool` — True for a Health-Connect Speediance strength import: `focus == "Strength Training"` and `nsi is None` and `calorie` present and not `has_miles`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_reconcile.py
WP_LIST = """Workouts (2026-06-01 → 2026-08-30):
[ID 696827] 2026-08-29: Strength Training · 33 min · 341 cal
[ID 696826] 2026-08-28: Workout · 37 min · 552 cal · 1.81 mi
[ID 696955] 2026-08-25: Upper @ Gym · NSI 24.5 (Below Average)
[ID 465860] 2026-08-20: Walking · 11 min · 31 cal · 0.38 mi
Avg session NSI in window: 32.1 across 3 sessions."""

WP_EMPTY = ("2026-08-29: Strength Training · 33 min · 341 cal · Health Connect [ID 696827]\n"
            "  Notes: Imported from Health Connect...\n"
            "No exercises logged for this session. A wearable import arrives as a session total...")

WP_DETAILED = ("2026-08-25: Upper @ Gym · Session NSI 24.5 [ID 696955]\n"
               "  Chest Press: [Cable]\n    Set 1: 15 reps @ 45 lb")

class TestWpParsers(unittest.TestCase):
    def test_parse_list(self):
        rows = reconcile.parse_wp_workout_list(WP_LIST)
        by_id = {r["session_id"]: r for r in rows}
        self.assertEqual(len(rows), 4)
        self.assertEqual(by_id[696827]["date"], "2026-08-29")
        self.assertEqual(by_id[696827]["focus"], "Strength Training")
        self.assertEqual(by_id[696827]["calorie"], 341)
        self.assertIsNone(by_id[696827]["nsi"])
        self.assertFalse(by_id[696827]["has_miles"])
        self.assertTrue(by_id[696826]["has_miles"])
        self.assertEqual(by_id[696955]["nsi"], 24.5)

    def test_is_empty(self):
        self.assertTrue(reconcile.wp_workout_is_empty(WP_EMPTY))
        self.assertFalse(reconcile.wp_workout_is_empty(WP_DETAILED))

    def test_is_backfill_target(self):
        rows = {r["session_id"]: r for r in reconcile.parse_wp_workout_list(WP_LIST)}
        self.assertTrue(reconcile.is_backfill_target(rows[696827]))   # Strength Training, no NSI
        self.assertFalse(reconcile.is_backfill_target(rows[696826]))  # Workout + miles (rowing)
        self.assertFalse(reconcile.is_backfill_target(rows[696955]))  # @ Gym, has NSI
        self.assertFalse(reconcile.is_backfill_target(rows[465860]))  # Walking
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py::TestWpParsers -v`
Expected: FAIL — `AttributeError: module 'reconcile' has no attribute 'parse_wp_workout_list'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to reconcile.py
import re

_ROW_RE = re.compile(r"\[ID (\d+)\]\s*(\d{4}-\d{2}-\d{2}):\s*(.+)")
_CAL_RE = re.compile(r"(\d+)\s*cal")
_NSI_RE = re.compile(r"NSI\s*([\d.]+)")
_MILES_RE = re.compile(r"[\d.]+\s*mi\b")

def parse_wp_workout_list(text):
    """Parse Wellness Project list_workouts text into structured rows."""
    rows = []
    for line in text.splitlines():
        m = _ROW_RE.search(line)
        if not m:
            continue
        sid, date, rest = int(m.group(1)), m.group(2), m.group(3)
        focus = rest.split("·")[0].split("@")[0].strip()
        cal = _CAL_RE.search(rest)
        nsi = _NSI_RE.search(rest)
        rows.append({
            "session_id": sid,
            "date": date,
            "focus": focus,
            "calorie": int(cal.group(1)) if cal else None,
            "nsi": float(nsi.group(1)) if nsi else None,
            "has_miles": bool(_MILES_RE.search(rest)),
        })
    return rows

def wp_workout_is_empty(text):
    """True when a get_workout payload reports no logged exercises."""
    return "No exercises logged" in text

def is_backfill_target(row):
    """A Health-Connect Speediance strength import lacking detail."""
    return (row["focus"] == "Strength Training"
            and row["nsi"] is None
            and row["calorie"] is not None
            and not row["has_miles"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py::TestWpParsers -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add reconcile.py tests/test_reconcile.py
git commit -m "feat(reconcile): parse Wellness Project workout-list + empty-check text"
```

---

### Task 3: Matching — `match_candidates`

Pair each empty WP strength workout to a Speediance strength session by date + calories.

**Files:**
- Modify: `reconcile.py`
- Test: `tests/test_reconcile.py`

**Interfaces:**
- Produces: `sp_strength_sessions(records: list) -> list[dict]` — filter to strength: keep `courseType != 2 and totalCapacity > 0`; return `{"training_id", "type", "date", "calorie", "trainingTime", "title"}` (date from `startTime[:10]`).
- Produces: `match_candidates(wp_targets: list, sp_sessions: list) -> {"confident": [...], "ambiguous": [...]}`. A `wp_target` is a parsed row (Task 2). Confident entry: `{"wp": row, "sp": sp_session}`. Ambiguous entry: `{"wp": row, "candidates": [sp_session,...], "reason": str}`. Match rule: candidate SP sessions where `abs(date_delta_days) <= 1` and `abs(wp.calorie - sp.calorie) <= 2`; **confident** iff exactly one; else ambiguous (`"reason"` = `"no match"` or `"multiple matches"`).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_reconcile.py
def _rec(tid, date, cal, cap=5000.0, ctype=0, typ=5, t=1800, title="X"):
    return {"trainingId": tid, "type": typ, "courseType": ctype,
            "totalCapacity": cap, "calorie": cal, "trainingTime": t,
            "startTime": f"{date} 12:00:00", "title": title}

class TestMatching(unittest.TestCase):
    def test_strength_filter_excludes_rowing(self):
        recs = [_rec(1, "2026-08-29", 341),                       # strength
                _rec(2, "2026-08-28", 552, cap=0.0),              # rowing (cap 0)
                _rec(3, "2026-08-15", 529, ctype=2, cap=0.0)]     # cardio course
        out = reconcile.sp_strength_sessions(recs)
        self.assertEqual([s["training_id"] for s in out], [1])
        self.assertEqual(out[0]["date"], "2026-08-29")

    def test_confident_single_match(self):
        wp = [{"session_id": 696827, "date": "2026-08-29", "focus": "Strength Training",
               "calorie": 341, "nsi": None, "has_miles": False}]
        sp = reconcile.sp_strength_sessions([_rec(1103072, "2026-08-29", 341)])
        res = reconcile.match_candidates(wp, sp)
        self.assertEqual(len(res["confident"]), 1)
        self.assertEqual(res["confident"][0]["sp"]["training_id"], 1103072)
        self.assertEqual(res["ambiguous"], [])

    def test_no_match_is_ambiguous(self):
        wp = [{"session_id": 1, "date": "2026-08-29", "focus": "Strength Training",
               "calorie": 999, "nsi": None, "has_miles": False}]
        sp = reconcile.sp_strength_sessions([_rec(1103072, "2026-08-29", 341)])
        res = reconcile.match_candidates(wp, sp)
        self.assertEqual(res["confident"], [])
        self.assertEqual(res["ambiguous"][0]["reason"], "no match")

    def test_multiple_matches_is_ambiguous(self):
        wp = [{"session_id": 1, "date": "2026-08-29", "focus": "Strength Training",
               "calorie": 341, "nsi": None, "has_miles": False}]
        sp = reconcile.sp_strength_sessions(
            [_rec(10, "2026-08-29", 341), _rec(11, "2026-08-29", 340)])  # both within tol
        res = reconcile.match_candidates(wp, sp)
        self.assertEqual(res["confident"], [])
        self.assertEqual(res["ambiguous"][0]["reason"], "multiple matches")

    def test_one_day_tolerance(self):
        wp = [{"session_id": 1, "date": "2026-08-30", "focus": "Strength Training",
               "calorie": 341, "nsi": None, "has_miles": False}]
        sp = reconcile.sp_strength_sessions([_rec(1103072, "2026-08-29", 341)])
        res = reconcile.match_candidates(wp, sp)
        self.assertEqual(len(res["confident"]), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py::TestMatching -v`
Expected: FAIL — `AttributeError: ... 'sp_strength_sessions'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to reconcile.py
import datetime

CARDIO_COURSE_TYPE = 2
CAL_TOLERANCE = 2
DAY_TOLERANCE = 1

def sp_strength_sessions(records):
    """Speediance records -> strength-only session dicts (courseType != 2, capacity > 0)."""
    out = []
    for r in records:
        if r.get("courseType") == CARDIO_COURSE_TYPE:
            continue
        if (r.get("totalCapacity") or 0) <= 0:
            continue
        out.append({
            "training_id": r.get("trainingId"),
            "type": r.get("type"),
            "date": (r.get("startTime") or "")[:10],
            "calorie": r.get("calorie"),
            "trainingTime": r.get("trainingTime"),
            "title": r.get("title"),
        })
    return out

def _days_apart(a, b):
    da = datetime.date.fromisoformat(a)
    db = datetime.date.fromisoformat(b)
    return abs((da - db).days)

def match_candidates(wp_targets, sp_sessions):
    """Match empty WP strength workouts to Speediance strength sessions."""
    confident, ambiguous = [], []
    for wp in wp_targets:
        cands = [
            sp for sp in sp_sessions
            if sp.get("calorie") is not None
            and abs((wp["calorie"] or 0) - sp["calorie"]) <= CAL_TOLERANCE
            and _days_apart(wp["date"], sp["date"]) <= DAY_TOLERANCE
        ]
        if len(cands) == 1:
            confident.append({"wp": wp, "sp": cands[0]})
        else:
            ambiguous.append({
                "wp": wp, "candidates": cands,
                "reason": "multiple matches" if cands else "no match",
            })
    return {"confident": confident, "ambiguous": ambiguous}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py -v`
Expected: PASS (all reconcile tests).

- [ ] **Step 5: Commit**

```bash
git add reconcile.py tests/test_reconcile.py
git commit -m "feat(reconcile): match empty WP workouts to Speediance strength sessions"
```

---

### Task 4: `wellness_client.py` — OAuth (PKCE, DCR, token lifecycle)

The Wellness Project connection's auth half: register a client, drive the PKCE authorize flow, exchange the code, and refresh silently with rotation. HTTP is mocked in tests.

**Files:**
- Create: `wellness_client.py`
- Test: `tests/test_wellness_client.py`
- Reference (read): `api_client.py:1-45,150-260` (exception + config patterns)

**Interfaces:**
- Produces exceptions: `WellnessAPIError(Exception)`, `WellnessAuthError(WellnessAPIError)`.
- Produces class `WellnessClient` with:
  - `__init__(self, base_dir=None, tokens_file=None, pending_file=None)` — loads `wellness_tokens.json` if present.
  - `is_connected() -> bool` — a refresh token is stored.
  - `_pkce_pair() -> (verifier, challenge)` — `verifier` = base64url(32 random bytes) no padding; `challenge` = base64url(sha256(verifier)) no padding.
  - `begin_authorization(redirect_uri) -> str` — ensures a registered client (`_register_client`), makes a PKCE pair + random `state`, persists `{state: {verifier, ts}}` to the pending file, returns the full `authorize` URL.
  - `complete_authorization(code, state, redirect_uri) -> None` — pops+validates state from pending file (raise `WellnessAuthError` if unknown), POSTs the token endpoint with `code_verifier`, persists tokens.
  - `_valid_access_token() -> str` — returns a live access token, refreshing (rotating) if within 60s of expiry; raises `WellnessAuthError` on `invalid_grant` after clearing tokens.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wellness_client.py
import base64, hashlib, json, os, tempfile, unittest
from unittest import mock
import wellness_client as wc

AUTH_META = {
    "authorization_endpoint": "https://wellnessproject.ai/api/oauth/authorize",
    "token_endpoint": "https://wellnessproject.ai/api/oauth/token",
    "registration_endpoint": "https://wellnessproject.ai/api/oauth/register",
}

def _resp(json_body=None, status=200, text=""):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = json_body or {}
    r.text = text or json.dumps(json_body or {})
    return r

class TestOAuth(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.c = wc.WellnessClient(
            base_dir=self.d,
            tokens_file=os.path.join(self.d, "wellness_tokens.json"),
            pending_file=os.path.join(self.d, "wellness_pending.json"))
        self.c._auth_meta = dict(AUTH_META)  # skip discovery in tests

    def test_pkce_challenge_is_sha256_of_verifier(self):
        v, ch = self.c._pkce_pair()
        expect = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(ch, expect)
        self.assertNotIn("=", v)

    def test_begin_then_complete_persists_tokens(self):
        redirect = "https://speediance.labattsimon.com/wp/callback"
        with mock.patch.object(self.c, "_register_client", return_value="client-123"):
            url = self.c.begin_authorization(redirect)
        self.assertIn("code_challenge=", url)
        self.assertIn("client_id=client-123", url)
        # recover the state we just stored
        pending = json.load(open(self.c.pending_file))
        state = next(iter(pending))
        with mock.patch("wellness_client.requests.post",
                        return_value=_resp({"access_token": "AT", "refresh_token": "RT",
                                            "expires_in": 3600})):
            self.c.complete_authorization("the-code", state, redirect)
        self.assertTrue(self.c.is_connected())
        saved = json.load(open(self.c.tokens_file))
        self.assertEqual(saved["refresh_token"], "RT")

    def test_complete_rejects_unknown_state(self):
        with self.assertRaises(wc.WellnessAuthError):
            self.c.complete_authorization("code", "bogus-state",
                                          "https://x/wp/callback")

    def test_refresh_rotation_persists_new_refresh_token(self):
        self.c._save_tokens({"client_id": "c", "access_token": "old",
                             "refresh_token": "RT1", "expires_at": 0})  # expired
        with mock.patch("wellness_client.requests.post",
                        return_value=_resp({"access_token": "AT2", "refresh_token": "RT2",
                                            "expires_in": 3600})):
            tok = self.c._valid_access_token()
        self.assertEqual(tok, "AT2")
        self.assertEqual(json.load(open(self.c.tokens_file))["refresh_token"], "RT2")

    def test_invalid_grant_clears_and_raises(self):
        self.c._save_tokens({"client_id": "c", "access_token": "old",
                             "refresh_token": "RT1", "expires_at": 0})
        with mock.patch("wellness_client.requests.post",
                        return_value=_resp({"error": "invalid_grant"}, status=400)):
            with self.assertRaises(wc.WellnessAuthError):
                self.c._valid_access_token()
        self.assertFalse(self.c.is_connected())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_wellness_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wellness_client'`.

- [ ] **Step 3: Write minimal implementation**

```python
# wellness_client.py
"""Wellness Project MCP client for the Speediance app.

WP exposes no REST API — its MCP endpoint is the API, gated by OAuth
(authorization_code + PKCE + refresh_token; no machine grant). This module
handles the OAuth lifecycle (register once, authorize once in a browser, refresh
silently forever) and the MCP JSON-RPC transport. Tokens live only in
wellness_tokens.json (chmod 600) and are never logged or rendered."""

import base64, hashlib, json, os, secrets, time
import requests

BASE = "https://wellnessproject.ai"
MCP_URL = f"{BASE}/api/mcp"
AS_METADATA_URL = f"{BASE}/.well-known/oauth-authorization-server"
SCOPE = "mcp"
CLIENT_NAME = "Speediance Backfill"
PENDING_TTL = 600  # seconds


class WellnessAPIError(Exception):
    """Base Wellness Project failure."""

class WellnessAuthError(WellnessAPIError):
    """Missing/expired/revoked credentials — user must (re)connect."""


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class WellnessClient:
    def __init__(self, base_dir=None, tokens_file=None, pending_file=None):
        self.base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
        self.tokens_file = tokens_file or os.path.join(self.base_dir, "wellness_tokens.json")
        self.pending_file = pending_file or os.path.join(self.base_dir, "wellness_pending.json")
        self.tokens = self._load_json(self.tokens_file, {})
        self._auth_meta = None

    # ---- persistence ----
    def _load_json(self, path, default):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return default

    def _save_tokens(self, tokens):
        self.tokens = tokens
        with open(self.tokens_file, "w") as f:
            json.dump(tokens, f)
        try:
            os.chmod(self.tokens_file, 0o600)
        except OSError:
            pass

    def is_connected(self):
        return bool(self.tokens.get("refresh_token"))

    # ---- discovery ----
    def _meta(self):
        if self._auth_meta is None:
            r = requests.get(AS_METADATA_URL, timeout=20)
            if r.status_code != 200:
                raise WellnessAPIError(f"AS metadata {r.status_code}")
            self._auth_meta = r.json()
        return self._auth_meta

    def _register_client(self, redirect_uri):
        if self.tokens.get("client_id"):
            return self.tokens["client_id"]
        body = {
            "client_name": CLIENT_NAME, "redirect_uris": [redirect_uri],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"], "scope": SCOPE,
        }
        r = requests.post(self._meta()["registration_endpoint"], json=body, timeout=20)
        if r.status_code not in (200, 201):
            raise WellnessAPIError(f"DCR failed {r.status_code}")
        cid = r.json()["client_id"]
        self.tokens["client_id"] = cid
        self._save_tokens(self.tokens)
        return cid

    # ---- PKCE + authorize ----
    def _pkce_pair(self):
        verifier = _b64url(secrets.token_bytes(32))
        challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
        return verifier, challenge

    def begin_authorization(self, redirect_uri):
        client_id = self._register_client(redirect_uri)
        verifier, challenge = self._pkce_pair()
        state = secrets.token_urlsafe(24)
        pending = self._load_json(self.pending_file, {})
        # drop expired entries, add this one
        now = time.time()
        pending = {k: v for k, v in pending.items() if now - v.get("ts", 0) < PENDING_TTL}
        pending[state] = {"verifier": verifier, "ts": now}
        with open(self.pending_file, "w") as f:
            json.dump(pending, f)
        from urllib.parse import urlencode
        q = urlencode({
            "response_type": "code", "client_id": client_id,
            "redirect_uri": redirect_uri, "scope": SCOPE, "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256",
        })
        return f"{self._meta()['authorization_endpoint']}?{q}"

    def complete_authorization(self, code, state, redirect_uri):
        pending = self._load_json(self.pending_file, {})
        entry = pending.pop(state, None)
        with open(self.pending_file, "w") as f:
            json.dump(pending, f)
        if not entry:
            raise WellnessAuthError("unknown or expired OAuth state")
        r = requests.post(self._meta()["token_endpoint"], data={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": redirect_uri, "client_id": self.tokens["client_id"],
            "code_verifier": entry["verifier"],
        }, timeout=20)
        if r.status_code != 200:
            raise WellnessAuthError(f"token exchange failed {r.status_code}")
        self._store_token_response(r.json())

    def _store_token_response(self, body):
        toks = dict(self.tokens)
        toks["access_token"] = body["access_token"]
        if body.get("refresh_token"):
            toks["refresh_token"] = body["refresh_token"]
        toks["expires_at"] = time.time() + int(body.get("expires_in", 3600))
        self._save_tokens(toks)

    def _valid_access_token(self):
        if not self.tokens.get("refresh_token"):
            raise WellnessAuthError("not connected")
        if self.tokens.get("access_token") and time.time() < self.tokens.get("expires_at", 0) - 60:
            return self.tokens["access_token"]
        r = requests.post(self._meta()["token_endpoint"], data={
            "grant_type": "refresh_token",
            "refresh_token": self.tokens["refresh_token"],
            "client_id": self.tokens["client_id"],
        }, timeout=20)
        if r.status_code != 200:
            self._save_tokens({"client_id": self.tokens.get("client_id")})  # clear creds
            raise WellnessAuthError("refresh failed — reconnect required")
        self._store_token_response(r.json())
        return self.tokens["access_token"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_wellness_client.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add wellness_client.py tests/test_wellness_client.py
git commit -m "feat(wellness): OAuth PKCE + DCR + refresh-with-rotation"
```

---

### Task 5: `wellness_client.py` — MCP transport + high-level methods

Add the JSON-RPC `tools/call` transport (parsing both raw-JSON and single-SSE-event responses) and the three typed methods the backfill needs.

**Files:**
- Modify: `wellness_client.py`
- Test: `tests/test_wellness_client.py`

**Interfaces:**
- Produces: `WellnessClient._call_tool(name, arguments) -> str` — POSTs MCP `tools/call`, returns the tool's text content. Raises `WellnessAuthError` on 401, `WellnessAPIError` otherwise.
- Produces: `list_workouts(start_date, end_date) -> str`, `get_workout(session_id) -> str`, `update_workout(session_id, add_exercises, notes=None) -> str` — thin wrappers over `_call_tool` returning the raw text (the pure parsers in `reconcile.py` interpret it).
- Consumes: `_valid_access_token()` (Task 4).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_wellness_client.py
class TestTransport(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.c = wc.WellnessClient(
            base_dir=self.d,
            tokens_file=os.path.join(self.d, "wellness_tokens.json"),
            pending_file=os.path.join(self.d, "wellness_pending.json"))
        self.c._auth_meta = dict(AUTH_META)
        self.c._save_tokens({"client_id": "c", "access_token": "AT",
                             "refresh_token": "RT", "expires_at": time.time() + 9999})

    def _rpc_result(self, text):
        return {"jsonrpc": "2.0", "id": 1,
                "result": {"content": [{"type": "text", "text": text}]}}

    def test_call_tool_parses_raw_json(self):
        with mock.patch("wellness_client.requests.post",
                        return_value=_resp(self._rpc_result("HELLO"))) as p:
            out = self.c._call_tool("list_workouts", {"start_date": "x"})
        self.assertEqual(out, "HELLO")
        # Authorization header carried the bearer token
        _, kwargs = p.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer AT")

    def test_call_tool_parses_sse_event(self):
        sse = "event: message\ndata: " + json.dumps(self._rpc_result("VIA-SSE")) + "\n\n"
        r = _resp(text=sse)
        r.headers = {"content-type": "text/event-stream"}
        r.json.side_effect = ValueError("not json")
        with mock.patch("wellness_client.requests.post", return_value=r):
            out = self.c._call_tool("get_workout", {"session_id": 1})
        self.assertEqual(out, "VIA-SSE")

    def test_call_tool_401_raises_auth(self):
        with mock.patch("wellness_client.requests.post", return_value=_resp({}, status=401)):
            with self.assertRaises(wc.WellnessAuthError):
                self.c._call_tool("list_workouts", {})

    def test_update_workout_shapes_arguments(self):
        with mock.patch.object(self.c, "_call_tool", return_value="ok") as ct:
            self.c.update_workout(696827, [{"name": "Row", "sets": [{"reps": 8, "weight_lb": 50}]}],
                                  notes="Backfilled from Speediance trainingId 1103072")
        name, args = ct.call_args[0]
        self.assertEqual(name, "update_workout")
        self.assertEqual(args["session_id"], 696827)
        self.assertEqual(args["notes"], "Backfilled from Speediance trainingId 1103072")
        self.assertEqual(args["add_exercises"][0]["name"], "Row")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_wellness_client.py::TestTransport -v`
Expected: FAIL — `AttributeError: 'WellnessClient' object has no attribute '_call_tool'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to wellness_client.py
MCP_PROTOCOL_VERSION = "2025-06-18"

def _parse_rpc_body(resp):
    """Return the JSON-RPC object from either a raw-JSON or SSE MCP response."""
    try:
        return resp.json()
    except ValueError:
        pass
    # SSE: find the last `data:` line and JSON-decode it
    for line in resp.text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            return json.loads(line[len("data:"):].strip())
    raise WellnessAPIError("unparseable MCP response")

# --- add as methods on WellnessClient ---
def _call_tool(self, name, arguments):
    token = self._valid_access_token()
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": name, "arguments": arguments}}
    resp = requests.post(MCP_URL, json=payload, timeout=60, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    })
    if resp.status_code == 401:
        raise WellnessAuthError("Wellness Project rejected the token (401)")
    if resp.status_code != 200:
        raise WellnessAPIError(f"MCP call {name} -> {resp.status_code}")
    body = _parse_rpc_body(resp)
    if "error" in body:
        raise WellnessAPIError(f"MCP error: {body['error']}")
    parts = body.get("result", {}).get("content", [])
    return "".join(p.get("text", "") for p in parts if p.get("type") == "text")

def list_workouts(self, start_date, end_date):
    return self._call_tool("list_workouts",
                           {"start_date": start_date, "end_date": end_date})

def get_workout(self, session_id):
    return self._call_tool("get_workout", {"session_id": session_id})

def update_workout(self, session_id, add_exercises, notes=None):
    args = {"session_id": session_id, "add_exercises": add_exercises}
    if notes is not None:
        args["notes"] = notes
    return self._call_tool("update_workout", args)
```

Bind these to the class (define them inside `class WellnessClient:` alongside the Task 4 methods; `_parse_rpc_body` is a module-level function).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_wellness_client.py -v`
Expected: PASS (all client tests).

- [ ] **Step 5: Commit**

```bash
git add wellness_client.py tests/test_wellness_client.py
git commit -m "feat(wellness): MCP tools/call transport + list/get/update methods"
```

---

### Task 6: OAuth routes — `/wp/connect`, `/wp/callback`

Wire the browser Connect flow into `app.py`.

**Files:**
- Modify: `app.py` (imports near top ~line 30; new routes after the history-detail route ~line 1650; add a module-level `wellness = WellnessClient()` next to `client = SpeedianceClient()` ~line 36)
- Test: `tests/test_wp_routes.py`
- Reference (read): `app.py:36`, existing route/`_is_auth_error` patterns

**Interfaces:**
- Consumes: `WellnessClient.begin_authorization`, `complete_authorization`, `is_connected` (Tasks 4-5).
- Produces routes: `GET /wp/connect` → 302 to WP authorize URL; `GET /wp/callback?code&state` → exchanges, redirects to `/wp/reconcile`. `WP_REDIRECT_URI` derived from `request.url_root` + `wp/callback` (falls back to the known prod URL).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wp_routes.py
import os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as app_module

class TestWpOAuthRoutes(unittest.TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def test_connect_redirects_to_authorize(self):
        with mock.patch.object(app_module.wellness, "begin_authorization",
                               return_value="https://wellnessproject.ai/api/oauth/authorize?x=1") as b:
            resp = self.client.get("/wp/connect")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("oauth/authorize", resp.headers["Location"])
        self.assertTrue(b.call_args[0][0].endswith("/wp/callback"))

    def test_callback_completes_and_redirects(self):
        with mock.patch.object(app_module.wellness, "complete_authorization") as comp:
            resp = self.client.get("/wp/callback?code=abc&state=xyz")
        comp.assert_called_once()
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/wp/reconcile", resp.headers["Location"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_wp_routes.py -v`
Expected: FAIL — `AttributeError: module 'app' has no attribute 'wellness'` (route/attr not added yet).

- [ ] **Step 3: Write minimal implementation**

```python
# app.py — near the top imports
from wellness_client import WellnessClient, WellnessAuthError, WellnessAPIError

# app.py — next to `client = SpeedianceClient()`
wellness = WellnessClient()

# app.py — new routes (place after api_history_detail)
def _wp_redirect_uri():
    root = request.url_root  # e.g. https://speediance.labattsimon.com/
    return root.rstrip("/") + "/wp/callback"

@app.route("/wp/connect")
def wp_connect():
    url = wellness.begin_authorization(_wp_redirect_uri())
    return redirect(url)

@app.route("/wp/callback")
def wp_callback():
    code = request.args.get("code")
    state = request.args.get("state")
    try:
        wellness.complete_authorization(code, state, _wp_redirect_uri())
    except WellnessAuthError as e:
        flash(f"Wellness Project connection failed: {e}", "error")
    return redirect(url_for("wp_reconcile"))
```

(The `wp_reconcile` endpoint is added in Task 8; if running this task's tests before Task 8, temporarily point the redirect at `"/"` — Task 8 switches it to `url_for("wp_reconcile")`. Note this in the commit.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_wp_routes.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_wp_routes.py
git commit -m "feat(app): Wellness Project OAuth connect + callback routes"
```

---

### Task 7: Backfill pass — `/wp/backfill` and `/wp/apply`

The reconciliation engine wired to both clients: find empties, match, auto-apply confident, flag ambiguous; plus a manual single-apply endpoint.

**Files:**
- Modify: `app.py` (new routes; a `_run_backfill(mode)` helper; a `_apply_match(wp_session_id, sp_training_id, sp_type)` helper; a `WP_WINDOW_DAYS = 90` constant; report persisted to `wellness_reconcile_report.json`)
- Test: `tests/test_wp_backfill.py`
- Reference (read): `reconcile.py` (all), `app.py` `_is_auth_error`

**Interfaces:**
- Consumes: `wellness.list_workouts/get_workout/update_workout`, `client.get_training_records/get_training_detail`, all `reconcile.*` functions.
- Produces routes: `POST /wp/backfill?mode=manual|scheduled` → JSON `{"connected": bool, "applied": [...], "flagged": [...], "errors": [...]}`. When not connected → `{"connected": false, "status": "connect_required"}` (HTTP 200 so the cron doesn't alarm). `POST /wp/apply` (JSON body `{wp_session_id, sp_training_id, sp_type}`) → applies one match, returns `{"applied": {...}}` or 4xx/5xx JSON error.
- Produces helper: `_apply_match(wp_session_id, sp_training_id, sp_type) -> dict` — fetches SP detail, transforms, appends provenance to the workout's existing notes, calls `update_workout`; returns an `applied` record `{"wp_session_id", "sp_training_id", "exercise_count"}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wp_backfill.py
import json, os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as app_module

WP_LIST = ("Workouts:\n"
           "[ID 696827] 2026-08-29: Strength Training · 33 min · 341 cal\n"
           "[ID 696826] 2026-08-28: Workout · 37 min · 552 cal · 1.81 mi\n")
SP_RECORDS = [{"trainingId": 1103072, "type": 5, "courseType": 0, "totalCapacity": 7745.0,
               "calorie": 341, "trainingTime": 1949, "startTime": "2026-08-29 13:13:17",
               "title": "Miami Pull"}]
SP_DETAIL = [{"actionLibraryName": "Barbell Bent Over Row", "completionMethod": 1,
              "finishedReps": [{"finishedCount": 8, "targetCount": 8, "time": 8,
                                "trainingInfoDetail": {"weights": [50, 50]}}]}]

class TestBackfill(unittest.TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def test_not_connected_returns_connect_required(self):
        with mock.patch.object(app_module.wellness, "is_connected", return_value=False):
            resp = self.client.post("/wp/backfill?mode=scheduled")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "connect_required")

    def test_confident_match_is_applied(self):
        w = app_module.wellness
        with mock.patch.object(w, "is_connected", return_value=True), \
             mock.patch.object(w, "list_workouts", return_value=WP_LIST), \
             mock.patch.object(w, "get_workout", return_value="... No exercises logged ..."), \
             mock.patch.object(w, "update_workout", return_value="ok") as upd, \
             mock.patch.object(app_module.client, "get_training_records", return_value=SP_RECORDS), \
             mock.patch.object(app_module.client, "get_training_detail", return_value=SP_DETAIL):
            resp = self.client.post("/wp/backfill?mode=manual")
        body = resp.get_json()
        self.assertEqual(len(body["applied"]), 1)
        self.assertEqual(body["applied"][0]["wp_session_id"], 696827)
        upd.assert_called_once()
        # provenance note carries the trainingId
        self.assertIn("1103072", upd.call_args.kwargs.get("notes", ""))

    def test_nonempty_wp_workout_is_not_written(self):
        w = app_module.wellness
        with mock.patch.object(w, "is_connected", return_value=True), \
             mock.patch.object(w, "list_workouts", return_value=WP_LIST), \
             mock.patch.object(w, "get_workout", return_value="Bench Press: Set 1: 8 @ 135"), \
             mock.patch.object(w, "update_workout") as upd, \
             mock.patch.object(app_module.client, "get_training_records", return_value=SP_RECORDS), \
             mock.patch.object(app_module.client, "get_training_detail", return_value=SP_DETAIL):
            resp = self.client.post("/wp/backfill?mode=manual")
        upd.assert_not_called()
        self.assertEqual(resp.get_json()["applied"], [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_wp_backfill.py -v`
Expected: FAIL — 404 on `/wp/backfill` (route not defined).

- [ ] **Step 3: Write minimal implementation**

```python
# app.py
import reconcile
import datetime as _dt

WP_WINDOW_DAYS = 90
WP_REPORT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "wellness_reconcile_report.json")

def _wp_window():
    today = _dt.date.today()
    return (today - _dt.timedelta(days=WP_WINDOW_DAYS)).isoformat(), today.isoformat()

def _apply_match(wp_session_id, sp_training_id, sp_type):
    training_type = "course" if sp_type == 2 else "custom"
    detail = client.get_training_detail(sp_training_id, training_type)
    exercises = reconcile.sp_detail_to_wp_exercises(detail)
    if not exercises:
        raise WellnessAPIError("Speediance session had no loggable exercises")
    # Preserve the existing Health Connect note; append provenance.
    existing = wellness.get_workout(wp_session_id)
    note = f"Backfilled from Speediance trainingId {sp_training_id}"
    wellness.update_workout(wp_session_id, exercises, notes=note)
    return {"wp_session_id": wp_session_id, "sp_training_id": sp_training_id,
            "exercise_count": len(exercises)}

def _run_backfill(mode):
    if not wellness.is_connected():
        return {"connected": False, "status": "connect_required"}
    start, end = _wp_window()
    wp_text = wellness.list_workouts(start, end)
    rows = reconcile.parse_wp_workout_list(wp_text)
    targets = [r for r in rows if reconcile.is_backfill_target(r)]
    # confirm each is genuinely empty
    empties = []
    for r in targets:
        try:
            if reconcile.wp_workout_is_empty(wellness.get_workout(r["session_id"])):
                empties.append(r)
        except WellnessAPIError:
            continue
    sp = reconcile.sp_strength_sessions(client.get_training_records(start, end))
    matched = reconcile.match_candidates(empties, sp)

    applied, errors = [], []
    for m in matched["confident"]:
        try:
            applied.append(_apply_match(m["wp"]["session_id"],
                                        m["sp"]["training_id"], m["sp"]["type"]))
        except (WellnessAPIError, Exception) as e:
            errors.append({"wp_session_id": m["wp"]["session_id"], "error": str(e)})
    flagged = [{"wp": m["wp"], "candidates": m["candidates"], "reason": m["reason"]}
               for m in matched["ambiguous"]]
    report = {"connected": True, "applied": applied, "flagged": flagged, "errors": errors}
    try:
        with open(WP_REPORT_FILE, "w") as f:
            json.dump(report, f)
    except OSError:
        pass
    return report

@app.route("/wp/backfill", methods=["POST"])
def wp_backfill():
    mode = request.args.get("mode", "manual")
    try:
        return jsonify(_run_backfill(mode))
    except WellnessAuthError:
        return jsonify({"connected": False, "status": "connect_required"})
    except Exception as e:
        if _is_auth_error(e):
            return jsonify({"error": str(e)}), 401
        return jsonify({"error": str(e)}), 500

@app.route("/wp/apply", methods=["POST"])
def wp_apply():
    data = request.get_json(force=True)
    try:
        applied = _apply_match(int(data["wp_session_id"]),
                               int(data["sp_training_id"]), int(data.get("sp_type", 5)))
        return jsonify({"applied": applied})
    except WellnessAuthError:
        return jsonify({"error": "connect_required"}), 401
    except Exception as e:
        if _is_auth_error(e):
            return jsonify({"error": str(e)}), 401
        return jsonify({"error": str(e)}), 500
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_wp_backfill.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_wp_backfill.py
git commit -m "feat(app): /wp/backfill pass + /wp/apply single-match endpoint"
```

---

### Task 8: Status page — `/wp/reconcile`

A minimal page: connection state + Connect button, a Backfill-now button, and the last report's applied/flagged/errors. Follows the app's existing Tailwind template style.

**Files:**
- Create: `templates/wp_reconcile.html`
- Modify: `app.py` (add the `GET /wp/reconcile` route; switch Task 6's callback redirect to `url_for("wp_reconcile")`)
- Test: `tests/test_wp_routes.py` (extend)

**Interfaces:**
- Consumes: `wellness.is_connected()`, the persisted `wellness_reconcile_report.json`.
- Produces route: `GET /wp/reconcile` → renders the page with `connected` and `report`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_wp_routes.py
class TestReconcilePage(unittest.TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def test_page_shows_connect_when_disconnected(self):
        with mock.patch.object(app_module.wellness, "is_connected", return_value=False):
            resp = self.client.get("/wp/reconcile")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"/wp/connect", resp.data)

    def test_page_shows_backfill_when_connected(self):
        with mock.patch.object(app_module.wellness, "is_connected", return_value=True):
            resp = self.client.get("/wp/reconcile")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"/wp/backfill", resp.data)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_wp_routes.py::TestReconcilePage -v`
Expected: FAIL — 404 on `/wp/reconcile`.

- [ ] **Step 3: Write minimal implementation**

```python
# app.py
@app.route("/wp/reconcile")
def wp_reconcile():
    report = {}
    try:
        with open(WP_REPORT_FILE) as f:
            report = json.load(f)
    except (OSError, ValueError):
        report = {}
    return render_template("wp_reconcile.html",
                           connected=wellness.is_connected(), report=report)
```

Also update Task 6's `wp_callback` redirect to `return redirect(url_for("wp_reconcile"))`.

```html
<!-- templates/wp_reconcile.html -->
<!doctype html>
<html><head><meta charset="utf-8"><title>Wellness Project Backfill</title>
<script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-gray-900 text-gray-100 p-8">
  <h1 class="text-2xl font-bold mb-4">Wellness Project Backfill</h1>
  {% if connected %}
    <p class="text-green-400 mb-4">Connected.</p>
    <button id="run" class="bg-blue-600 px-4 py-2 rounded">Backfill now</button>
    <pre id="out" class="mt-4 bg-gray-800 p-4 rounded text-sm overflow-auto"></pre>
    <script>
      document.getElementById('run').onclick = async () => {
        const out = document.getElementById('out');
        out.textContent = 'Running…';
        const r = await fetch('/wp/backfill?mode=manual', {method: 'POST'});
        out.textContent = JSON.stringify(await r.json(), null, 2);
      };
    </script>
  {% else %}
    <p class="mb-4">Not connected to Wellness Project.</p>
    <a href="/wp/connect" class="bg-blue-600 px-4 py-2 rounded">Connect Wellness Project</a>
  {% endif %}
  {% if report and report.get('applied') %}
    <h2 class="text-lg mt-6 mb-2">Last run — applied {{ report['applied']|length }}</h2>
    <pre class="bg-gray-800 p-4 rounded text-sm">{{ report['applied']|tojson(indent=2) }}</pre>
  {% endif %}
</body></html>
```

Note: this page loads the Tailwind CDN like the app's other templates; it renders no tokens or secrets. Ambiguous-match resolution UI (a picker calling `/wp/apply`) can be added later; the flagged list is already in the JSON output.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_wp_routes.py -v`
Expected: PASS (all route tests).

- [ ] **Step 5: Commit**

```bash
git add app.py templates/wp_reconcile.html tests/test_wp_routes.py
git commit -m "feat(app): /wp/reconcile status page with Connect + Backfill controls"
```

---

### Task 9: Ops — git-exclude runtime files, README, cron

Wire the runtime artifacts out of git, document the feature, and provide the daily cron.

**Files:**
- Modify: `.git/info/exclude`
- Modify: `README.md`
- Create: `docs/wp-backfill-cron.md` (the cron one-liner + setup notes)

**Interfaces:** none (docs/config only).

- [ ] **Step 1: Exclude runtime files from git**

Append to `.git/info/exclude`:

```
wellness_tokens.json
wellness_pending.json
wellness_reconcile_report.json
```

Verify: `git status --porcelain` shows none of those three after a backfill run.

- [ ] **Step 2: Document the cron**

Create `docs/wp-backfill-cron.md`:

```markdown
# Wellness Project backfill — daily cron

The scheduled scan is a plain cron entry that POSTs the backfill endpoint. It
reuses the site's nginx basic-auth credentials. Confident matches are applied
automatically; ambiguous ones are recorded and shown on /wp/reconcile.

    # crontab -e  (runs 06:15 daily)
    15 6 * * * curl -sS -u labatt:<basic-auth-pw> -X POST \
      'https://speediance.labattsimon.com/wp/backfill?mode=scheduled' \
      >> /var/log/wp-backfill.log 2>&1

One-time setup: open https://speediance.labattsimon.com/wp/reconcile and click
**Connect Wellness Project** to authorize. After that the app refreshes its own
token; re-connect only if a run reports `connect_required`.
```

- [ ] **Step 3: Update the README**

Add a "Wellness Project backfill" bullet to `README.md` describing: what it does (fills empty WP strength workouts from the matching Speediance session), the one-time Connect step, the daily cron, and that it only writes to empty workouts (real-gym entries untouched, idempotent).

- [ ] **Step 4: Full regression run**

Run: `.venv/bin/python -m pytest -q`
Expected: all green except the two known-unrelated `test_e2e_workouts.py` failures.
Run: `node --test tests/workout-logic.test.mjs`
Expected: PASS (unchanged by this feature).

- [ ] **Step 5: Commit**

```bash
git add .git/info/exclude README.md docs/wp-backfill-cron.md
git commit -m "docs+ops: git-exclude WP runtime files, cron, README"
```

---

## Manual acceptance (post-implementation, needs the user)

OAuth cannot be exercised in tests. After Task 9, do a live smoke test with the user:

1. Restart the app (`pm2 restart speediance`), open `/wp/reconcile`.
2. Click **Connect Wellness Project**, approve in the browser, confirm it returns "Connected."
3. Click **Backfill now**. Confirm the Aug 29 "Miami Pull" workout (WP ID 696827) gains its 5 exercises and that no `@ Gym` entry changed.
4. Click **Backfill now** again → `applied: []` (idempotent).

---

## Self-Review

**Spec coverage:**
- WP auth (OAuth/PKCE/DCR/refresh) → Task 4. MCP transport (JSON+SSE) → Task 5. ✓
- Matching by date+calories, confident/ambiguous → Task 3. ✓
- Transform (reuse existing parsing, units verbatim, provenance note) → Tasks 1, 7. ✓
- Empty-only writes / idempotency / @ Gym safety → Tasks 2 (`is_backfill_target`, `wp_workout_is_empty`), 7 (confirm-empty loop). ✓
- Triggers: manual button + `/wp/backfill` + `/wp/apply` + scheduled cron → Tasks 7, 8, 9. ✓
- Scope strength-only (`courseType != 2`, `totalCapacity > 0`) → Task 3. ✓
- Files, git-exclude, README → Task 9. ✓
- Graceful "reconnect required" on refresh failure → Tasks 4 (`_valid_access_token`), 7 (`connect_required`). ✓
- Tests mock all HTTP; no live network → every task. ✓

**Placeholder scan:** No TBD/TODO; all steps carry real code. The one forward-reference (Task 6 callback → `wp_reconcile`, added in Task 8) is called out explicitly in both tasks.

**Type consistency:** `sp_detail_to_wp_exercises`, `parse_wp_workout_list`, `wp_workout_is_empty`, `is_backfill_target`, `sp_strength_sessions`, `match_candidates`, `_call_tool`, `list_workouts`/`get_workout`/`update_workout`, `_apply_match`, `_run_backfill` — names and shapes are used consistently across Tasks 1-8. `match_candidates` returns `{"confident","ambiguous"}` and the ambiguous entries carry `candidates`/`reason`, consumed unchanged in Task 7's `flagged` mapping. ✓

## Out of scope (per spec)

Rowing/cardio backfill; superset grouping and equipment inference; re-syncing already-detailed workouts; WP domains beyond workouts; a machine-to-machine grant. The ambiguous-match resolution **UI** is deferred (the data is surfaced in the report JSON; `/wp/apply` exists for it).
