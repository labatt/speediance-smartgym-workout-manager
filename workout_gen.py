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

FEEL = {"too_easy": "too easy", "easy": "easy", "right": "just right",
        "hard": "hard", "too_hard": "too hard", None: "not rated"}


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
            if not any(not s.get("skipped") for s in ex.get("sets", [])):
                continue   # an all-skipped exercise isn't "performance" — omit it
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


def build_generation_system_prompt(exercises, unit_label, has_recent=False, has_refs=False):
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
        "WEIGHT — REQUIRED on every rep-based set, and it must be greater than 0. NEVER write \"weight\": 0.",
        f"- presetId -1: \"weight\" is the ABSOLUTE load in {unit_label} (e.g. 40). Configured for {unit_label}; "
        f"the value is stored verbatim — nothing converts it, so do NOT prescribe in {other}.",
        "- presetId 1, 3 or 5: \"weight\" is the RM VALUE — the rep-max within that preset's range (e.g. a 6RM "
        "for Strength), a small integer, NOT an absolute load and NOT 0. Keep about one rep in reserve.",
        "If you are unsure of a load, prefer presetId -1 with a sensible absolute weight rather than leaving it 0.",
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
    if has_refs:
        p += [
            "",
            "REFERENCE WORKOUTS are provided in the user prompt as structure to adapt: reuse their "
            "exercises where they fit the request, but tailor sets and loads to the request and the "
            "athlete's recent performance rather than copying them verbatim.",
        ]
    p += [
        "",
        "OUTPUT FORMAT — output ONLY a JSON object, no prose:",
        '{ "name": "Workout Name", "exercises": [',
        '  { "id": 1001, "presetId": -1, "sets": [ { "reps": 10, "weight": 40, "mode": 1, "rest": 60 } ] },',
        '  { "id": 1002, "presetId": 5,  "sets": [ { "reps": 6,  "weight": 7,  "mode": 1, "rest": 90 } ] }',
        "] }",
        "In the first line weight 40 is an absolute load; in the second, presetId 5 with weight 7 means a 7RM. "
        "Every rep-based set needs a weight greater than 0.",
    ]
    if has_timed:
        p.append("For a normal exercise omit \"unit\" (defaults to reps). For [TIMED]/[TIMED+LEVEL], \"reps\" is seconds "
                 "and \"unit\":\"sec\" is required.")
    else:
        p.append("For all exercises, omit \"unit\" (defaults to reps).")
    return "\n".join(p)


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
