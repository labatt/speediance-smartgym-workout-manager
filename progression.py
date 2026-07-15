"""Turn a completed session into a structured snapshot for comparison over time.

This deliberately does NOT hand down "add weight / reduce" verdicts. A session on 2026-07-14
proved why: power-fade — the obvious metric — called a Standing Leg Curl "grinding" (it was
easy; one explosive peak rep skewed the maths) and a Hip Abduction "too light" (it was hard;
a small stabiliser burns without ever producing high wattage). A single sensor-derived number
cannot see effort, and a rule built on it is confidently wrong.

So this module extracts *facts* — completion, per-set load or level, the device's own scores,
and raw power/speed/ROM trends clearly labelled as trends — and pairs them with the athlete's
own subjective rating, which is the ground truth the sensors miss. Interpretation happens
later, over several sessions, against that felt rating. Everything here is pure and testable;
no I/O, no API, no clock.
"""

import statistics

# trainingPartId2 -> body region. Present on every detail entry (the finer
# mainMuscleGroupName needs a library join and is added opportunistically upstream).
REGION_NAMES = {
    11: "Chest",
    12: "Shoulders",
    13: "Back",
    14: "Glutes",
    15: "Legs",
    16: "Arms",
    17: "Core",
}

# The optional subjective scale. Ordered easy -> hard; a rating is never required.
FEEL_SCALE = ["too_easy", "easy", "right", "hard", "too_hard"]


def _nums(arr):
    return [x for x in (arr or []) if isinstance(x, (int, float))]


def _side_series(detail, name):
    """Ragged-safe: the cable(s) this set actually used, concatenated.

    The per-rep arrays are ragged and a set uses only the worked side(s), so we take
    whichever is populated rather than zipping left against right by index.
    """
    left = _nums(detail.get("left" + name))
    right = _nums(detail.get("right" + name))
    if left and not right:
        return left
    if right and not left:
        return right
    return left + right


def exercise_kind(ex):
    """'reps', 'timed', or 'level' — decides what a set's numbers mean."""
    cm = ex.get("completionMethod")
    if cm == 5 or ex.get("dataStatType") == 6:
        return "level"          # Vita: intensity is a level, goal is seconds
    if cm in (0, 2):
        return "timed"          # duration goal, no load
    return "reps"


def _set_facts(kind, s):
    detail = s.get("trainingInfoDetail") or {}
    done = s.get("finishedCount") or 0
    target = s.get("targetCount") or 0
    fact = {
        "done": done,
        "target": target,
        "complete": done >= target and done > 0,
        "skipped": done == 0,
    }

    if kind == "level":
        # For Vita the "weight" the user set is the level; done/target are reps in a window.
        levels = _nums(detail.get("weights"))  # 0s here; level lives elsewhere in save,
        fact["seconds"] = s.get("time") or 0    # but the read side exposes time + counts.
        fact["load"] = None
        return fact

    if kind == "timed":
        fact["seconds"] = s.get("time") or 0
        fact["load"] = None
        return fact

    # reps
    weights = _nums(detail.get("weights"))
    fact["load"] = weights[0] if weights else 0

    watts = [w for w in _side_series(detail, "Watts") if w > 0]
    if len(watts) >= 4:
        peak = max(watts)
        last2 = statistics.mean(watts[-2:])
        # Peak -> last, NOT first -> last: rep 1 is an ~80% ramp-in on this athlete, so a
        # first->last measure reads a warming-up set as getting *stronger*. Even peak->last
        # is only a trend, never a verdict — see the module docstring.
        fact["power_trend_pct"] = round((peak - last2) / peak * 100, 1) if peak else None
        fact["power_peak"] = round(peak, 1)
    else:
        fact["power_trend_pct"] = None
        fact["power_peak"] = None

    roms = [a for a in _side_series(detail, "Amplitudes") if a > 0]
    fact["rom"] = round(statistics.mean(roms), 3) if roms else None
    return fact


def analyze_exercise(ex):
    kind = exercise_kind(ex)
    sets = [_set_facts(kind, s) for s in (ex.get("finishedReps") or [])]
    worked = [s for s in sets if not s["skipped"]]

    loads = [s["load"] for s in worked if s.get("load")]
    top_load = max(loads) if loads else None

    # ROM change across worked sets, a genuine form signal (shrinking range = compensating).
    roms = [s["rom"] for s in worked if s.get("rom")]
    rom_change_pct = None
    if len(roms) >= 2 and roms[0]:
        rom_change_pct = round((roms[-1] - roms[0]) / roms[0] * 100, 1)

    return {
        "name": ex.get("actionLibraryName"),
        "group": ex.get("actionLibraryGroupId"),
        "region": REGION_NAMES.get(ex.get("trainingPartId2"), "Other"),
        "muscle": ex.get("mainMuscleGroupName"),  # filled by a library join upstream if present
        "kind": kind,
        "sets": sets,
        "sets_done": len(worked),
        "sets_total": len(sets),
        "all_complete": bool(worked) and all(s["complete"] for s in worked),
        "any_missed": any(not s["complete"] for s in worked),
        "top_load": top_load,
        "rom_change_pct": rom_change_pct,
        "scores": {
            "force_control": ex.get("forceControlScore"),
            "amplitude_stable": ex.get("amplitudeStableScore"),
            "bilateral_balance": ex.get("bilateralBalanceScore"),
            "rating": ex.get("actionRating"),
        },
    }


def analyze_session(detail):
    """Whole-session snapshot: per-exercise facts plus a per-region rollup. No verdicts."""
    exercises = [analyze_exercise(ex) for ex in (detail or [])]

    groups = {}
    for ex in exercises:
        g = groups.setdefault(ex["region"], {
            "region": ex["region"], "exercises": [], "complete": 0, "missed": 0,
        })
        g["exercises"].append(ex["name"])
        if ex["all_complete"]:
            g["complete"] += 1
        if ex["any_missed"]:
            g["missed"] += 1

    return {"exercises": exercises, "groups": list(groups.values())}


def compare_exercise(current, previous):
    """Line up one exercise against its last outing. Facts only; no advice."""
    if not previous:
        return {"name": current["name"], "status": "first_time"}
    return {
        "name": current["name"],
        "top_load": current.get("top_load"),
        "prev_top_load": previous.get("top_load"),
        "load_delta": (current.get("top_load") or 0) - (previous.get("top_load") or 0)
        if current.get("top_load") is not None and previous.get("top_load") is not None else None,
        "sets_done": current.get("sets_done"),
        "prev_sets_done": previous.get("sets_done"),
        "all_complete": current.get("all_complete"),
        "prev_all_complete": previous.get("all_complete"),
    }


def compare_sessions(current, previous):
    prev_by_name = {e["name"]: e for e in (previous or {}).get("exercises", [])}
    return [compare_exercise(e, prev_by_name.get(e["name"])) for e in current.get("exercises", [])]
