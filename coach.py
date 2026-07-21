"""Turn a session's deterministic facts into a coaching read, via a chosen LLM provider.

Split in two on purpose:

- build_prompt() / SYSTEM_PROMPT are PURE and unit-tested. They lay out the facts
  progression.py extracted plus the athlete's own felt ratings, and hard-code the lesson
  from 2026-07-14: a power sensor cannot measure effort, so the felt rating outranks any
  metric, and the model must cite the numbers it is given and never invent one.
- Everything below the prompt is a thin, provider-agnostic HTTP client. Providers are
  Ollama (cloud or local), Anthropic (Claude), OpenAI (ChatGPT), Google (Gemini), and
  xAI (Grok). Each has a fixed API host (only Ollama's endpoint is user-editable), so
  models are DISCOVERED live from the provider rather than hardcoded — and a weekly check
  can diff that list to surface newly-released models.

The model interprets; it does not compute. Every number it may cite is pre-computed here.
"""

import datetime
import json
import os
import urllib.error
import urllib.parse
import urllib.request

# Fixed API host per provider. Only Ollama's endpoint is user-editable (it can point at a
# local daemon); the rest are constants, which keeps the SSRF surface to Ollama alone.
PROVIDERS = {
    "ollama":    {"label": "Ollama",             "endpoint": "https://ollama.com",                          "editable": True},
    "anthropic": {"label": "Anthropic (Claude)", "endpoint": "https://api.anthropic.com"},
    "openai":    {"label": "OpenAI (ChatGPT)",   "endpoint": "https://api.openai.com"},
    "gemini":    {"label": "Google (Gemini)",    "endpoint": "https://generativelanguage.googleapis.com"},
    "grok":      {"label": "xAI (Grok)",         "endpoint": "https://api.x.ai"},
}
DEFAULT_PROVIDER = "ollama"
DEFAULT_MODELS = {"ollama": "gpt-oss:120b"}   # others: first from the live list

_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "coach_config.json")


# --------------------------------------------------------------------------- config

def _blank_provider(provider):
    return {"api_key": "", "endpoint": PROVIDERS[provider]["endpoint"], "model": DEFAULT_MODELS.get(provider, "")}


def load_config():
    """Full multi-provider config. Migrates the old single-Ollama shape into providers.ollama."""
    cfg = {
        "provider": DEFAULT_PROVIDER,
        "providers": {p: _blank_provider(p) for p in PROVIDERS},
        "known_models": {},
        "last_model_check": None,
    }
    if os.path.exists(_CONFIG_FILE):
        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
        except Exception:
            saved = {}
        if "providers" in saved:
            for p in PROVIDERS:
                if p in saved.get("providers", {}):
                    cfg["providers"][p].update({k: v for k, v in saved["providers"][p].items() if v is not None})
            cfg["provider"] = saved.get("provider", cfg["provider"])
            cfg["known_models"] = saved.get("known_models", {})
            cfg["last_model_check"] = saved.get("last_model_check")
        elif saved.get("api_key") or saved.get("model"):
            # Legacy {endpoint, model, api_key} — it was Ollama-only.
            cfg["providers"]["ollama"].update({
                "api_key": saved.get("api_key", ""),
                "endpoint": saved.get("endpoint") or PROVIDERS["ollama"]["endpoint"],
                "model": saved.get("model") or DEFAULT_MODELS["ollama"],
            })

    # Env overrides (headless).
    if os.environ.get("OLLAMA_HOST"):
        cfg["providers"]["ollama"]["endpoint"] = os.environ["OLLAMA_HOST"]
    if os.environ.get("OLLAMA_API_KEY"):
        cfg["providers"]["ollama"]["api_key"] = os.environ["OLLAMA_API_KEY"]
    return cfg


def save_config(config):
    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    try:
        os.chmod(_CONFIG_FILE, 0o600)   # holds API keys
    except OSError:
        pass
    return config


