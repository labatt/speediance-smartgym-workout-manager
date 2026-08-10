"""Pure cardio/rowing session derivations. No I/O, no Flask — unit-tested.

Speediance logs cardio sessions (rowing/ski) as continuous telemetry rather than
reps x weight sets, so the strength breakdown is empty. The meaningful numbers
live in the session-info summary; this module turns that summary into display
and trend metrics. Mirrors static/workout-logic.js::deriveCardioStats — keep the
two in sync (both covered by the same worked oracle, trainingId 2023440).
"""

import math

# The only signal that cleanly separates cardio courses from strength in the
# records list (mileage is always 0; totalCapacity==0 also matches skipped
# strength sessions). Widen when a bike/ski example is observed.
CARDIO_COURSE_TYPES = {2}


def is_cardio_record(rec):
    """True iff a training-records entry is a cardio session we can chart."""
    return rec.get("courseType") in CARDIO_COURSE_TYPES


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


def derive_cardio_stats(s):
    """Map a session_info dict to display/trend metrics. Missing/zero inputs -> None."""
    dur = _num(s.get("trainingTime"))
    dist = _num(s.get("totalDistance"))
    cal = _num(s.get("calorie"))
    energy = _num(s.get("totalEnergy"))

    has_dur = dur is not None and dur > 0
    has_dist = dist is not None and dist > 0

    pace500 = _round(dur / (dist / 500.0), 1) if has_dur and has_dist else None
    speed = _round(dist / dur, 2) if has_dur and has_dist else None
    cal_min = _round(cal / (dur / 60.0), 1) if has_dur and cal is not None else None
    energy_kj = _round(energy / 1000.0, 1) if energy is not None else None
    watts = int(_round(energy / dur, 0)) if has_dur and energy is not None and energy > 0 else None

    return {
        "durationSec": int(dur) if dur is not None else None,
        "distanceM": _round(dist, 2) if dist is not None else None,
        "pace500": pace500,
        "speedMs": speed,
        "calorie": cal,
        "calPerMin": cal_min,
        "energyKJ": energy_kj,
        "avgWatts": watts,
        "completion": _num(s.get("completionRate")),
        "rpe": _num(s.get("rpe")),
    }
