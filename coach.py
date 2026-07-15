"""Turn a session's deterministic facts into a coaching read, via a local Ollama model.

Split in two on purpose:

- build_prompt() is PURE and unit-tested. It lays out the facts progression.py extracted
  plus the athlete's own felt ratings, and hard-codes the lesson from 2026-07-14 into the
  system prompt: a power sensor cannot measure effort, so the felt rating outranks any
  metric, and the model must cite the numbers it is given and never invent one.
- ask_ollama() is a thin HTTP client to a local Ollama daemon. It is optional: if Ollama
  is not running the feature degrades to a clear "start Ollama" message rather than an error.

The model interprets; it does not compute. Every number it may cite is pre-computed here.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

# Ollama Cloud: a hosted Ollama that speaks the same API at https://ollama.com with a Bearer
# key (created at ollama.com/settings/keys). This box has no GPU and shares its RAM with
# other services, so cloud is the right call — nothing runs locally. The same code works
# against a local daemon (http://127.0.0.1:11434, no key) if that is ever preferred.
DEFAULT_ENDPOINT = "https://ollama.com"
DEFAULT_MODEL = "gpt-oss:120b"

_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "coach_config.json")


def endpoint_allowed(endpoint):
    """Only Ollama Cloud, or a local Ollama daemon on its standard port.

    The endpoint is user-set and every call carries the Bearer key, so an unrestricted value
    is an SSRF straight into this box's loopback services (Postgres 5432, Redis 6379, MySQL,
    other apps) or cloud metadata (169.254.169.254). An allowlist is more robust than
    filtering private IPs, which DNS rebinding can slip past. Both legitimate uses still work:
    hosted cloud, and a local daemon (always on 11434).
    """
    try:
        u = urllib.parse.urlparse((endpoint or "").strip())
    except Exception:
        return False
    host = (u.hostname or "").lower()
    if u.scheme not in ("http", "https"):
        return False
    if host == "ollama.com" or host.endswith(".ollama.com"):
        return u.scheme == "https"
    if host in ("127.0.0.1", "localhost", "::1"):
        return (u.port or 11434) == 11434   # local Ollama only; not 5432/6379/etc.
    return False


def load_config():
    """{endpoint, model, api_key}. File first, then env override, then defaults."""
    cfg = {"endpoint": DEFAULT_ENDPOINT, "model": DEFAULT_MODEL, "api_key": ""}
    if os.path.exists(_CONFIG_FILE):
        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg.update({k: v for k, v in json.load(f).items() if v})
        except Exception:
            pass
    if os.environ.get("OLLAMA_HOST"):
        cfg["endpoint"] = os.environ["OLLAMA_HOST"]
    if os.environ.get("OLLAMA_MODEL"):
        cfg["model"] = os.environ["OLLAMA_MODEL"]
    if os.environ.get("OLLAMA_API_KEY"):
        cfg["api_key"] = os.environ["OLLAMA_API_KEY"]
    return cfg


def save_config(endpoint=None, model=None, api_key=None):
    cfg = load_config()
    if endpoint is not None:
        cfg["endpoint"] = endpoint or DEFAULT_ENDPOINT
    if model is not None:
        cfg["model"] = model or DEFAULT_MODEL
    if api_key is not None:
        cfg["api_key"] = api_key
    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    try:
        os.chmod(_CONFIG_FILE, 0o600)   # holds the API key
    except OSError:
        pass
    return cfg

FEEL_WORDS = {
    "too_easy": "TOO EASY", "easy": "easy", "right": "just right",
    "hard": "hard", "too_hard": "TOO HARD", None: "not rated",
}

SYSTEM_PROMPT = """You are a strength coach reading one training session on a Speediance cable machine.

