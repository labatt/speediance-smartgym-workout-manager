"""Shaping for the Cardio page. No I/O, no Flask — unit-tested.

Speediance exposes rather less cardio data than its app implies. What it does give,
without any wearable, is where recorded heart rate actually sat: five zones with their
bpm ranges and the time spent in each. That is the page's centrepiece.

Recovery and sleep ARE rendered, even though the account this was written against has
neither. This is open-source software: anyone running it with a paired wearable will
have overnight HRV, resting heart rate and sleep scores, and leaving those out because
one developer's account is empty would ship them a worse app. A card appears when its
number exists and is silently skipped when it doesn't, so an empty account sees a short
explanation instead of a wall of dashes.

Field names come from the app's own string pool, but only the empty shape could be
observed live. `_first` therefore takes several candidate keys, and `extra_numbers`
surfaces anything unrecognised rather than dropping it — so a user WITH data sees their
numbers even if a key differs, and can report the real shape back.
"""

import json


def _num(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _fmt_duration(seconds):
    """Seconds -> '1h 20m' / '45m' / '30s'. Zero is a real answer, not a blank."""
    seconds = int(seconds or 0)
    if seconds <= 0:
        return "0m"
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return f"{seconds}s"


def heart_rate_zones(payload):
    """`heartRateStatIndex` -> zones with their share of recorded time.

    Zones arrive low to high. `timeLevel` is seconds spent in that band. A zone with no
    time is kept rather than dropped: "you never reached this" is information, and
    dropping it would silently renumber the ones above it.
    """
    payload = payload or {}
    rows = [r for r in (payload.get("timeLevelList") or []) if isinstance(r, dict)]
    total = sum(_num(r.get("timeLevel")) or 0 for r in rows)
    zones = []
    for index, row in enumerate(rows, 1):
        seconds = _num(row.get("timeLevel")) or 0
        low, high = row.get("levelRateMin"), row.get("levelRateMax")
        zones.append({
            "zone": index,
            "range": row.get("levelRateDisplay") or (f"{low}-{high}" if low and high else "-"),
            "seconds": int(seconds),
            "duration": _fmt_duration(seconds),
            "percent": round(100.0 * seconds / total, 1) if total > 0 else 0.0,
        })
    return {
        "available": bool(rows) and total > 0,
        "zones": zones,
        "totalSeconds": int(total),
        "totalDuration": _fmt_duration(total),
        "maxHeartRate": payload.get("maxHeartRate"),
        "minHeartRate": payload.get("minHeartRate"),
        "watchPaired": bool(payload.get("watchType")),
    }


def _ext(entry):
    """`extData` is a JSON string on some cards and absent on others."""
    raw = (entry or {}).get("extData")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def today_cards(health_score, actual_age=None):
    """`newIndex/healthScore` -> the cards that actually carry a number today.

    A card with no value is omitted rather than rendered blank — the whole point of
    this page is to not display placeholders for data that isn't coming.
    """
    score = health_score or {}
    cards = []

    steps = _num((score.get("walking") or {}).get("value"))
    if steps is not None:
        cards.append({"label": "Steps today", "value": f"{int(steps):,}", "hint": None})

    calories = _num((score.get("nutrition") or {}).get("value"))
    if calories is not None:
        cards.append({"label": "Nutrition", "value": f"{int(calories):,} kcal", "hint": "logged today"})

    body = _ext(score.get("bodyAge"))
    body_age = _num(body.get("age"))
    if body_age is not None:
        hint = None
        if actual_age:
            delta = body_age - actual_age
            hint = ("same as your age" if abs(delta) < 0.5
                    else f"{abs(delta):.1f} years {'older' if delta > 0 else 'younger'} than you")
        cards.append({"label": "Body age", "value": f"{body_age:g}", "hint": hint})

    monitor = _ext(score.get("wellnessMonitor"))
    if monitor.get("totalCount") is not None:
        cards.append({"label": "Wellness alerts", "value": str(monitor.get("totalCount")),
                      "hint": "flagged by Speediance"})
    return cards


# Field names recovered from the app's string pool. Only the empty shape could be
# observed on the account this was built against, so each reader tries several.
RECOVERY_CARDS = (
    ("recoveryScoreResp", "Recovery", ("value", "recoveryScore", "score"), ("avg", "recoveryScoreAvg"), ""),
    ("nightHrvResp", "Night HRV", ("nightHrv", "value", "hrv"), ("nightHrvAvg",), " ms"),
    ("nightRestingHeartRateResp", "Night resting HR",
     ("nightRestHeartRate", "value", "restHeartRate"), ("nightRestHeartRateAvg",), " bpm"),
    ("sleepResp", "Sleep score", ("value", "sleepScore", "score"), ("sleepScoreAvg",), ""),
)

SLEEP_SCORES = (
    ("sleepQualityScore", "Quality"),
    ("sleepEfficiencyScore", "Efficiency"),
    ("sleepRegularityScore", "Regularity"),
    ("sleepDurationScore", "Duration score"),
)


def _first(payload, keys):
    """The first candidate key that carries a number."""
    for key in keys:
        value = _num((payload or {}).get(key))
        if value is not None:
            return value
    return None


def extra_numbers(payload, known):
    """Numeric fields we didn't expect, so unfamiliar data is surfaced rather than lost."""
    known = {k.lower() for k in known}
    out = []
    for key, value in (payload or {}).items():
        if key.lower() in known or isinstance(value, (dict, list)):
            continue
        number = _num(value)
        if number is not None:
            out.append({"label": key, "value": f"{number:g}"})
    return out


def recovery_cards(recovery):
    """`recovery/detailByDate` -> one card per sub-report that has a number."""
    recovery = recovery or {}
    cards = []
    for key, label, value_keys, avg_keys, suffix in RECOVERY_CARDS:
        section = recovery.get(key) or {}
        value = _first(section, value_keys)
        if value is None:
            cards.extend({"label": f"{label}: {e['label']}", "value": e["value"], "hint": None}
                         for e in extra_numbers(section, value_keys + avg_keys))
            continue
        average = _first(section, avg_keys)
        cards.append({
            "label": label,
            "value": f"{value:g}{suffix}",
            "hint": f"{average:g}{suffix} average" if average is not None else None,
        })
    return cards


def sleep_summary(sleep):
    """`userHealth/sleep` -> slept vs target, plus whichever sub-scores are present."""
    sleep = sleep or {}
    minutes = _num(sleep.get("sleep"))
    target = _num(sleep.get("targetSleepMin"))
    scores = []
    for key, label in SLEEP_SCORES:
        value = _num(sleep.get(key))
        if value is not None:
            scores.append({"label": label, "value": f"{value:g}"})
    return {
        "available": bool(minutes) or bool(scores),
        "slept": _fmt_duration(int(minutes * 60)) if minutes else None,
        "target": _fmt_duration(int(target * 60)) if target else None,
        "metTarget": bool(minutes and target and minutes >= target),
        "scores": scores,
    }