def active_provider(config):
    p = config.get("provider", DEFAULT_PROVIDER)
    return p if p in PROVIDERS else DEFAULT_PROVIDER


def provider_cfg(config, provider):
    return config["providers"].get(provider) or _blank_provider(provider)


# --------------------------------------------------------------------------- endpoint safety

def endpoint_allowed(provider, endpoint):
    """A provider may only talk to its own fixed host — or, for Ollama, its allowlist.

    Only Ollama's endpoint is user-editable, so it's the only SSRF surface: an arbitrary
    value would send the Bearer key into this box's loopback services (Postgres, Redis) or
    cloud metadata. An allowlist beats private-IP filtering (DNS rebinding defeats that).
    """
    try:
        u = urllib.parse.urlparse((endpoint or "").strip())
    except Exception:
        return False
    host = (u.hostname or "").lower()
    if u.scheme not in ("http", "https"):
        return False
    if provider == "ollama":
        if host == "ollama.com" or host.endswith(".ollama.com"):
            return u.scheme == "https"
        if host in ("127.0.0.1", "localhost", "::1"):
            return (u.port or 11434) == 11434   # local Ollama only; not 5432/6379/etc.
        return False
    # Fixed-host providers: endpoint must match the constant we ship.
    return endpoint.rstrip("/") == PROVIDERS.get(provider, {}).get("endpoint", "").rstrip("/")


# --------------------------------------------------------------------------- HTTP helpers

def _request(method, url, headers, body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, json.loads(resp.read() or "{}"), None
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="ignore")[:300]
        return False, None, (e.code, detail)
    except (urllib.error.URLError, ConnectionError, OSError) as e:
        return False, None, (0, str(e))


def _auth_headers(provider, pc):
    key = pc.get("api_key", "")
    if provider == "anthropic":
        return {"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"}
    if provider in ("openai", "grok"):
        return {"content-type": "application/json", "Authorization": "Bearer " + key}
    if provider == "gemini":
        return {"content-type": "application/json"}   # key rides in the query string
    # ollama
    h = {"content-type": "application/json"}
    if key:
        h["Authorization"] = "Bearer " + key
    return h


def _err_reason(provider, code, detail):
    if code in (401, 403):
        return f"{PROVIDERS[provider]['label']} rejected the API key ({code}). Check it in Settings."
    if code == 404:
        return f"{PROVIDERS[provider]['label']}: not found (404). The model may be unavailable to this key."
    if code == 429:
        return f"{PROVIDERS[provider]['label']} rate-limited (429). Try again shortly."
    if code == 0:
        return f"Couldn't reach {PROVIDERS[provider]['label']}: {detail}"
    return f"{PROVIDERS[provider]['label']} error {code}: {detail}"


# --------------------------------------------------------------------------- model discovery

def _looks_like_chat_model(mid):
    """OpenAI lists embeddings/tts/whisper/etc.; keep the chat-capable ones."""
    mid = mid.lower()
    if any(x in mid for x in ("embedding", "whisper", "tts", "dall-e", "moderation",
                              "audio", "realtime", "transcribe", "image", "search")):
        return False
    return mid.startswith("gpt") or mid.startswith("chatgpt") or (len(mid) > 1 and mid[0] == "o" and mid[1].isdigit())