Rules you must follow:
- Use ONLY the facts given below. Never invent a number, a weight, or a rep count. If you cite a figure, it must appear in the facts.
- The athlete's own FELT rating outranks every sensor metric. A power/velocity sensor cannot measure effort: a small muscle worked to a burn shows low flat power yet feels hard, and one explosive rep can look like fatigue. When a felt rating and a metric disagree, trust the felt rating and say so.
- Recommend adding weight ONLY where the evidence agrees: every rep completed AND the athlete felt it easy/too-easy AND the device's form scores are solid (roughly 4-5 of 5). If form scores are low or range is shrinking, say hold and fix form first, regardless of the numbers.
- For "level" exercises (Vita), talk in LEVELS and seconds, never weight.
- Where an exercise was not rated, say what you'd want to know rather than guessing.
- Be concise and specific. Group your read by muscle region. Prefer 'hold' over churn — most exercises should stay put most weeks.
- End with at most 2-3 concrete suggestions, each naming the exercise and the felt/factual basis."""


def _feel(notes, name):
    return FEEL_WORDS.get((notes.get("exercises") or {}).get(name))


def build_prompt(snapshot, notes, comparison=None):
    """Compact, factual brief for the model. Pure — no I/O."""
    notes = notes or {}
    lines = []

    overall = FEEL_WORDS.get(notes.get("overall"))
    lines.append(f"Overall the athlete rated the whole session: {overall}.")
    if notes.get("note"):
        lines.append(f"Session note: {notes['note']}")
    lines.append("")

    cmp_by = {c["name"]: c for c in (comparison or [])}

    for region in sorted({e["region"] for e in snapshot["exercises"]}):
        lines.append(f"== {region} ==")
        for e in [x for x in snapshot["exercises"] if x["region"] == region]:
            felt = _feel(notes, e["name"])
            if e["kind"] == "level":
                sets = ", ".join(f"{s['done']}/{s['target']} in {s.get('seconds','?')}s"
                                 for s in e["sets"] if not s["skipped"])
                lines.append(f"- {e['name']} (Vita, level-based): sets {sets}. Felt: {felt}.")
                continue

            sets = ", ".join(
                f"{s['done']}/{s['target']} @ {s['load']:g}"
                + (f" (power {s['power_trend_pct']:+.0f}% peak->last)" if s.get("power_trend_pct") is not None else "")
                for s in e["sets"] if not s["skipped"]
            )
            sc = e["scores"]
            score_str = f"force {sc.get('force_control')}/5, amplitude-stability {sc.get('amplitude_stable')}/5"
            complete = "all reps completed" if e["all_complete"] else "MISSED some reps"
            rom = ""
            if e.get("rom_change_pct") is not None and abs(e["rom_change_pct"]) >= 8:
                rom = f", range {e['rom_change_pct']:+.0f}% across sets"
            cmp = cmp_by.get(e["name"])
            vs = ""
            if cmp and cmp.get("load_delta") not in (None, 0):
                vs = f", top load {cmp['load_delta']:+g} vs last session"
            lines.append(f"- {e['name']}: {complete}. Sets {sets}. {score_str}{rom}{vs}. Felt: {felt}.")
        lines.append("")

    lines.append("Note: 'power peak->last' is a raw sensor trend, NOT a measure of effort or difficulty. "
                 "Weight it far below the athlete's felt rating and rep completion.")
    return "\n".join(lines)


def _headers(cfg):
    h = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        h["Authorization"] = "Bearer " + cfg["api_key"]
    return h


def ask_ollama(prompt, cfg=None, timeout=120):
    """Call Ollama (cloud or local) via /api/chat. Returns (ok, text_or_reason)."""
    cfg = cfg or load_config()
    endpoint = cfg["endpoint"].rstrip("/")
    if not endpoint_allowed(endpoint):
        return False, ("Endpoint not allowed. Use https://ollama.com or a local Ollama at "
                       "http://127.0.0.1:11434.")
    is_cloud = "ollama.com" in endpoint

    if is_cloud and not cfg.get("api_key"):
        return False, "No Ollama Cloud API key set. Add one in Settings (get it from ollama.com/settings/keys)."

    body = json.dumps({
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.3},
    }).encode()

    req = urllib.request.Request(endpoint + "/api/chat", data=body, headers=_headers(cfg))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        return True, ((data.get("message") or {}).get("content") or "").strip()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="ignore")[:200]
        if e.code in (401, 403):
            return False, "Ollama rejected the API key (401/403). Check the key in Settings."
        if e.code == 404:
            hint = f"ollama pull {cfg['model']}" if not is_cloud else "check the model name against ollama.com/search?c=cloud"
            return False, f"Model '{cfg['model']}' not found. {hint}"
        return False, f"Ollama error {e.code}: {detail}"
    except (urllib.error.URLError, ConnectionError, OSError) as e:
        where = "Ollama Cloud" if is_cloud else f"Ollama at {endpoint}"
        return False, f"Couldn't reach {where}: {e}"


def ollama_status(cfg=None):
    """Reachable? Which models are available? (Cloud /api/tags lists local pulls only,
    so for cloud we report reachability via the key rather than a model list.)"""
    cfg = cfg or load_config()
    endpoint = cfg["endpoint"].rstrip("/")
    is_cloud = "ollama.com" in endpoint
    if not endpoint_allowed(endpoint):
        return {"up": False, "cloud": is_cloud, "model": cfg["model"],
                "has_key": bool(cfg.get("api_key")), "models": [], "blocked": True}
    try:
        req = urllib.request.Request(endpoint + "/api/tags", headers=_headers(cfg))
        with urllib.request.urlopen(req, timeout=5) as resp:
            tags = json.loads(resp.read())
        return {"up": True, "cloud": is_cloud, "model": cfg["model"],
                "has_key": bool(cfg.get("api_key")),
                "models": [m.get("name") for m in tags.get("models", [])]}
    except Exception:
        return {"up": False, "cloud": is_cloud, "model": cfg["model"],
                "has_key": bool(cfg.get("api_key")), "models": []}
