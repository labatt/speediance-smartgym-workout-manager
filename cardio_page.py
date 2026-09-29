"""Shaping for the Cardio page. No I/O, no Flask — unit-tested.

Speediance exposes rather less cardio data than its app implies. What it does give,
without any wearable, is where recorded heart rate actually sat: five zones with their
bpm ranges and the time spent in each. That is the page's centrepiece.

Deliberately NOT rendered: VO2max, cardiorespiratory fitness and resting heart rate.
They need overnight HRV and resting-HR readings from a paired device, and GM Manager's
equivalent page shows all three permanently blank on this same account. An empty card
implies the number is coming; saying it needs a wearable is the truth.
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
