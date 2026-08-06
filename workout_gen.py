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
    ]
    if has_timed:
        p.append("For a normal exercise omit \"unit\" (defaults to reps). For [TIMED]/[TIMED+LEVEL], \"reps\" is seconds "
                 "and \"unit\":\"sec\" is required.")
    else:
        p.append("For all exercises, omit \"unit\" (defaults to reps).")
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
