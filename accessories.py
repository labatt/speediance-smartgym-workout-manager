"""Accessory catalog helpers. No I/O, no Flask — unit-tested.

Speediance lists the same accessory under several ids (the Monster 3 and Ultra each
have their own "Handles", "Tricep Rope", "Ankle Straps"...). Rendering one tile per id
means ticking the "wrong" Handles silently hides every exercise that needs the other,
so the UI shows one tile per NAME and remembers all the ids behind it.

Matches speediance-mcp's list_accessories, which deduplicates the same way.
"""


def dedupe_accessories(catalog):
    """Catalog rows -> one entry per name: {name, ids, img, type}, name-sorted.

    Keeps every id so ownership can be stored for all of them, and the first image
    found, since the duplicates are the same physical item.
    """
    by_name = {}
    for item in catalog or []:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        entry = by_name.setdefault(name.lower(), {
            "name": name, "ids": [], "img": item.get("img"),
            "type": "furniture" if item.get("type") == 1 else "attachment",
        })
        if item.get("id") is not None:
            entry["ids"].append(int(item["id"]))
        if not entry["img"] and item.get("img"):
            entry["img"] = item.get("img")
    return sorted(by_name.values(), key=lambda e: e["name"].lower())


def is_owned(entry, owned_ids):
    """Owned if ANY id behind the name is owned — a tick on either duplicate counts."""
    owned = set(owned_ids or [])
    return any(i in owned for i in entry["ids"])


def parse_selected_ids(values):
    """Form values -> a flat list of ids.

    Each checkbox submits every id behind its name as a comma-separated value, so one
    tick owns all the duplicates of that accessory. Unparseable values are dropped
    rather than failing the save.
    """
    out = []
    for value in values or []:
        for part in str(value).split(","):
            part = part.strip()
            if part.lstrip("-").isdigit():
                number = int(part)
                if number not in out:
                    out.append(number)
    return out
