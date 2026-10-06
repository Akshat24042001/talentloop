"""LLM layer: one place for every AI call, any of several providers, switchable at runtime.

Providers: OpenRouter, OpenAI (ChatGPT), Anthropic (Claude), Google Gemini, xAI (Grok), or any custom OpenAI-compatible
endpoint. A provider is available when its key is set on the server (OPENROUTER_API_KEY, OPENAI_API_KEY,
ANTHROPIC_API_KEY, GEMINI_API_KEY, XAI_API_KEY; LLM_API_KEY still works: "sk-or-..." means OpenRouter, any other
key OpenAI or LLM_BASE_URL). Keys never leave the server and never go in the database.

Three roles, each with its own provider and model list (first = main, the rest = fallbacks in order):
  fast    live interview turns, plans (speed matters)
  smart   scoring, reports, resume reads (quality matters)
  vision  photo and scanned resumes, live-task screenshots (must accept images; optional)
The platform admin picks them in Platform admin > AI models; the choice is stored in the database and applied
without a restart. Without a stored choice the environment decides (FAST_MODEL, SMART_MODEL, VISION_MODEL), with
free OpenRouter models as the default.

Claude goes through Anthropic's own SDK; the other providers speak the OpenAI chat-completions API.
Set LLM_MOCK=1 to run the whole app without any API key (deterministic fake answers).
"""
import asyncio
import base64
import json
import logging
import os
import re
import time

import httpx
from openai import AsyncOpenAI, BadRequestError, NotFoundError, RateLimitError

log = logging.getLogger("llm")

from . import appenv  # noqa: E402
MOCK = appenv.allowed_in_dev("LLM_MOCK")     # the fake AI never runs in production
JSON_MODE = (os.getenv("LLM_JSON_MODE") or "1") == "1"
OPENROUTER_URL = "https://openrouter.ai/api/v1"
_LEGACY_KEY = (os.getenv("LLM_API_KEY") or "").strip()
_CUSTOM_URL = (os.getenv("LLM_BASE_URL") or "").strip()

PROVIDERS: dict[str, dict] = {
    "openrouter": {"label": "OpenRouter", "kind": "openai", "base_url": OPENROUTER_URL, "env": "OPENROUTER_API_KEY",
                   "note": "Hundreds of models from every lab behind one key, including free ones.", "site": "https://openrouter.ai/keys"},
    "openai": {"label": "OpenAI (ChatGPT)", "kind": "openai", "base_url": "https://api.openai.com/v1", "env": "OPENAI_API_KEY",
               "note": "GPT models.", "site": "https://platform.openai.com/api-keys"},
    "anthropic": {"label": "Anthropic (Claude)", "kind": "anthropic", "base_url": "", "env": "ANTHROPIC_API_KEY",
                  "note": "Claude models, through Anthropic's own SDK.", "site": "https://console.anthropic.com/settings/keys"},
    "gemini": {"label": "Google Gemini", "kind": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
               "env": "GEMINI_API_KEY", "note": "Gemini models (Google AI Studio key).", "site": "https://aistudio.google.com/apikey"},
    "xai": {"label": "xAI (Grok)", "kind": "openai", "base_url": "https://api.x.ai/v1", "env": "XAI_API_KEY",
            "note": "Grok models.", "site": "https://console.x.ai"},
    "custom": {"label": "Custom (OpenAI-compatible)", "kind": "openai", "base_url": _CUSTOM_URL if "openrouter.ai" not in _CUSTOM_URL else "",
               "env": "LLM_API_KEY", "note": "Any OpenAI-compatible endpoint set in LLM_BASE_URL (Groq, Azure, a local server...).", "site": ""},
}

