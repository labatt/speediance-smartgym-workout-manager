"""Read-only account profile for Settings. No I/O, no Flask — unit-tested.

Speediance owns these values; the app only mirrors them so the unit system is always
visible. Editing waits until Speediance's update route is known.

The unit trap: `userinfo.weightUnit` reads 0 even on an imperial account, so it must
never decide how weights are labelled. `unit` (1 = imperial) from the login/config is
the reliable source, and that is what everything else in this app already uses.
"""

import datetime

SEX = {0: "Male", 1: "Female"}
# `isWatch`: the profile flags whether a watch is paired. 0 is none; anything else
# names a paired device, and the exact value distinguishes the model.
WATCH = {0: "None paired"}


def _age(birthday, today=None):
    """Whole years from a 'YYYY-MM-DD ...' birthday, or None if unparseable."""
    try:
        born = datetime.date.fromisoformat(str(birthday)[:10])
    except (TypeError, ValueError):
        return None
    today = today or datetime.date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def profile_summary(profile, unit, today=None):
    """Profile payload -> rows for display, plus the fields the rest of the app trusts.

    `unit` is the account's display unit (1 = imperial), taken from config rather than
    from the payload, whose `weightUnit` is unreliable.
    """
    profile = profile or {}
    imperial = int(unit or 0) == 1
    weight = profile.get("weight")
    birthday = str(profile.get("birthday") or "")[:10] or None
    age = _age(birthday, today)
    watch = profile.get("isWatch")
    rows = [
        ("Unit system", "Imperial (lbs)" if imperial else "Metric (kg)"),
        ("Bodyweight", f"{weight:g} {'lbs' if imperial else 'kg'}" if weight else None),
        ("Height", profile.get("height") or None),
        ("Sex", SEX.get(profile.get("sex"))),
        ("Birthday", f"{birthday} ({age})" if birthday and age is not None else birthday),
        ("Watch", WATCH.get(watch, "Paired") if watch is not None else None),
        ("Email", profile.get("email") or None),
    ]
    return {
        "rows": [{"label": label, "value": value} for label, value in rows if value],
        "signedInPhone": bool(profile.get("isSoftwareLoggedIn")),
        "signedInMachine": bool(profile.get("isHardwareLoggedIn")),
    }
