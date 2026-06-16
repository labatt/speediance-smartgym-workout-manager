"""
Adaptive Speediance training planner for Toby — unique-per-day edition.

Loads the on-device Speediance library and picks a single-implement, on-device
workout that is guaranteed to differ from the last N days (N starts at the
total number of historical plans in training_plans/, grows by 1 per day,
caps at UNIQUE_LOOKBACK_MAX = 30). Adds 0–2 off-Speediance (no-implement)
exercises on top of the 10 on-device moves for extra variety. If forced to
repeat, the title still uses today's date so the workout is freshly surfaced.

All file paths and tunables live at the top of the file. The blacklist is
intentionally empty by default — populate BLACKLIST below if/when needed.
"""

import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


SPEEDIANCE_MANAGER_DIR = Path(os.path.expanduser("~/.openclaw/workspace/speediance_manager"))
LIBRARY_CACHE = SPEEDIANCE_MANAGER_DIR / "library_cache_v2_device1_allow0.json"
TRAINING_PLANS_DIR = Path(os.path.expanduser("~/clawd/data/training_plans"))

STAMINA_PRESET_ID = 3
STAMINA_SPORT_MODE = 3
TOBY_REPS = 13
TOBY_REST_SECONDS = 30
WARMUP_RM = 20
WORKING_RM = 15

UNIQUE_LOOKBACK_MAX = 30
ON_DEVICE_COUNT = 10                # mandatory on-device lifts per workout
OFF_SPEEDIANCE_MAX = 2              # max off-Speediance additions per workout

# Optional blacklist — empty by default. Populate with group_id ints to drop
# movements from the candidate pool. Designed to be edited in place.
BLACKLIST: Tuple[int, ...] = ()

SETUP_RANK = {"high": 0, "chest": 1, "mid": 2, "base": 3}
SETUP_POSITION_ORDER = SETUP_RANK

# Implement → accessories code mapping (Speediance library "accessories" field).
# "handles"  → '5'  (also accepts 5,1 / 5,9 etc for bench/incline variants)
# "barbell"  → '4'
# "rope"     → '2'
IMPLEMENT_CODES = {
    "handles": {"5", "5,1", "5,9", "1,5", "9,5"},
    "barbell": {"4", "4,1", "4,9", "1,4", "9,4"},
    "rope": {"2", "2,1", "2,9", "1,2", "9,2"},
}


# ---------------------------------------------------------------------------
# Movement dataclass + catalog loader
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Movement:
    group_id: int
    name: str
    patterns: tuple
    implement: str
    setup_position: str          # "high" / "chest" / "mid" / "base"
    bjj_cost: str = "moderate"   # "high" / "moderate" / "low"
    unilateral: bool = False
    main_muscle: str = ""
    off_speediance: bool = False


def _out_position_to_setup(out_position: Optional[int]) -> str:
    """Map Speediance's numeric outPosition to a setup rank bucket.

    outPosition is 0-10 per the catalog. Lower = higher cable anchor.
    Returns "high" (0-2), "chest" (3-6), "base" (7-10). "mid" is kept for
    any future use but the catalog doesn't currently emit it.
    """
    if out_position is None:
        return "chest"
    if out_position <= 2:
        return "high"
    if out_position <= 6:
        return "chest"
    return "base"