# Free OpenRouter models, best first (checked against OpenRouter's free list on 2026-09-26). The free list changes
# almost weekly, so models missing from the catalogue at startup are replaced automatically (resolve_models).
OR_FAST_DEFAULT = ["qwen/qwen3.8-27b:free", "nvidia/nemotron-3.5-lightning:free", "openrouter/free"]
OR_SMART_DEFAULT = ["nvidia/nemotron-3-ultra-550b-a55b:free", "nvidia/nemotron-3-super-120b-a12b:free", "openrouter/free"]
# Suggested starting points when switching provider (the admin page lists every model the provider offers).
SUGGEST = {
    "openrouter": {"fast": OR_FAST_DEFAULT, "smart": OR_SMART_DEFAULT, "vision": []},
    "openai": {"fast": ["gpt-4.1-mini"], "smart": ["gpt-4.1"], "vision": ["gpt-4.1-mini"]},
    "anthropic": {"fast": ["claude-haiku-4-5"], "smart": ["claude-opus-5-5"], "vision": ["claude-opus-5-5"]},
    "gemini": {"fast": [], "smart": [], "vision": []},
    "xai": {"fast": [], "smart": [], "vision": []},
    "custom": {"fast": [], "smart": [], "vision": []},
}
_AUTO_PICK_HINTS = ["nemotron-3-ultra", "nemotron-3-super", "qwen3", "gemma-4-31b", "inkling", "nemotron", "gemma"]
_NOT_CHAT = ("code", "content-safety", "lyria", "omni", "-vl", "vision", "embed")


def provider_key(pid: str) -> str:
    p = PROVIDERS.get(pid) or {}
    key = (os.getenv(p.get("env", "")) or "").strip() if p.get("env") != "LLM_API_KEY" else ""
    if key:
        return key
    if pid == "openrouter" and _LEGACY_KEY.startswith("sk-or-"):
        return _LEGACY_KEY
    if pid == "openai" and _LEGACY_KEY and not _LEGACY_KEY.startswith("sk-or-") and not _CUSTOM_URL:
        return _LEGACY_KEY
    if pid == "custom" and p.get("base_url") and _LEGACY_KEY:
        return _LEGACY_KEY
    return ""


def available(pid: str) -> bool:
    return bool(provider_key(pid)) and (pid != "custom" or bool(PROVIDERS["custom"]["base_url"]))


def _env_list(name: str) -> list[str]:
    return [m.strip() for m in os.getenv(name, "").split(",") if m.strip()]


def _default_provider() -> str:
    if _CUSTOM_URL and "openrouter.ai" not in _CUSTOM_URL and _LEGACY_KEY:
        return "custom"
    for pid in ("openrouter", "openai", "anthropic", "gemini", "xai"):
        if available(pid):
            return pid
    return "openrouter"


def _env_config() -> dict:
    pid = _default_provider()
    sug = SUGGEST.get(pid, {})

    def chain(env: str, role: str) -> list[str]:
        own = _env_list(env)
        if pid == "openrouter":
            own = [m for m in own if "/" in m]    # OpenAI-style names ("gpt-4.1") aren't OpenRouter ids
        return own or list(sug.get(role) or [])
    return {"fast": {"provider": pid, "models": chain("FAST_MODEL", "fast")},
            "smart": {"provider": pid, "models": chain("SMART_MODEL", "smart")},
            "vision": {"provider": pid, "models": chain("VISION_MODEL", "vision") if os.getenv("VISION_MODEL") else []}}


# --- the live configuration (module attributes other modules read at call time) -----------------------------------
CONFIG: dict = {}
SOURCE = "environment"            # or "admin" once the platform admin saves a choice
FAST_CHAIN: list[str] = []
SMART_CHAIN: list[str] = []
VISION_CHAIN: list[str] = []
FAST_MODEL = SMART_MODEL = VISION_MODEL = ""
FAST_PROVIDER = SMART_PROVIDER = VISION_PROVIDER = ""
OPENROUTER = False                # the smart role runs on OpenRouter (free-model behaviour, router fallbacks)
BASE_URL = ""
API_KEY = ""
MODEL_CHECK = {"checked": False, "note": ""}
_clients: dict[str, object] = {}


