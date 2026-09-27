"""Which Speediance route holds a completed session's exercises, and how to read Free Lift.

The history feed's `type` decides the route (pookey/speediance-cli docs/api-notes.md, MIT;
verified live 2026-09-27):
  1, 6, 7 -> freeTraining                 (Free Lift / quick sessions)
  2       -> courseTrainingInfoDetail     (official courses)
  3, 5    -> cttTrainingInfoDetail        (custom templates)
  4, 9    -> aiCourseTrainingInfoDetail   (AI / Goal-Focused)
The calendar feed numbers types differently, so only apply this to history-feed types.

Every route except freeTraining returns the list shape the rest of the app parses
(actionLibraryName + finishedReps[].trainingInfoDetail). freeTraining returns one object
with actionList[].setList[].summary; free_training_to_detail converts it. Pure: no I/O.
"""

DETAIL_KINDS = {1: "free", 6: "free", 7: "free", 2: "course", 3: "custom", 5: "custom", 4: "ai", 9: "ai"}

# Free Lift set figures come back x2.2 on kg accounts (pookey) and unscaled on lb accounts
# (verified live on this lb account), so reconcile against the session's own total instead
# of assuming either way.
KG_LB_SCALE = 2.2
SCALE_TOLERANCE = 0.01


def detail_kind(session_type):
    """'free' | 'course' | 'custom' | 'ai' for a history-feed session type."""
    try:
        return DETAIL_KINDS.get(int(session_type), "custom")
    except (TypeError, ValueError):
        return "custom"


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _scale(payload):
    total = _num(payload.get("totalCapacity"))
    raw = sum(_num((st.get("summary") or {}).get("totalCapacity"))
              for action in payload.get("actionList") or [] for st in action.get("setList") or [])
    if total <= 0 or raw <= 0 or abs(raw - total) <= SCALE_TOLERANCE * total:
        return 1.0, None
    if abs(raw / KG_LB_SCALE - total) <= SCALE_TOLERANCE * total:
        return KG_LB_SCALE, None
    return 1.0, (f"Free Lift loads didn't reconcile with the session total (sets sum to {raw:.1f}, "
                 f"session reports {total:.1f}); showing the raw values.")


def free_training_to_detail(payload):
    """freeTraining object -> (list-shaped detail, warning-or-None).

    Each set's summary `weight` is already the load across both cables, so it becomes a
    one-element trainingInfoDetail.weights. targetCount mirrors finishedCount: Free Lift has
    no prescribed reps, so a logged set counts as complete.
    """
    if not isinstance(payload, dict) or not payload.get("actionList"):
        return [], None
    scale, warning = _scale(payload)
    detail = []
    for action in payload["actionList"]:
        finished = []
        for st in action.get("setList") or []:
            s = st.get("summary") or {}
            done = int(_num(s.get("finishedCount")))
            weight = s.get("weight")
            if weight is not None and scale != 1.0:
                weight = round(_num(weight) / scale, 1)
            finished.append({
                "finishedCount": done,
                "targetCount": done,
                "time": s.get("time") or 0,
                "leftRight": s.get("leftRight") or 0,
                "maxHeartRate": s.get("maxHeartRate"),
                "trainingInfoDetail": {"weights": [weight] if weight is not None else []},
            })
        detail.append({
            "actionLibraryName": action.get("actionLibraryName"),
            "actionLibraryGroupId": action.get("groupId"),
            "completionMethod": action.get("completionMethod"),
            "trainingPartId2": action.get("trainingPartId2"),
            "finishedReps": finished,
        })
    return detail, warning