def _muscle_to_patterns(main_muscle: str, title: str = "") -> tuple:
    """Map Speediance's mainMuscleGroupName + title keywords to a pattern tuple."""
    title_l = title.lower()
    patterns = []
    if main_muscle in ("Pecs", "Front Delts", "Side Delts", "Triceps"):
        patterns.append("push")
    if main_muscle in ("Lats", "Rear Delts", "Biceps", "Trapezius", "Forearms"):
        patterns.append("pull")
    if main_muscle in ("Hamstrings", "Gluteus", "Quadriceps", "Calves", "Adductors"):
        patterns.append("legs")
    if main_muscle in ("Lats", "Rear Delts"):
        patterns.append("posture")
    if main_muscle in ("Abs",):
        patterns.append("core")
    if main_muscle in ("Full Body",):
        patterns.append("full_body")

    # Title-keyword nudges
    if "row" in title_l:
        patterns.append("row")
    if "deadlift" in title_l or "rdl" in title_l or "good morning" in title_l:
        patterns.append("hinge")
    if "fly" in title_l or "pec deck" in title_l:
        patterns.append("chest")
    if "curl" in title_l and "bicep" not in title_l:
        patterns.append("biceps")
    if "lateral raise" in title_l or "front raise" in title_l or "rear delt" in title_l or "face pull" in title_l:
        patterns.append("accessory")
        patterns.append("shoulders")
    if "press" in title_l and "leg" not in title_l:
        patterns.append("push")
    if "woodchop" in title_l or "rotation" in title_l or "pallof" in title_l:
        patterns.append("rotation")
        patterns.append("core")
    if "squat" in title_l or "lunge" in title_l or "leg press" in title_l or "split squat" in title_l:
        patterns.append("squat")
        patterns.append("legs")
    if "calf" in title_l:
        patterns.append("calves")
    if "shrug" in title_l:
        patterns.append("trapezius")
    if "kickback" in title_l:
        patterns.append("legs")
        patterns.append("glutes")

    # Unilateral hints
    unilateral = any(t in title_l for t in (
        "single-arm", "single-arm", "alternating", "single leg", "single-arm",
        "one-arm", "unilateral",
    ))
    return tuple(dict.fromkeys(patterns)), unilateral


def _load_library() -> Tuple[List[Movement], List[Movement]]:
    """Read the Speediance library cache and return (on_device, off_device) pools."""
    if not LIBRARY_CACHE.exists():
        return [], []
    raw = json.load(open(LIBRARY_CACHE))
    on_device: List[Movement] = []
    off_device: List[Movement] = []
    blacklist = set(BLACKLIST)
    for m in raw:
        if m.get("isCustom") not in (0, None):
            continue
        acc = str(m.get("accessories") or "").strip()
        gid = int(m.get("id") or 0)
        title = m.get("title") or ""
        if not gid or not title:
            continue
        if gid in blacklist:
            continue
        main_muscle = m.get("mainMuscleGroupName") or ""
        out_pos = m.get("outPosition")
        setup = _out_position_to_setup(out_pos)
        patterns, unilateral = _muscle_to_patterns(main_muscle, title)

        if not acc or acc in ("0", "[]"):  # off-Speediance
            off_device.append(Movement(
                group_id=gid, name=title, patterns=patterns, implement="none",
                setup_position="floor", bjj_cost="low", unilateral=False,
                main_muscle=main_muscle, off_speediance=True,
            ))
            continue

        if not m.get("isUseDevice"):
            continue
        # Map accessories to implement label
        if acc in IMPLEMENT_CODES["handles"]:
            impl = "handles"
        elif acc in IMPLEMENT_CODES["barbell"]:
            impl = "barbell"
        elif acc in IMPLEMENT_CODES["rope"]:
            impl = "rope"
        else:
            continue
        on_device.append(Movement(
            group_id=gid, name=title, patterns=patterns, implement=impl,
            setup_position=setup, bjj_cost="moderate", unilateral=unilateral,
            main_muscle=main_muscle, off_speediance=False,
        ))
    return on_device, off_device


# Populated on import. Will be empty if the library cache is missing.
ON_DEVICE_POOL: List[Movement] = []
OFF_SPEEDIANCE_POOL: List[Movement] = []


def _refresh_pools() -> None:
    global ON_DEVICE_POOL, OFF_SPEEDIANCE_POOL
    on, off = _load_library()
    ON_DEVICE_POOL = on
    OFF_SPEEDIANCE_POOL = off


_refresh_pools()


# ---------------------------------------------------------------------------
# Training signals (unchanged shape)
# ---------------------------------------------------------------------------