def apply_config(cfg: dict, source: str = "environment") -> None:
    """Switch providers and models now (no restart)."""
    global CONFIG, SOURCE, FAST_CHAIN, SMART_CHAIN, VISION_CHAIN, FAST_MODEL, SMART_MODEL, VISION_MODEL
    global FAST_PROVIDER, SMART_PROVIDER, VISION_PROVIDER, OPENROUTER, BASE_URL, API_KEY
    base = _env_config()
    merged = {r: {"provider": (cfg.get(r) or {}).get("provider") or base[r]["provider"],
                  "models": [m for m in ((cfg[r].get("models") or []) if isinstance(cfg.get(r), dict) else base[r]["models"]) if isinstance(m, str) and m.strip()][:4]}
              for r in ("fast", "smart", "vision")}
    CONFIG, SOURCE = merged, source
    FAST_PROVIDER, SMART_PROVIDER, VISION_PROVIDER = (merged[r]["provider"] for r in ("fast", "smart", "vision"))
    FAST_CHAIN, SMART_CHAIN, VISION_CHAIN = (merged[r]["models"] for r in ("fast", "smart", "vision"))
    FAST_MODEL, SMART_MODEL = (FAST_CHAIN or [""])[0], (SMART_CHAIN or [""])[0]
    VISION_MODEL = (VISION_CHAIN or [""])[0] if available(VISION_PROVIDER) else ""
    OPENROUTER = SMART_PROVIDER == "openrouter"
    BASE_URL = PROVIDERS.get(SMART_PROVIDER, {}).get("base_url", "")
    API_KEY = provider_key(SMART_PROVIDER)
    _clients.clear()


apply_config({})


def load_saved() -> None:
    """Apply the platform admin's saved choice (if any) from the database. Called at startup."""
    try:
        from . import db
        with db.session() as s:
            row = s.get(db.AppSecret, "llm_config")
            if row and row.value:
                apply_config(json.loads(row.value), "admin")
    except Exception as e:
        log.warning("could not load the saved model choice: %s", e)


def save(cfg: dict) -> None:
    from . import db
    clean = {r: {"provider": str((cfg.get(r) or {}).get("provider") or ""), "models": [str(m).strip()[:120] for m in (cfg.get(r) or {}).get("models") or [] if str(m).strip()][:4]}
             for r in ("fast", "smart", "vision")}
    with db.session() as s:
        row = s.get(db.AppSecret, "llm_config")
        if row:
            row.value = json.dumps(clean)
        else:
            s.add(db.AppSecret(name="llm_config", value=json.dumps(clean)))
    apply_config(clean, "admin")


def reset() -> None:
    from . import db
    with db.session() as s:
        row = s.get(db.AppSecret, "llm_config")
        if row:
            s.delete(row)
    apply_config({})


def provider_of(model: str) -> str:
    for chain, pid in ((FAST_CHAIN, FAST_PROVIDER), (SMART_CHAIN, SMART_PROVIDER), (VISION_CHAIN, VISION_PROVIDER)):
        if model in chain:
            return pid
    return SMART_PROVIDER


def _chain_of(model: str) -> list[str]:
    for chain in (FAST_CHAIN, SMART_CHAIN, VISION_CHAIN):
        if model in chain:
            i = chain.index(model)
            return chain[i:] + chain[:i]
    return [model]


def client(pid: str | None = None):
    pid = pid or SMART_PROVIDER
    if pid not in _clients:
        p = PROVIDERS[pid]
        if p["kind"] == "anthropic":
            from anthropic import AsyncAnthropic
            _clients[pid] = AsyncAnthropic(api_key=provider_key(pid) or "missing", max_retries=1)
        else:
            headers = {"X-Title": "TalentLoop AI Interview"} if pid == "openrouter" else None
            _clients[pid] = AsyncOpenAI(api_key=provider_key(pid) or "missing", base_url=p["base_url"] or None, default_headers=headers, max_retries=1)
    return _clients[pid]


