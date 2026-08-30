"""Pure, network-free reconciliation logic: parse Wellness Project tool text,
match empty WP workouts to Speediance strength sessions, and transform Speediance
session detail into WP add_exercises payloads. No I/O, no Flask, no requests —
everything here is unit-tested against live-captured fixtures."""

import re
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
            if kind == "reps":
                # For reps, skip if done == 0
                if s.get("skipped"):
                    continue
                load = s.get("load") or 0
                if load > 0:
                    sets.append({"reps": s["done"], "weight_lb": float(load)})
                else:
                    sets.append({"reps": s["done"], "is_bodyweight": True})
            else:  # timed or level
                # For timed/level, skip if seconds == 0
                if (s.get("seconds") or 0) == 0:
                    continue
                st = {"hold_length_sec": int(s.get("seconds") or 0),
                      "is_bodyweight": True}
                if kind == "level":
                    st["notes"] = "Vita level"
                sets.append(st)
        if not sets:
            continue
        out.append({"name": ex["name"], "slot_type": "working", "sets": sets})
    return out


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