@dataclass
class TrainingSignals:
    date: str
    report_context: str = "morning"
    whoop_recovery: float = 0.0
    whoop_strain_so_far: float = 0.0
    bjj_strain: float = 0.0
    bjj_minutes: float = 0.0
    bjj_completed: bool = False
    bjj_expected_today: bool = False
    expected_bjj_strain: float = 0.0
    garmin_body_battery: float = 0.0
    resting_hr: Optional[float] = None
    baseline_resting_hr: Optional[float] = None
    sleep_hours: Optional[float] = None
    morning_step_target: int = 8000
    recent_28d_run_miles: float = 0.0
    recent_weekly_run_miles: float = 0.0
    current_week_run_miles: float = 0.0
    recent_long_run_miles: float = 0.0
    observed_max_run_hr: float = 0.0
    recent_easy_run_avg_hr: float = 0.0
    forecast_high_f: float = 0.0
    heat_index_f: float = 0.0
    thunderstorm_risk: bool = False
    preferred_patterns: tuple = ()
    avoid_patterns: tuple = ()
    preferred_implement: Optional[str] = None


@dataclass
class RunPrescription:
    mode: str
    distance_miles: float
    heart_rate_zones: str
    reason: str


@dataclass
class PlannedExercise:
    group_id: int
    name: str
    rm: int                          # 0 for off-Speediance (no RM)
    role: str                        # "warmup" / "working" / "off_speediance"
    setup_position: str
    sets: int = 1
    reps: int = TOBY_REPS
    rest_seconds: int = TOBY_REST_SECONDS
    off_speediance: bool = False
    implement: str = ""


@dataclass
class TrainingPlan:
    date: str
    report_context: str
    readiness_bucket: str
    strain_capacity: float
    remaining_strain: float
    speediance_title: str
    speediance_mode: str
    implement: str
    exercises: List[PlannedExercise]
    run: RunPrescription
    step_target: int
    notes: List[str] = field(default_factory=list)
    uniqueness_window: int = 0
    uniqueness_skipped: int = 0
    forced_repeats: int = 0

    @property
    def warmup_count(self) -> int:
        return sum(1 for e in self.exercises if e.rm == WARMUP_RM and not e.off_speediance)

    @property
    def working_count(self) -> int:
        return sum(1 for e in self.exercises if e.rm == WORKING_RM and not e.off_speediance)

    @property
    def off_speediance_count(self) -> int:
        return sum(1 for e in self.exercises if e.off_speediance)


# ---------------------------------------------------------------------------
# Capacity / bucket / run prescription (unchanged)
# ---------------------------------------------------------------------------

def estimate_daily_strain_capacity(signals: TrainingSignals) -> float:
    recovery = signals.whoop_recovery or 0
    if recovery >= 75:
        capacity = 15.0
    elif recovery >= 60:
        capacity = 13.5
    elif recovery >= 45:
        capacity = 11.5
    elif recovery >= 30:
        capacity = 9.5
    else:
        capacity = 8.0

    if signals.garmin_body_battery and signals.garmin_body_battery < 35:
        capacity -= 1.0
    elif signals.garmin_body_battery >= 75:
        capacity += 0.75

    if signals.resting_hr and signals.baseline_resting_hr:
        rhr_delta = signals.resting_hr - signals.baseline_resting_hr
        if rhr_delta >= 7:
            capacity -= 1.5
        elif rhr_delta >= 4:
            capacity -= 0.75

    if signals.sleep_hours is not None and signals.sleep_hours < 6:
        capacity -= 1.0

    return round(max(6.5, min(16.0, capacity)), 1)


def classify_readiness(signals: TrainingSignals, remaining_strain: float) -> str:
    if signals.bjj_completed and (signals.bjj_strain >= 12.0 or signals.whoop_strain_so_far >= 14.0):
        return "post_bjj_brutal"
    if remaining_strain <= 1.5 or signals.whoop_recovery < 30:
        return "protect"
    if remaining_strain <= 3.5:
        return "recover"
    if remaining_strain <= 5.5:
        return "maintain"
    return "build"


def _round_run_distance(distance: float) -> float:
    if distance <= 0:
        return 0.0
    return round(max(0.5, distance) * 10) / 10