async def list_models(pid: str) -> list[dict]:
    """Every model the provider offers right now: [{id, name, free, vision}] (free/vision when the provider says)."""
    p = PROVIDERS[pid]
    out = []
    if pid == "openrouter":
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{OPENROUTER_URL}/models")
            r.raise_for_status()
        for m in r.json().get("data", []):
            pr = m.get("pricing") or {}
            free = m["id"].endswith(":free") or (str(pr.get("prompt")) in ("0", "0.0") and str(pr.get("completion")) in ("0", "0.0"))
            mods = ((m.get("architecture") or {}).get("input_modalities")) or []
            out.append({"id": m["id"], "name": m.get("name") or m["id"], "free": free, "vision": "image" in mods,
                        "context": m.get("context_length")})
        return sorted(out, key=lambda x: (not x["free"], x["id"]))
    if not available(pid):
        raise ValueError(f"Set {p['env']} on the server to use {p['label']}.")
    if p["kind"] == "anthropic":
        async for m in client(pid).models.list():
            out.append({"id": m.id, "name": getattr(m, "display_name", m.id) or m.id, "free": False, "vision": True})
        return out
    res = await client(pid).models.list()
    for m in getattr(res, "data", []) or []:
        mid = m.id.removeprefix("models/") if pid == "gemini" else m.id
        out.append({"id": mid, "name": mid, "free": False, "vision": None})
    return sorted(out, key=lambda x: x["id"])


async def resolve_models() -> None:
    """OpenRouter only: keep configured models that exist, otherwise pick any available free model."""
    global FAST_CHAIN, SMART_CHAIN, FAST_MODEL, SMART_MODEL
    if MOCK or "openrouter" not in (FAST_PROVIDER, SMART_PROVIDER):
        return
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{OPENROUTER_URL}/models")
            r.raise_for_status()
            ids = [m["id"] for m in r.json().get("data", [])]
    except Exception as e:
        MODEL_CHECK.update(checked=False, note=f"Could not list OpenRouter models ({e}); using configured ones")
        log.warning(MODEL_CHECK["note"])
        return
    have = set(ids)
    free = [i for i in ids if i.endswith(":free")]

    def fix(chain: list[str]) -> list[str]:
        kept = [m for m in chain if m in have]
        if kept:
            return kept[:4]
        for hint in _AUTO_PICK_HINTS:
            picks = [i for i in free if hint in i and not any(x in i for x in _NOT_CHAT)]
            if picks:
                return picks[:2] + (["openrouter/free"] if "openrouter/free" in have else [])
        return (["openrouter/free"] if "openrouter/free" in have else free[:3]) or chain

    notes = []
    if FAST_PROVIDER == "openrouter":
        new = fix(FAST_CHAIN)
        if new != FAST_CHAIN:
            notes.append(f"fast: {', '.join(new)}")
        FAST_CHAIN = new
    if SMART_PROVIDER == "openrouter":
        new = fix(SMART_CHAIN)
        if new != SMART_CHAIN:
            notes.append(f"smart: {', '.join(new)}")
        SMART_CHAIN = new
    FAST_MODEL, SMART_MODEL = (FAST_CHAIN or [""])[0], (SMART_CHAIN or [""])[0]
    MODEL_CHECK.update(checked=True, note=("Adjusted models to what OpenRouter offers. " + "; ".join(notes)) if notes else "")
    log.info("models: fast=%s:%s smart=%s:%s", FAST_PROVIDER, FAST_CHAIN, SMART_PROVIDER, SMART_CHAIN)


def plan_models() -> list[str]:
    """Models for interview plans, fastest first. PLAN_MODEL (comma-separated) overrides. Plans must come back
    in well under 30 seconds, so the fast chain leads; the smart models are slow on free tiers."""
    own = _env_list("PLAN_MODEL")
    if FAST_PROVIDER == "openrouter":
        own = [m for m in own if "/" in m]
    if own:
        return own
    return list(dict.fromkeys(FAST_CHAIN + SMART_CHAIN))


