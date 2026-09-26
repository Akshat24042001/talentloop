"""Thin LLM wrapper. Any OpenAI-compatible endpoint works (OpenAI, Azure, Groq, OpenRouter, Anthropic's OpenAI-compat endpoint).

Set LLM_MOCK=1 to run the whole app without any API key (deterministic fake answers). Useful for testing the flow.
"""
import json
import os
import re

from openai import AsyncOpenAI

MOCK = os.getenv("LLM_MOCK", "0") == "1"
FAST_MODEL = os.getenv("FAST_MODEL", "gpt-4.1-mini")
SMART_MODEL = os.getenv("SMART_MODEL", "gpt-4.1")
JSON_MODE = os.getenv("LLM_JSON_MODE", "1") == "1"

_client = None


def client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "missing",
            base_url=os.getenv("LLM_BASE_URL") or None,
        )
    return _client


def parse_json(text: str) -> dict:
    text = (text or "").strip()
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
    if JSON_MODE:
        kwargs["response_format"] = {"type": "json_object"}
    resp = await client().chat.completions.create(**kwargs)
    return parse_json(resp.choices[0].message.content)