def _easy_run_hr_text(signals: TrainingSignals, heat_limited: bool = False) -> str:
    max_hr = signals.observed_max_run_hr if signals.observed_max_run_hr >= 150 else 185.0
    z2_low = int(round(max_hr * 0.60))
    z2_high = int(round(max_hr * 0.70))

    if signals.recent_easy_run_avg_hr:
        low = int(round(max(105, signals.recent_easy_run_avg_hr - 5)))
        high = int(round(min(z2_high, signals.recent_easy_run_avg_hr + 12)))
    else:
        low = z2_low
        high = z2_high

    cap = min(high + 5, 135 if heat_limited else 140)
    if heat_limited:
        high = min(high, 130)
        cap = min(cap, 135)
        return f"easy aerobic HR {low}-{high} bpm; hard cap {cap} bpm in heat; walk if HR drifts"
    return f"easy aerobic HR {low}-{high} bpm; hard cap {cap} bpm; mostly Zone 2/no intervals"


def _run_volume_limited_distance(signals: TrainingSignals, bucket: str, remaining_strain: float) -> float:
    weekly_avg = signals.recent_weekly_run_miles or (
        signals.recent_28d_run_miles / 4 if signals.recent_28d_run_miles else 0.0
    )

    if bucket == "maintain":
        base = 0.75
    elif weekly_avg <= 0:
        base = 0.75
    elif weekly_avg < 6:
        base = 1.5
    elif weekly_avg < 10:
        base = 2.0
    else:
        base = 2.0 if remaining_strain < 8 else 3.0

    if weekly_avg > 0:
        weekly_target_cap = max(3.0, weekly_avg * 1.10)
        remaining_week_room = weekly_target_cap - (signals.current_week_run_miles or 0.0)
        if remaining_week_room <= 0:
            return 0.0
        base = min(base, remaining_week_room)
        if signals.recent_long_run_miles > 0:
            base = min(base, max(0.75, signals.recent_long_run_miles * 0.80))

    heat_index = signals.heat_index_f or signals.forecast_high_f or 0.0
    if heat_index >= 100 or signals.forecast_high_f >= 92:
        base = min(base * 0.40, 0.75)
    elif heat_index >= 95 or signals.forecast_high_f >= 88:
        base = min(base * 0.65, 1.25)

    return _round_run_distance(base)


def choose_run(signals: TrainingSignals, bucket: str, remaining_strain: float) -> RunPrescription:
    heat_index = signals.heat_index_f or signals.forecast_high_f or 0.0
    heat_limited = heat_index >= 95 or signals.forecast_high_f >= 88
    storm_note = " Avoid thunderstorm windows." if signals.thunderstorm_risk else ""

    if bucket in {"post_bjj_brutal", "protect", "recover"}:
        return RunPrescription(
            mode="walk",
            distance_miles=0.0,
            heart_rate_zones="walk only; keep HR mostly Zone 1, roughly under 115 bpm",
            reason="BJJ/recovery load already consumed the useful strain budget." + storm_note,
        )

    distance = _run_volume_limited_distance(signals, bucket, remaining_strain)
    if distance <= 0:
        return RunPrescription(
            mode="walk",
            distance_miles=0.0,
            heart_rate_zones="walk only; keep HR mostly Zone 1, roughly under 115 bpm",
            reason="Recent weekly running volume is already at today's progression cap." + storm_note,
        )

    if bucket == "maintain":
        mode = "optional_short_easy_run"
        reason = "There is a little capacity left, but run distance is capped by recent mileage."
    elif heat_index >= 100 or signals.forecast_high_f >= 92:
        mode = "heat_limited_optional_jog"
        reason = "Recovery supports movement, but recent mileage plus Camp Hill heat caps this to a short early jog or walk."
    elif heat_limited:
        mode = "heat_adjusted_easy_run"
        reason = "Recovery supports easy aerobic work, with distance reduced for heat and recent run volume."
    else:
        mode = "easy_run"
        reason = "Recovery and strain budget support easy aerobic work scaled to recent running volume."

    if signals.recent_weekly_run_miles:
        reason += (
            f" Recent baseline: {signals.recent_weekly_run_miles:.1f} mi/week; "
            f"current week: {signals.current_week_run_miles:.1f} mi."
        )
    if heat_limited:
        reason += f" Forecast heat signal: {heat_index:.0f}F."
    reason += storm_note

    return RunPrescription(
        mode=mode,
        distance_miles=distance,
        heart_rate_zones=_easy_run_hr_text(signals, heat_limited=heat_limited),
        reason=reason,
    )