def list_models(provider, pc):
    """(ok, [model_id, ...]) discovered live from the provider, or (False, reason)."""
    endpoint = (pc.get("endpoint") or PROVIDERS[provider]["endpoint"]).rstrip("/")
    if not endpoint_allowed(provider, endpoint):
        return False, "Endpoint not allowed."
    if provider != "gemini" and not pc.get("api_key"):
        return False, "No API key set for this provider."

    if provider in ("openai", "grok"):
        ok, data, err = _request("GET", endpoint + "/v1/models", _auth_headers(provider, pc), timeout=20)
        if not ok:
            return False, _err_reason(provider, *err)
        ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
        if provider == "openai":
            ids = [i for i in ids if _looks_like_chat_model(i)]
        return True, sorted(ids)

    if provider == "anthropic":
        ok, data, err = _request("GET", endpoint + "/v1/models?limit=1000", _auth_headers(provider, pc), timeout=20)
        if not ok:
            return False, _err_reason(provider, *err)
        return True, sorted(m.get("id") for m in data.get("data", []) if m.get("id"))

    if provider == "gemini":
        url = endpoint + "/v1beta/models?key=" + urllib.parse.quote(pc.get("api_key", "")) + "&pageSize=1000"
        ok, data, err = _request("GET", url, _auth_headers(provider, pc), timeout=20)
        if not ok:
            return False, _err_reason(provider, *err)
        ids = []
        for m in data.get("models", []):
            if "generateContent" in (m.get("supportedGenerationMethods") or []):
                ids.append((m.get("name") or "").replace("models/", ""))
        return True, sorted(i for i in ids if i)

    # ollama — /api/tags (cloud lists cloud models; local lists pulls)
    ok, data, err = _request("GET", endpoint + "/api/tags", _auth_headers(provider, pc), timeout=20)
    if not ok:
        return False, _err_reason(provider, *err)
    return True, sorted(m.get("name") for m in data.get("models", []) if m.get("name"))


# --------------------------------------------------------------------------- chat