def scoring_models(passes: int) -> list[str]:
    """Different models per scoring pass: two models disagreeing is a far better warning sign
    than one model disagreeing with itself. Skips the generic router when a named model exists."""
    named = [m for m in SMART_CHAIN if m != "openrouter/free"] or SMART_CHAIN
    return [named[i % len(named)] for i in range(passes)]


def default_scoring_passes() -> int:
    # Free models are less reliable, so score with two of them and flag disagreements.
    return 2 if any(m.endswith(":free") or m == "openrouter/free" for m in SMART_CHAIN) else 1


def parse_json(text: str) -> dict:
    text = (text or "").strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()  # reasoning models
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


# --- calls ---------------------------------------------------------------------------------------------------------
async def _anthropic_json(pid: str, model: str, system: str, content, max_tokens: int, timeout: float) -> dict:
    """Claude through Anthropic's SDK. No temperature: current Claude models reject sampling parameters. A roomy
    max_tokens because thinking (always on for some models) counts toward it; billing is by tokens actually used."""
    resp = await client(pid).with_options(timeout=timeout).messages.create(
        model=model, max_tokens=max(max_tokens, 16000), system=system + "\n\nReply with the JSON object only.",
        messages=[{"role": "user", "content": content}])
    if resp.stop_reason == "refusal":
        raise ValueError("Claude declined this request")
    text = "".join(b.text for b in resp.content if b.type == "text")
    out = parse_json(text)
    if not isinstance(out, dict):
        raise ValueError("model did not return a JSON object")
    return out


async def _openai_json(pid: str, kwargs: dict) -> dict:
    for _ in range(3):
        try:
            resp = await client(pid).chat.completions.create(**kwargs)
            break
        except (BadRequestError, NotFoundError) as e:
            msg = str(e)
            if "response_format" in kwargs and ("response_format" in msg or "No endpoints" in msg or "json" in msg.lower()):
                kwargs.pop("response_format")  # many models don't support JSON mode; the prompt still asks for JSON
                continue
            if "max_tokens" in kwargs and ("max_tokens" in msg or "temperature" in msg):
                # Newer OpenAI models (gpt-5, o-series) reject max_tokens and a custom temperature.
                kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
                kwargs.pop("temperature", None)
                continue
            raise
    else:
        raise RuntimeError("LLM request failed after retries")
    model = kwargs.get("model", "?")
    if not resp.choices:
        raise BadAnswer(f"{model} returned no answer: {getattr(resp, 'error', '')}")
    ch = resp.choices[0]
    cut = getattr(ch, "finish_reason", "") == "length"
    text = (ch.message.content or "") if ch.message else ""
    if not text.strip():
        raise BadAnswer(f"{model} returned an empty answer" + (" (it ran out of room, usually while reasoning)" if cut else ""))
    try:
        out = parse_json(text)
    except (ValueError, json.JSONDecodeError):
        raise BadAnswer(f"{model} answered, but not in the expected JSON" + (" (the answer was cut off)" if cut else ""))
    if not isinstance(out, dict):
        raise BadAnswer(f"{model} did not return a JSON object")
    return out


class BadAnswer(ValueError):
    """The provider answered, but the answer is empty, cut off or not JSON (as opposed to an HTTP error)."""


class QuotaExhausted(RuntimeError):
    """The provider's daily allowance (for example OpenRouter's free-model limit) is used up."""


_BLOCKED: dict[str, tuple[float, str]] = {}      # provider -> (until, why): after a daily-limit refusal, don't keep knocking
BLOCK_SEC = 300
LAST_BACKUP: dict = {}                           # the last time a backup provider answered (shown to the platform admin)


def _daily_limit(e: Exception) -> bool:
    m = str(e).lower()
    return "per-day" in m or "per day" in m or "daily" in m or ("quota" in m and "exceed" in m)


def _blocked(pid: str) -> str:
    until, why = _BLOCKED.get(pid, (0.0, ""))
    return why if until > time.time() else ""