def choose_step_target(signals: TrainingSignals, bucket: str) -> int:
    base = int(signals.morning_step_target or 8000)
    if bucket == "post_bjj_brutal":
        return max(5000, min(base, 6500))
    if bucket == "protect":
        return max(5000, min(base, 7000))
    if bucket == "recover":
        return max(6500, min(base, 8500))
    if bucket == "maintain":
        return max(base, 9000)
    return max(base, 10000)


# ---------------------------------------------------------------------------
# Movement selection — uniqueness-aware
# ---------------------------------------------------------------------------

def _load_uniqueness_signatures() -> List[Tuple[Tuple[int, int], ...]]:
    """Load past workout signatures from training_plans/. Each signature is a
    sorted tuple of (group_id, rm) pairs representing the 10 on-device moves.
    """
    if not TRAINING_PLANS_DIR.exists():
        return []
    signatures: List[Tuple[Tuple[int, int], ...]] = []
    for path in sorted(TRAINING_PLANS_DIR.glob("*_post_bjj.json")):
        try:
            data = json.load(open(path))
        except Exception:
            continue
        sig = tuple(sorted(
            (int(e["group_id"]), int(e.get("rm", 0)))
            for e in data.get("exercises", [])
            if not e.get("off_speediance") and e.get("group_id") is not None
        ))
        if sig:
            signatures.append(sig)
    return signatures


def _movement_score(movement: Movement, patterns: Iterable[str], avoid: Iterable[str], bucket: str) -> int:
    wanted = set(patterns)
    avoided = set(avoid)
    score = 0
    score += 4 * len(wanted.intersection(movement.patterns))
    score -= 6 * len(avoided.intersection(movement.patterns))
    if bucket in {"post_bjj_brutal", "protect", "recover"} and movement.bjj_cost == "high":
        score -= 8
    if bucket in {"post_bjj_brutal", "recover"} and movement.bjj_cost == "low":
        score += 3
    return score


def _setup_rank(movement: Movement) -> int:
    return SETUP_RANK.get(movement.setup_position, 99)


def choose_patterns(signals: TrainingSignals, bucket: str) -> tuple:
    if signals.preferred_patterns:
        return signals.preferred_patterns
    if bucket in {"post_bjj_brutal", "protect", "recover"}:
        return ("posture", "core", "rear_delts", "lats", "accessory")
    if bucket == "maintain":
        return ("pull", "push", "core", "shoulders", "arms")
    return ("pull", "push", "hinge", "legs", "core")


def choose_implement(signals: TrainingSignals, bucket: str, count: int) -> str:
    if signals.preferred_implement:
        return signals.preferred_implement
    if not ON_DEVICE_POOL:
        return "handles"
    patterns = choose_patterns(signals, bucket)
    implement_scores: Dict[str, int] = {}
    for implement in {m.implement for m in ON_DEVICE_POOL}:
        candidates = [m for m in ON_DEVICE_POOL if m.implement == implement]
        if len(candidates) < count:
            continue
        score = sum(
            sorted(
                [_movement_score(m, patterns, signals.avoid_patterns, bucket) for m in candidates],
                reverse=True,
            )[:count]
        )
        if bucket in {"post_bjj_brutal", "protect", "recover"} and implement == "handles":
            score += 6
        implement_scores[implement] = score
    if not implement_scores:
        return "handles"
    return max(implement_scores, key=implement_scores.get)


