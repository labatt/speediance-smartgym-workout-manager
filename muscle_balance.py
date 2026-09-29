"""Per-muscle volume and training balance. No I/O, no Flask — unit-tested.

Every movement in the Speediance library names the muscles it works: a main list and
an assisting list. This module spreads each session's volume over those muscles and
reports the balance — which muscles carried the work, push against pull, upper against
lower, and what hasn't been trained lately.

Two things are deliberate and must stay visible wherever these numbers are shown:

* A main muscle takes the exercise's FULL volume and an assisting muscle HALF, so the
  attributed total exceeds the weight actually lifted. These are shares of attention,
  not a decomposition of load.
* Only reps-and-weight work carries volume. Timed and level work (Vita, planks, rowing)
  has no weight to multiply and is counted separately as `unweightedExercises`, never
  silently as zero.

Twin of speediance-mcp's speediance/muscles.py — separate implementations on purpose so
neither app depends on the other; keep them in step.
"""

MAIN_SHARE = 1.0
ASSIST_SHARE = 0.5

# The library's own body-part ids (`trainingPartId2`). 18 is its whole-body catch-all.
BODY_PARTS = {11: "Chest", 12: "Shoulders", 13: "Back", 14: "Glutes",
              15: "Legs", 16: "Arms", 17: "Core", 18: "Full body"}

# Movement-chain classification. "Full Body" belongs to neither chain: counting it as
# both would flatter every ratio, and picking one would be arbitrary.
PUSH_MUSCLES = {"pecs", "front delts", "side delts", "triceps"}
PULL_MUSCLES = {"lats", "traps", "rear delts", "biceps", "forearms", "back extensors"}
UPPER_MUSCLES = PUSH_MUSCLES | PULL_MUSCLES
LOWER_MUSCLES = {"glutes", "quads", "hamstrings", "calves", "adductors"}


def _key(name):
    return str(name or "").strip().lower()


def _nums(value):
    """Coerce a list or CSV of numbers, skipping anything unparseable."""
    if isinstance(value, str):
        value = value.split(",")
    out = []
    for item in value or []:
        try:
            out.append(float(item))
        except (TypeError, ValueError):
            continue
    return out


def muscle_index(library):
    """groupId -> {'main': [...], 'assist': [...], 'part': name} from the cached catalog."""
    index = {}
    for raw in library or []:
        group_id = raw.get("id")
        if group_id is None:
            continue
        main = [m.get("muscleGroupName") for m in (raw.get("mainMuscleGroupList") or [])
                if m.get("muscleGroupName")]
        assist = [m.get("muscleGroupName") for m in (raw.get("auxiliaryMuscleGroupList") or [])
                  if m.get("muscleGroupName")]
        index[int(group_id)] = {"main": main,
                                "assist": [a for a in assist if a not in main],
                                "part": BODY_PARTS.get(raw.get("trainingPartId2"))}
    return index


def set_load(detail, side):
    """The resistance of one set: side arrays first, `weights` only as a fallback.

    A pinned side (1/2) is a unilateral set — that side's max alone. Otherwise, when both
    cables are populated, BOTH carry the load, so the set's resistance is
    max(left) + max(right). Taking one side's max would halve every barbell number.
    Never zip the arrays by index: they are independent, ragged telemetry series.
    """
    left, right = _nums(detail.get("leftWeights")), _nums(detail.get("rightWeights"))
    if side == 1 and left:
        return max(left)
    if side == 2 and right:
        return max(right)
    if left and right:
        return max(left) + max(right)
    if left or right:
        return max(left or right)
    weights = _nums(detail.get("weights"))
    return max(weights) if weights else None


def exercise_volume(exercise):
    """reps x load, summed over the sets that were actually worked."""
    total = 0.0
    for st in exercise.get("finishedReps") or []:
        reps = st.get("finishedCount") or 0
        load = set_load(st.get("trainingInfoDetail") or {}, st.get("leftRight") or None)
        if reps and load:
            total += float(reps) * float(load)
    return round(total, 1)


def attribute(exercises, index):
    """Spread each exercise's volume over the muscles it works."""
    by_muscle, by_part, unknown, unweighted = {}, {}, [], 0
    for exercise in exercises or []:
        group_id = exercise.get("actionLibraryGroupId")
        entry = index.get(int(group_id)) if group_id is not None else None
        if entry is None:
            name = exercise.get("actionLibraryName")
            if name and name not in unknown:
                unknown.append(name)
            continue
        volume = exercise_volume(exercise)
        if volume <= 0:
            unweighted += 1
            continue
        for muscle in entry["main"]:
            by_muscle[muscle] = by_muscle.get(muscle, 0.0) + volume * MAIN_SHARE
        for muscle in entry["assist"]:
            by_muscle[muscle] = by_muscle.get(muscle, 0.0) + volume * ASSIST_SHARE
        if entry["part"]:
            by_part[entry["part"]] = by_part.get(entry["part"], 0.0) + volume
    return {"byMuscle": {k: round(v, 1) for k, v in by_muscle.items()},
            "byBodyPart": {k: round(v, 1) for k, v in by_part.items()},
            "unweightedExercises": unweighted,
            "exercisesNotInLibrary": unknown}


def _sum(by_muscle, names):
    return sum(v for k, v in by_muscle.items() if _key(k) in names)


def _ratio(left, right):
    return round(left / right, 2) if right > 0 else None


def ratios(by_muscle):
    """Push:pull and upper:lower, with the volumes behind them."""
    push, pull = _sum(by_muscle, PUSH_MUSCLES), _sum(by_muscle, PULL_MUSCLES)
    upper, lower = _sum(by_muscle, UPPER_MUSCLES), _sum(by_muscle, LOWER_MUSCLES)
    return {"push": round(push, 1), "pull": round(pull, 1), "pushPull": _ratio(push, pull),
            "upper": round(upper, 1), "lower": round(lower, 1), "upperLower": _ratio(upper, lower)}


def untrained(by_muscle, index):
    """Main muscles the library knows that took no volume. A muscle that only ever
    assists is excluded — listing it would be an artefact of the catalog."""
    known = set()
    for entry in index.values():
        known.update(entry["main"])
    trained = {_key(m) for m, v in by_muscle.items() if v > 0}
    return sorted(m for m in known if _key(m) not in trained and _key(m) != "full body")