def _chat_provider(provider, pc, prompt, timeout, system=None):
    endpoint = (pc.get("endpoint") or PROVIDERS[provider]["endpoint"]).rstrip("/")
    if not endpoint_allowed(provider, endpoint):
        return False, "Endpoint not allowed."
    model = pc.get("model")
    if not model:
        return False, "No model selected. Pick one in Settings."
    if provider != "gemini" and not pc.get("api_key") and provider != "ollama":
        return False, "No API key set for this provider."

    sys_prompt = system or SYSTEM_PROMPT

    if provider in ("openai", "grok"):
        body = {"model": model, "temperature": 0.3, "messages": [
            {"role": "system", "content": sys_prompt}, {"role": "user", "content": prompt}]}
        ok, data, err = _request("POST", endpoint + "/v1/chat/completions", _auth_headers(provider, pc), body, timeout)
        if not ok:
            return False, _err_reason(provider, *err)
        return True, ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "").strip()

    if provider == "anthropic":
        body = {"model": model, "max_tokens": 2000, "system": sys_prompt,
                "messages": [{"role": "user", "content": prompt}]}
        ok, data, err = _request("POST", endpoint + "/v1/messages", _auth_headers(provider, pc), body, timeout)
        if not ok:
            return False, _err_reason(provider, *err)
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        return True, text.strip()

    if provider == "gemini":
        url = endpoint + "/v1beta/models/" + urllib.parse.quote(model) + ":generateContent?key=" + urllib.parse.quote(pc.get("api_key", ""))
        body = {"system_instruction": {"parts": [{"text": sys_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.3}}
        ok, data, err = _request("POST", url, _auth_headers(provider, pc), body, timeout)
        if not ok:
            return False, _err_reason(provider, *err)
        parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts", [])
        return True, "".join(p.get("text", "") for p in parts).strip()

    # ollama
    body = {"model": model, "stream": False, "options": {"temperature": 0.3},
            "messages": [{"role": "system", "content": sys_prompt}, {"role": "user", "content": prompt}]}
    ok, data, err = _request("POST", endpoint + "/api/chat", _auth_headers(provider, pc), body, timeout)
    if not ok:
        return False, _err_reason(provider, *err)
    return True, ((data.get("message") or {}).get("content") or "").strip()


def chat(prompt, config=None, timeout=120, system=None):
    """Run a prompt through the ACTIVE provider. (ok, text_or_reason).
    `system` overrides the default single-session SYSTEM_PROMPT (used by assessments)."""
    config = config or load_config()
    provider = active_provider(config)
    return _chat_provider(provider, provider_cfg(config, provider), prompt, timeout, system)


def status(config=None):
    """Lightweight reachability/config summary for the active provider (no model call)."""
    config = config or load_config()
    provider = active_provider(config)
    pc = provider_cfg(config, provider)
    has_key = bool(pc.get("api_key")) or provider == "ollama"
    return {"provider": provider, "label": PROVIDERS[provider]["label"],
            "model": pc.get("model"), "has_key": bool(pc.get("api_key")),
            "ready": bool(pc.get("model")) and has_key}


# --------------------------------------------------------------------------- weekly new-model check

def check_new_models(config, force=False, interval_days=7):
    """Diff each keyed provider's live model list against what we last saw.

    Returns (new_by_provider, config) and records the current lists + timestamp. Throttled to
    once per interval unless force=True; today's date is passed in via datetime at call time.
    """
    today = datetime.date.today()
    last = config.get("last_model_check")
    if not force and last:
        try:
            if (today - datetime.date.fromisoformat(last)).days < interval_days:
                return {}, config
        except Exception:
            pass

    known = config.setdefault("known_models", {})
    new_by_provider = {}
    for provider in PROVIDERS:
        pc = provider_cfg(config, provider)
        if provider != "ollama" and not pc.get("api_key"):
            continue
        if provider == "ollama" and not pc.get("api_key"):
            continue
        ok, models = list_models(provider, pc)
        if not ok or not isinstance(models, list):
            continue
        prev = set(known.get(provider, []))
        fresh = [m for m in models if m not in prev]
        if prev and fresh:                    # only report once we have a prior baseline
            new_by_provider[provider] = fresh
        known[provider] = models

    config["last_model_check"] = today.isoformat()
    return new_by_provider, config


# =========================================================================== PURE PROMPT
# Everything below is pure and unit-tested — do not add I/O here.

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
- Loads are given in the athlete's own unit (labelled in the facts). Use that exact unit and never convert between kg and lb, and never assume a unit that is not stated.
- Where an exercise was not rated, say what you'd want to know rather than guessing.
- Be concise and specific. Group your read by muscle region. Prefer 'hold' over churn — most exercises should stay put most weeks.
- End with at most 2-3 concrete suggestions, each naming the exercise and the felt/factual basis."""


def _feel(notes, name):
    return FEEL_WORDS.get((notes.get("exercises") or {}).get(name))


def _exercise_line(e, notes, cmp_by=None, unit=""):
    """One '- ...' fact line for an exercise. Pure. Shared by the single-session
    read and the multi-day assessment so both speak the facts identically.

    `unit` labels every weighted load (e.g. 'lbs'). The API returns loads already in the
    athlete's display unit, so this only LABELS them — it never converts. Without a label
    the model guesses (it printed kg for lbs data). Vita levels are never given a unit."""
    cmp_by = cmp_by or {}
    felt = _feel(notes, e["name"])
    if e["kind"] == "level":
        sets = ", ".join(f"{s['done']}/{s['target']} in {s.get('seconds','?')}s"
                         for s in e["sets"] if not s["skipped"])
        return f"- {e['name']} (Vita, level-based): sets {sets}. Felt: {felt}."
    u = f" {unit}" if unit else ""
    sets = ", ".join(
        f"{s['done']}/{s['target']} @ {s['load']:g}{u}"
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
        vs = f", top load {cmp['load_delta']:+g}{u} vs last session"
    return f"- {e['name']}: {complete}. Sets {sets}. {score_str}{rom}{vs}. Felt: {felt}."


def build_prompt(snapshot, notes, comparison=None, unit=""):
    """Compact, factual brief for the model. Pure — no I/O.

    `unit` (e.g. 'lbs') labels every weighted load. The API already returns loads in the
    athlete's display unit, so this labels them without converting."""
    notes = notes or {}
    lines = []

    overall = FEEL_WORDS.get(notes.get("overall"))
    lines.append(f"Overall the athlete rated the whole session: {overall}.")
    if unit:
        lines.append(f"All loads are in {unit} (the athlete's unit). Use {unit}; do not convert.")
    if notes.get("note"):
        lines.append(f"Session note: {notes['note']}")
    lines.append("")

    cmp_by = {c["name"]: c for c in (comparison or [])}

    for region in sorted({e["region"] for e in snapshot["exercises"]}):
        lines.append(f"== {region} ==")
        for e in [x for x in snapshot["exercises"] if x["region"] == region]:
            lines.append(_exercise_line(e, notes, cmp_by, unit))
        lines.append("")

    lines.append("Note: 'power peak->last' is a raw sensor trend, NOT a measure of effort or difficulty. "
                 "Weight it far below the athlete's felt rating and rep completion.")
    return "\n".join(lines)


ASSESSMENT_SYSTEM_PROMPT = """You are a strength coach reviewing several training sessions on a Speediance cable machine across a period of days.

Rules you must follow:
- Use ONLY the facts given below. Never invent a number, a weight, or a rep count. If you cite a figure, it must appear in the facts.
- The athlete's own FELT rating outranks every sensor metric. A power/velocity sensor cannot measure effort. When a felt rating and a metric disagree, trust the felt rating and say so.
- Recommend adding weight or resistance ONLY where the evidence agrees across the period: reps consistently completed AND the athlete felt it easy/too-easy AND the device's form scores are solid (roughly 4-5 of 5). If form is low or range is shrinking, say hold and fix form first.
- For "level" exercises (Vita), talk in LEVELS and seconds, never weight.
- Loads are given in the athlete's own unit (labelled in the facts). Use that exact unit and never convert between kg and lb, and never assume a unit that is not stated.
- Judge trends only from the dated facts: an exercise's load or reps rising across sessions is improvement; falling or stalling with hard or failed sets is regression or a plateau.
- Prefer 'hold' over churn — most exercises should stay put.

Structure your assessment, grouped by muscle region, to cover:
- Where the athlete is STRONG.
- Where the athlete is WEAK or lagging.
- Where they are IMPROVING (cite the dated trend).
- Where they are REGRESSING or PLATEAUING.
- Where to INCREASE weight or resistance next — name the exercise and the felt/factual basis.
- Any other observations (imbalances, missed reps, form or range notes).

Be concise and specific. Cite exercises by name and cite the facts you rely on."""


def build_assessment_prompt(sessions, days, unit=""):
    """Compact factual brief spanning several sessions. Pure — no I/O.

    sessions: list of {"date", "title", "snapshot": {"exercises": [...]}, "notes": {...}},
    oldest first. Reuses _exercise_line so the facts read identically to a single-session read.
    `unit` (e.g. 'lbs') labels loads; the API already returns them in the athlete's unit."""
    lines = [f"Assessment window: the last {days} day(s). "
             f"{len(sessions)} completed session(s) with data, oldest first."]
    if unit:
        lines.append(f"All loads are in {unit} (the athlete's unit). Use {unit}; do not convert.")
    lines.append("")
    for s in sessions:
        notes = s.get("notes") or {}
        snap = s.get("snapshot") or {}
        exercises = snap.get("exercises", [])
        overall = FEEL_WORDS.get(notes.get("overall"))
        lines.append(f"### {s.get('date', '?')} — {s.get('title', 'Workout')}")
        lines.append(f"Overall felt: {overall}.")
        if notes.get("note"):
            lines.append(f"Session note: {notes['note']}")
        for region in sorted({e["region"] for e in exercises}):
            lines.append(f"== {region} ==")
            for e in [x for x in exercises if x["region"] == region]:
                lines.append(_exercise_line(e, notes, unit=unit))
        lines.append("")
    lines.append("Note: 'power peak->last' is a raw sensor trend, NOT a measure of effort. "
                 "Weight it far below the athlete's felt rating and rep completion.")
    lines.append("")
    lines.append("Now assess performance across this whole window: where the athlete is strong, "
                 "where weak, where improving, where regressing or plateauing, where to increase "
                 "weight or resistance, plus other observations — grouped by muscle region.")
    return "\n".join(lines)