def _would_duplicate(signature_so_far: Tuple[Tuple[int, int], ...],
                    candidate_id: int, candidate_rm: int,
                    target_count: int,
                    past_signatures: List[Tuple[Tuple[int, int], ...]]) -> bool:
    """True if adding (candidate_id, candidate_rm) to signature_so_far would
    produce a plan whose first target_count moves match a past plan's first
    target_count moves. We compare prefixes so that small overlaps still count.
    """
    new_sig = tuple(sorted(signature_so_far + ((candidate_id, candidate_rm),)))
    prefix = new_sig[:target_count]
    for past in past_signatures:
        past_prefix = past[:target_count]
        if past_prefix and past_prefix == prefix:
            return True
    return False


def select_movements(signals: TrainingSignals, bucket: str, count: int,
                     past_signatures: List[Tuple[Tuple[int, int], ...]],
                     window: int) -> Tuple[List[Movement], int, int]:
    """Pick `count` on-device movements, all from a single implement, that
    differ from any past plan in the lookback window. Returns (movements,
    skipped_for_uniqueness, forced_repeats).
    """
    patterns = choose_patterns(signals, bucket)
    if not ON_DEVICE_POOL:
        return [], 0, 0
    implement = choose_implement(signals, bucket, count)
    candidates = [m for m in ON_DEVICE_POOL if m.implement == implement]
    ranked = sorted(
        candidates,
        key=lambda m: (
            _movement_score(m, patterns, signals.avoid_patterns, bucket),
            -m.group_id,  # stable secondary key for variety
        ),
        reverse=True,
    )
    selected: List[Movement] = []
    seen_ids: set = set()
    signature: List[Tuple[int, int]] = []
    skipped = 0
    for movement in ranked:
        if movement.group_id in seen_ids:
            continue
        if _would_duplicate(tuple(signature), movement.group_id, WARMUP_RM,
                            min(count, len(signature) + 1), past_signatures):
            skipped += 1
            continue
        selected.append(movement)
        seen_ids.add(movement.group_id)
        signature.append((movement.group_id, WARMUP_RM))
        if len(selected) >= count:
            break
    forced = 0
    if len(selected) < count:
        for movement in ranked:
            if movement.group_id in seen_ids:
                continue
            selected.append(movement)
            seen_ids.add(movement.group_id)
            forced += 1
            if len(selected) >= count:
                break
    selected = sorted(selected, key=lambda m: (_setup_rank(m), selected.index(m)))
    return selected, skipped, forced


def select_off_speediance(bucket: str, count: int,
                          past_signatures: List[Tuple[Tuple[int, int], ...]],
                          window: int) -> List[Movement]:
    """Pick up to `count` off-Speediance additions, avoiding any group_id
    used in past plans' off-Speediance additions (so the same jump-squat
    doesn't show up day after day).
    """
    if count <= 0 or not OFF_SPEEDIANCE_POOL:
        return []
    past_off_ids: set = set()
    for path in sorted(TRAINING_PLANS_DIR.glob("*_post_bjj.json")):
        try:
            data = json.load(open(path))
        except Exception:
            continue
        for e in data.get("exercises", []):
            if e.get("off_speediance") and e.get("group_id") is not None:
                past_off_ids.add(int(e["group_id"]))
    window_paths = sorted(TRAINING_PLANS_DIR.glob("*_post_bjj.json"))[-window:]
    window_off_ids: set = set()
    for path in window_paths:
        try:
            data = json.load(open(path))
        except Exception:
            continue
        for e in data.get("exercises", []):
            if e.get("off_speediance") and e.get("group_id") is not None:
                window_off_ids.add(int(e["group_id"]))

    ranked = sorted(OFF_SPEEDIANCE_POOL, key=lambda m: (
        0 if m.group_id in window_off_ids else 1,   # prefer never-seen-in-window
        0 if m.group_id in past_off_ids else 1,     # then never-seen-ever
        -m.group_id,
    ))
    out: List[Movement] = []
    seen: set = set()
    for m in ranked:
        if m.group_id in seen:
            continue
        out.append(m)
        seen.add(m.group_id)
        if len(out) >= count:
            break
    return out