def backups_on() -> bool:
    return (os.getenv("LLM_BACKUP") or "on").strip().lower() not in ("off", "0", "false", "no")


def _backup_targets(model: str, role_hint: str = "") -> list[tuple[str, str]]:
    """Other providers whose key is set, each with its suggested model for this kind of work: used only when the main
    provider fails a one-off job (never a live interview turn). Turn off with LLM_BACKUP=off."""
    main = provider_of(model)
    role = role_hint or ("fast" if model in FAST_CHAIN else "smart")
    out = []
    for pid in ("anthropic", "openai", "gemini", "xai", "openrouter", "custom"):
        if pid == main or not available(pid) or _blocked(pid):
            continue
        ms = SUGGEST.get(pid, {}).get(role) or []
        if ms:
            out.append((pid, ms[0]))
    return out


async def complete_json(system: str, user: str, model: str, temperature: float = 0.2,
                        max_tokens: int = 1500, timeout: float = 60.0, fallbacks: list[str] | None = None,
                        fast: bool = False, backup: bool = True) -> dict:
    """fallbacks: models to try if `model` fails (None = the rest of its chain, [] = none).
    fast: ask for low/hidden reasoning and the highest-throughput provider (plans, live turns).
    backup: when the main provider fails, try another configured provider (not for live interview turns)."""
    try:
        return await _complete_json(system, user, model, temperature, max_tokens, timeout, fallbacks, fast)
    except Exception as first:
        if not backup or not backups_on() or MOCK:
            raise
        for pid, m in _backup_targets(model):
            try:
                out = await _complete_json(system, user, m, temperature, max_tokens, timeout, [], fast, pid=pid)
            except Exception as e:
                log.warning("backup %s %s failed too: %s", pid, m, e)
                continue
            LAST_BACKUP.update(provider=pid, model=m, at=time.time(), because=str(first)[:200])
            log.warning("AI backup used: %s %s answered after %s %s failed (%s)", pid, m, provider_of(model), model, str(first)[:120])
            out.setdefault("_backup", f"{pid}:{m}")
            return out
        raise first


async def _complete_json(system: str, user: str, model: str, temperature: float = 0.2,
                         max_tokens: int = 1500, timeout: float = 60.0, fallbacks: list[str] | None = None,
                         fast: bool = False, pid: str | None = None) -> dict:
    pid = pid or provider_of(model)
    if (why := _blocked(pid)):
        raise QuotaExhausted(why)
    chain = [model] + ([m for m in fallbacks if m != model] if fallbacks is not None else [m for m in _chain_of(model) if m != model])
    if PROVIDERS[pid]["kind"] == "anthropic":
        err = None
        for m in chain[:3]:
            try:
                return await _anthropic_json(pid, m, system, user, max_tokens, timeout)
            except Exception as e:                 # try the next model in the chain
                err = e
                log.warning("Claude %s failed: %s", m, e)
        raise err
    # Room for reasoning models (OpenRouter free models, OpenAI o-series/gpt-5): their thinking counts against this.
    kwargs = dict(model=model, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                  temperature=temperature, max_tokens=max(max_tokens, 1024 if (fast or model == FAST_MODEL) else 2048), timeout=timeout)
    if pid == "openrouter":
        extra = {}
        if len(chain) > 1:
            extra["models"] = chain[:3]           # OpenRouter itself moves on when a model is down or rate-limited
        # Reasoning models (common among free OpenRouter models) count their thinking against max_tokens: with a small
        # budget they think, run out and return an empty or cut-off answer. So: low, hidden reasoning, and room for it.
        # max_tokens is a ceiling, not a charge: only tokens actually produced are billed.
        extra["reasoning"] = {"effort": "low", "exclude": True}
        if fast:
            extra["provider"] = {"sort": "throughput"}
        if extra:
            kwargs["extra_body"] = extra
    if JSON_MODE:
        kwargs["response_format"] = {"type": "json_object"}
    if pid == "openrouter":
        try:
            return await _openai_json(pid, kwargs)
        except BadAnswer as e:                     # an answer, but unusable: OpenRouter won't fall back by itself
            err = e
            log.warning("%s", e)
        except RateLimitError as e:
            if _daily_limit(e):                    # every model of this account shares the limit: don't try them all
                _BLOCKED[pid] = (time.time() + BLOCK_SEC, f"OpenRouter's daily free-model limit is used up ({str(e)[:100]})")
                log.warning("openrouter daily limit reached: %s", e)
                raise QuotaExhausted(_BLOCKED[pid][1]) from e
            raise
        for m in chain[1:3]:
            k = {**kwargs, "model": m, "extra_body": {x: v for x, v in kwargs.get("extra_body", {}).items() if x != "models"}}
            try:
                return await _openai_json(pid, k)
            except RateLimitError as e:
                if _daily_limit(e):
                    _BLOCKED[pid] = (time.time() + BLOCK_SEC, f"OpenRouter's daily free-model limit is used up ({str(e)[:100]})")
                    raise QuotaExhausted(_BLOCKED[pid][1]) from e
                err = e
            except Exception as e:
                err = e
                log.warning("openrouter %s failed: %s", m, e)
        raise err
    if len(chain) == 1:
        return await _openai_json(pid, kwargs)
    err = None
    for m in chain[:3]:                            # other providers: try the chain ourselves
        try:
            return await _openai_json(pid, {**kwargs, "model": m})
        except Exception as e:
            err = e
            log.warning("%s %s failed: %s", pid, m, e)
    raise err


