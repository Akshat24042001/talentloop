"""Thin LLM wrapper. Any OpenAI-compatible endpoint works (OpenAI, OpenRouter, Groq, Azure, ...).

OpenRouter: put your OpenRouter key (starts with "sk-or-") in LLM_API_KEY. Nothing else is needed:
the base URL is set automatically and free models are used by default. At startup the server asks
OpenRouter which models exist and replaces any configured model that has disappeared, so a
retired free model doesn't break interviews.

Set LLM_MOCK=1 to run the whole app without any API key (deterministic fake answers).
"""
import json
import logging
import os
import re

import httpx
from openai import AsyncOpenAI, BadRequestError, NotFoundError

log = logging.getLogger("llm")

MOCK = os.getenv("LLM_MOCK", "0") == "1"
API_KEY = (os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
OPENROUTER_URL = "https://openrouter.ai/api/v1"
BASE_URL = (os.getenv("LLM_BASE_URL") or "").strip() or (OPENROUTER_URL if API_KEY.startswith("sk-or-") else "")
OPENROUTER = "openrouter.ai" in BASE_URL
JSON_MODE = os.getenv("LLM_JSON_MODE", "1") == "1"

# Free OpenRouter models, best first (checked against OpenRouter's free list on 2026-09-26).
# The live turn needs speed; plan and scoring need quality. "openrouter/free" is OpenRouter's own
# router over whatever free models are up, used as the last resort. Models missing from the
# catalogue at startup are dropped automatically, because the free list changes almost weekly.
OR_FAST_DEFAULT = ["qwen/qwen3.8-27b:free", "nvidia/nemotron-3.5-lightning:free", "openrouter/free"]
OR_SMART_DEFAULT = ["nvidia/nemotron-3-ultra-550b-a55b:free", "nvidia/nemotron-3-super-120b-a12b:free",
                    "openrouter/free"]
_AUTO_PICK_HINTS = ["nemotron-3-ultra", "nemotron-3-super", "qwen3", "gemma-4-31b", "inkling", "nemotron", "gemma"]
_NOT_CHAT = ("code", "content-safety", "lyria", "omni", "-vl", "vision", "embed")


def _env_list(name: str) -> list[str]:
    return [m.strip() for m in os.getenv(name, "").split(",") if m.strip()]


def _chain(env_name: str, openai_default: str, or_default: list[str]) -> list[str]:
    chain = _env_list(env_name)
    if OPENROUTER:
        # OpenAI-style names ("gpt-4.1") are not valid on OpenRouter ("openai/gpt-4.1" is, but paid).
        chain = [m for m in chain if "/" in m]
        return chain or list(or_default)
    return chain or [openai_default]


FAST_CHAIN = _chain("FAST_MODEL", "gpt-4.1-mini", OR_FAST_DEFAULT)
SMART_CHAIN = _chain("SMART_MODEL", "gpt-4.1", OR_SMART_DEFAULT)
FAST_MODEL = FAST_CHAIN[0]
SMART_MODEL = SMART_CHAIN[0]
MODEL_CHECK = {"checked": False, "note": ""}

_client = None


def client() -> AsyncOpenAI:
    global _client
    if _client is None:
        headers = {"X-Title": "TalentLoop AI Interview"} if OPENROUTER else None
        _client = AsyncOpenAI(api_key=API_KEY or "missing", base_url=BASE_URL or None,
                              default_headers=headers, max_retries=1)
    return _client


async def resolve_models() -> None:
    """OpenRouter only: keep configured models that exist, otherwise pick any available free model."""
    global FAST_CHAIN, SMART_CHAIN, FAST_MODEL, SMART_MODEL
    if MOCK or not OPENROUTER:
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
            return kept[:3]
        for hint in _AUTO_PICK_HINTS:
            picks = [i for i in free if hint in i and not any(x in i for x in _NOT_CHAT)]
            if picks:
                return picks[:2] + (["openrouter/free"] if "openrouter/free" in have else [])
        return (["openrouter/free"] if "openrouter/free" in have else free[:3]) or chain

    notes = []
    for label, old in (("fast", FAST_CHAIN), ("smart", SMART_CHAIN)):
        new = fix(old)
        if new != old:
            notes.append(f"{label}: {', '.join(new)}")
        if label == "fast":
            FAST_CHAIN = new
        else:
            SMART_CHAIN = new
    FAST_MODEL, SMART_MODEL = FAST_CHAIN[0], SMART_CHAIN[0]
    MODEL_CHECK.update(checked=True, note=("Adjusted models to what OpenRouter offers. " + "; ".join(notes)) if notes else "")
    log.info("OpenRouter models: fast=%s smart=%s", FAST_CHAIN, SMART_CHAIN)


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


async def complete_json(system: str, user: str, model: str, temperature: float = 0.2,
                        max_tokens: int = 1500, timeout: float = 60.0) -> dict:
    kwargs = dict(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    if OPENROUTER:
        # OpenRouter tries the next model if the first is rate-limited or down (common on free models).
        chain = [model]
        for c in (FAST_CHAIN, SMART_CHAIN):
            if model in c:  # fall back through the rest of this model's chain
                i = c.index(model)
                chain = c[i:] + c[:i]
                break
        extra = {}
        if len(chain) > 1:
            extra["models"] = chain[:3]
        if model == FAST_MODEL:
            # Live turns: long hidden "thinking" would add seconds of silence on a voice call.
            extra["reasoning"] = {"effort": "low", "exclude": True}
        if extra:
            kwargs["extra_body"] = extra
    if JSON_MODE:
        kwargs["response_format"] = {"type": "json_object"}
    for _ in range(3):
        try:
            resp = await client().chat.completions.create(**kwargs)
            break
        except (BadRequestError, NotFoundError) as e:
            msg = str(e)
            if "response_format" in kwargs and ("response_format" in msg or "No endpoints" in msg
                                                 or "json" in msg.lower()):
                kwargs.pop("response_format")  # many free models don't support JSON mode; the prompt still asks for JSON
                continue
            if "max_tokens" in kwargs and ("max_tokens" in msg or "temperature" in msg):
                # Newer OpenAI models (gpt-5, o-series) reject max_tokens and a custom temperature.
                kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
                kwargs.pop("temperature", None)
                continue
            raise
    else:
        raise RuntimeError("LLM request failed after retries")
    if not resp.choices:
        raise ValueError(f"LLM returned no choices: {getattr(resp, 'error', '')}")
    out = parse_json(resp.choices[0].message.content)
    if not isinstance(out, dict):
        raise ValueError("model did not return a JSON object")
    return out