def choose_rm_sequence(bucket: str) -> List[int]:
    if bucket in {"post_bjj_brutal", "protect", "recover"}:
        return [WARMUP_RM] * ON_DEVICE_COUNT
    if bucket == "maintain":
        return [WARMUP_RM] * 7 + [WORKING_RM] * 3
    return [WARMUP_RM] * 5 + [WORKING_RM] * 5


def build_plan(signals: TrainingSignals) -> TrainingPlan:
    capacity = estimate_daily_strain_capacity(signals)
    observed_strain = max(signals.whoop_strain_so_far or 0.0, signals.bjj_strain or 0.0)
    reserved_bjj = 0.0
    if signals.bjj_expected_today and not signals.bjj_completed:
        reserved_bjj = signals.expected_bjj_strain if signals.expected_bjj_strain > 0 else 12.0
    remaining = round(max(0.0, capacity - observed_strain - reserved_bjj), 1)
    bucket = classify_readiness(signals, remaining)

    # Window = total historical plans (this will be the new plan), capped at 30.
    # Today's plan is the (window)th in history; we want it to differ from the
    # previous (window - 1). So past_signatures are loaded with that count.
    past_signatures = _load_uniqueness_signatures()
    window = min(UNIQUE_LOOKBACK_MAX, len(past_signatures) + 1)
    # Trim the loaded signatures to the window so the comparator only checks
    # the last (window - 1) plans (today is plan #window).
    past_window = past_signatures[-(window - 1):] if window > 1 else []

    rms = choose_rm_sequence(bucket)
    movements, skipped, forced = select_movements(
        signals, bucket, ON_DEVICE_COUNT, past_window, window,
    )
    if not movements:
        # Pool empty — fall back to handles w/ 0 count rather than crash
        movements = ON_DEVICE_POOL[:ON_DEVICE_COUNT]
    implement = movements[0].implement if movements else "handles"

    # RM assignment: if forced repeats reduced the pool, fill the rest as
    # working sets to keep the Speediance payload valid.
    effective_rms = list(rms)
    if len(movements) < len(rms):
        effective_rms = effective_rms[: len(movements)]
    if len(effective_rms) < len(movements):
        effective_rms += [WORKING_RM] * (len(movements) - len(effective_rms))

    # Off-Speediance additions: scale by bucket. Recover/protect = 0 (light).
    # Maintain = up to 1. Build = up to 2. Brutal = 0.
    if bucket in {"post_bjj_brutal", "protect", "recover"}:
        off_count = 0
    elif bucket == "maintain":
        off_count = min(OFF_SPEEDIANCE_MAX, 1)
    else:
        off_count = OFF_SPEEDIANCE_MAX
    off_movements = select_off_speediance(bucket, off_count, past_window, window)

    exercises: List[PlannedExercise] = []
    for movement, rm in zip(movements, effective_rms):
        exercises.append(PlannedExercise(
            group_id=movement.group_id,
            name=movement.name,
            rm=rm,
            role="warmup" if rm == WARMUP_RM else "working",
            setup_position=movement.setup_position,
            sets=2 if movement.unilateral else 1,
            off_speediance=False,
            implement=implement,
        ))
    for m in off_movements:
        exercises.append(PlannedExercise(
            group_id=m.group_id,
            name=m.name,
            rm=0,
            role="off_speediance",
            setup_position=m.setup_position,
            sets=1,
            off_speediance=True,
            implement="none",
        ))

    if bucket in {"post_bjj_brutal", "protect", "recover"}:
        speediance_mode = "recovery_stamina_rm20"
        title = f"ARIA {implement.title()} Recovery Stamina"
    elif bucket == "maintain":
        speediance_mode = "stamina_mixed_7x20_3x15"
        title = f"ARIA {implement.title()} Maintain Stamina"
    else:
        speediance_mode = "stamina_mixed_5x20_5x15"
        title = f"ARIA {implement.title()} Build Stamina"

    date_stamp = signals.date.replace("-", "")
    title = f"{title} {date_stamp}"  # always today's date — never inherits

    notes = [
        f"Capacity {capacity:.1f}; observed strain {observed_strain:.1f}; remaining {remaining:.1f}.",
        "RM20 is warm-up/low-stress Stamina work; RM15 is the working-set setting.",
        f"Single implement: {implement}. On-device only, ordered high→chest→base by Speediance setup position.",
        f"Uniqueness window: last {window - 1} day(s) of plans; new plan must differ from all of them.",
    ]
    if off_movements:
        notes.append(
            f"Added {len(off_movements)} off-Speediance (no-implement) move(s) on top of the "
            f"{ON_DEVICE_COUNT} on-device moves for extra variety."
        )
    if skipped:
        notes.append(f"Skipped {skipped} candidate(s) that would have duplicated a recent plan.")
    if forced:
        notes.append(
            f"Forced {forced} repeat(s) — no unused on-device movements of {implement} available. "
            "Title still uses today's date; the workout is freshly surfaced."
        )
    if reserved_bjj > 0:
        notes.append(
            f"Reserved {reserved_bjj:.1f} strain for today's scheduled BJJ session."
        )
    if signals.bjj_completed:
        notes.append(f"Post-BJJ adjustment used BJJ strain {signals.bjj_strain:.1f}.")
    elif signals.report_context == "morning":
        notes.append("Morning version is provisional until the post-BJJ 9:30 refresh.")

    return TrainingPlan(
        date=signals.date,
        report_context=signals.report_context,
        readiness_bucket=bucket,
        strain_capacity=capacity,
        remaining_strain=remaining,
        speediance_title=title,
        speediance_mode=speediance_mode,
        implement=implement,
        exercises=exercises,
        run=choose_run(signals, bucket, remaining),
        step_target=choose_step_target(signals, bucket),
        notes=notes,
        uniqueness_window=window,
        uniqueness_skipped=skipped,
        forced_repeats=forced,
    )