async def complete_json_vision(system: str, text: str, images: list[bytes], model: str | None = None,
                               max_tokens: int = 1500, timeout: float = 120.0) -> dict:
    model = model or VISION_MODEL
    if not model:
        raise ValueError("No vision model is set (Platform admin > AI models, or VISION_MODEL).")
    pid = VISION_PROVIDER if model in VISION_CHAIN or not VISION_CHAIN else provider_of(model)
    b64 = [base64.b64encode(b).decode() for b in images]
    if PROVIDERS[pid]["kind"] == "anthropic":
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": x}} for x in b64] + [{"type": "text", "text": text}]
        return await _anthropic_json(pid, model, system, content, max_tokens, timeout)
    parts = [{"type": "text", "text": text}] + [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + x}} for x in b64]
    kwargs = dict(model=model, messages=[{"role": "system", "content": system}, {"role": "user", "content": parts}],
                  temperature=0.1, max_tokens=max_tokens, timeout=timeout)
    if JSON_MODE:
        kwargs["response_format"] = {"type": "json_object"}
    return await _openai_json(pid, kwargs)


async def test_role(role: str) -> dict:
    """One tiny real request on a role's main model: proves the key, the model id and the JSON reply work."""
    chain = {"fast": FAST_CHAIN, "smart": SMART_CHAIN, "vision": VISION_CHAIN}[role]
    if not chain:
        return {"ok": False, "error": "No model set for this role."}
    pid = CONFIG[role]["provider"]
    if not available(pid):
        return {"ok": False, "error": f"{PROVIDERS[pid]['env']} is not set on the server."}
    t = time.time()
    try:
        if role == "vision":
            from PIL import Image
            import io
            buf = io.BytesIO()
            Image.new("RGB", (64, 32), "red").save(buf, "JPEG")
            out = await complete_json_vision('Output ONLY JSON: {"color": str}', "What colour is this image?", [buf.getvalue()], chain[0], 200, 60)
        else:
            out = await complete_json('Output ONLY JSON: {"ok": true, "word": str}', "Reply with the word 'ready'.", chain[0], 0, 200, 60, fallbacks=[])
        return {"ok": True, "model": chain[0], "seconds": round(time.time() - t, 1), "reply": out}
    except Exception as e:
        return {"ok": False, "model": chain[0], "seconds": round(time.time() - t, 1), "error": f"{type(e).__name__}: {str(e)[:300]}"}
