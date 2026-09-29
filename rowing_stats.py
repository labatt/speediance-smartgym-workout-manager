"""Per-block rowing/ski telemetry. No I/O, no Flask — unit-tested.

Speediance records a rowing session as a series of samples a few seconds apart
(`app/boatingSkiDataGraph/{uuid}`), each carrying the stroke rate, pace, watts and
the target band the programmed workout is asking for at that moment. This module
turns that series into the blocks a person actually rowed.

Twin of speediance-mcp's parsing.rowing_telemetry — the two are deliberately
separate implementations so neither app depends on the other; keep them in step.
"""

import math

# Fields naming the programmed target at each sample.
_BAND_KEYS = ("minSpm", "maxSpm", "minResistance", "maxResistance")


def _num(v):
    """Coerce to float, or None if missing/non-numeric."""
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _round(v, ndigits):
    """Round half up (matches JS Math.round for non-negative values)."""
    factor = 10 ** ndigits
    return math.floor(v * factor + 0.5) / factor


def _points(data):
    """Normalise `pointDataList` into time-ordered samples, dropping unusable ones."""
    raw = data.get("pointDataList") if isinstance(data, dict) else data
    out = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        seconds = _num(item.get("time"))
        if seconds is None:
            continue
        out.append({
            "time": int(seconds),
            "strokeRate": _num(item.get("spm")) or 0,
            "pace500": _num(item.get("pace")),
            "watts": _num(item.get("power")),
            "resistance": _num(item.get("resistance")),
            "band": tuple(_num(item.get(k)) for k in _BAND_KEYS),
        })
    out.sort(key=lambda p: p["time"])
    return out


def _sample_seconds(points):
    """The gap between samples — the smallest positive step, since they are evenly spaced."""
    gaps = [b["time"] - a["time"] for a, b in zip(points, points[1:]) if b["time"] > a["time"]]
    return int(min(gaps)) if gaps else 0


def _stats(points, sample_seconds):
    """Averages over STROKING samples only.

    A sample with strokeRate 0 is the athlete not pulling — the flywheel spinning up,
    a pause, or the cool-down. Its pace is the wheel coasting, so including it would
    report a speed never actually rowed. Those samples count as rest instead.
    """
    working = [p for p in points if p["strokeRate"] > 0]
    rates = [p["strokeRate"] for p in working]
    paces = [p["pace500"] for p in working if p["pace500"] and p["pace500"] > 0]
    watts = [p["watts"] for p in working if p["watts"] is not None]
    return {
        "workingSec": len(working) * sample_seconds,
        "restingSec": (len(points) - len(working)) * sample_seconds,
        "avgStrokeRate": _round(sum(rates) / len(rates), 1) if rates else None,
        "maxStrokeRate": _round(max(rates), 1) if rates else None,
        # Lower pace is faster, so the best pace is the minimum.
        "avgPace500": _round(sum(paces) / len(paces), 1) if paces else None,
        "bestPace500": _round(min(paces), 1) if paces else None,
        "avgWatts": int(_round(sum(watts) / len(watts), 0)) if watts else None,
        "maxWatts": int(_round(max(watts), 0)) if watts else None,
    }


def derive_rowing_blocks(data):
    """Telemetry payload -> {available, totals, blocks[]}.

    Blocks are cut where the target band changes, because that is where the
    programmed workout moves from one piece to the next.
    """
    points = _points(data)
    if not points:
        return {"available": False,
                "reason": "No rowing telemetry for this session (the machine recorded no samples)."}
    sample_seconds = _sample_seconds(points)

    grouped = []
    for point in points:
        if not grouped or grouped[-1]["band"] != point["band"]:
            grouped.append({"band": point["band"], "points": []})
        grouped[-1]["points"].append(point)

    blocks = []
    for number, group in enumerate(grouped, 1):
        members = group["points"]
        min_spm, max_spm, min_res, max_res = group["band"]
        # No band means no target to be inside of — distinct from being outside one,
        # so this stays None rather than collapsing to 0%.
        has_band = min_spm is not None and max_spm is not None
        working = [p for p in members if p["strokeRate"] > 0]
        in_band = [p for p in working if has_band and min_spm <= p["strokeRate"] <= max_spm]
        blocks.append({
            "block": number,
            "startSec": members[0]["time"],
            "endSec": members[-1]["time"] + sample_seconds,
            "seconds": len(members) * sample_seconds,
            "targetStrokeRate": f"{int(min_spm)}-{int(max_spm)}" if has_band else None,
            "targetResistance": (f"{int(min_res)}-{int(max_res)}"
                                 if None not in (min_res, max_res) else None),
            "inTargetPercent": (_round(100.0 * len(in_band) / len(working), 1)
                                if has_band and working else None),
            **_stats(members, sample_seconds),
        })

    return {"available": True, "samples": len(points), "sampleSeconds": sample_seconds,
            "durationSec": points[-1]["time"] + sample_seconds,
            **_stats(points, sample_seconds), "blocks": blocks}