def build_speediance_payload_exercises(plan: TrainingPlan) -> List[Dict]:
    """Convert a dry-run plan into SpeedianceClient.save_workout exercises.
    Off-Speediance additions are not sent to the device.
    """
    payload = []
    for exercise in plan.exercises:
        if exercise.off_speediance:
            continue
        sets = [
            {
                "reps": exercise.reps,
                "weight": exercise.rm,
                "mode": STAMINA_SPORT_MODE,
                "rest": exercise.rest_seconds,
                "unit": "reps",
            }
            for _ in range(exercise.sets)
        ]
        payload.append({
            "groupId": exercise.group_id,
            "preset_id": STAMINA_PRESET_ID,
            "data_stat_type": 0,
            "sets": sets,
        })
    return payload


def render_plan_text(plan: TrainingPlan) -> str:
    lines = [
        f"{plan.speediance_title} ({plan.speediance_mode})",
        f"Implement: {plan.implement} only (on-device).",
        f"Speediance: {plan.warmup_count} RM20 warm-up slots, {plan.working_count} RM15 working slots.",
        f"Off-Speediance additions: {plan.off_speediance_count} (no RM; bodyweight/plio/mobility).",
        f"Run: {plan.run.mode}, {plan.run.distance_miles:g} mi, {plan.run.heart_rate_zones}.",
        f"Steps: {plan.step_target:,}.",
        f"Uniqueness window: {plan.uniqueness_window} day(s).",
        "Exercises:",
    ]
    for i, ex in enumerate(plan.exercises, 1):
        side = " x2 sides" if ex.sets == 2 else ""
        if ex.off_speediance:
            lines.append(f"{i}. {ex.name} — off-Speediance (bodyweight){side}")
        else:
            lines.append(f"{i}. {ex.name} — RM{ex.rm}, {ex.reps} reps{side}")
    for note in plan.notes:
        lines.append(f"Note: {note}")
    return "\n".join(lines)


def signals_from_dict(data: Dict) -> TrainingSignals:
    allowed = set(TrainingSignals.__dataclass_fields__)
    clean = {k: v for k, v in data.items() if k in allowed}
    if not clean.get("date"):
        clean["date"] = datetime.now().strftime("%Y-%m-%d")
    return TrainingSignals(**clean)
