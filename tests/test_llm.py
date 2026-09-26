"""OpenRouter wiring checks, no network: python -m tests.test_llm"""
import asyncio
import importlib
import os


def load(**env):
    for k in ("LLM_API_KEY", "LLM_BASE_URL", "FAST_MODEL", "SMART_MODEL", "LLM_MOCK", "OPENAI_API_KEY"):
        os.environ.pop(k, None)
    os.environ.update(env)
    from backend import llm
    return importlib.reload(llm)


class FakeResp:
    def __init__(self, ids):
        self.ids = ids

    def raise_for_status(self):
        pass

    def json(self):
        return {"data": [{"id": i} for i in self.ids]}


class FakeClient:
    ids: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def get(self, url):
        return FakeResp(FakeClient.ids)


def main():
    # OpenAI key: unchanged behaviour
    llm = load(LLM_API_KEY="sk-proj-abc")
    assert not llm.OPENROUTER and llm.FAST_MODEL == "gpt-4.1-mini" and llm.SMART_MODEL == "gpt-4.1"

    # OpenRouter key alone switches provider and uses free models; OpenAI-style names left in Render are ignored
    llm = load(LLM_API_KEY="sk-or-v1-abc", FAST_MODEL="gpt-4.1-mini", SMART_MODEL="gpt-4.1")
    assert llm.OPENROUTER and llm.BASE_URL == "https://openrouter.ai/api/v1"
    assert llm.FAST_MODEL == llm.OR_FAST_DEFAULT[0] and llm.SMART_MODEL == llm.OR_SMART_DEFAULT[0]
    assert llm.default_scoring_passes() == 2
    ms = llm.scoring_models(2)
    assert ms[0] != ms[1] and "openrouter/free" not in ms, ms

    # Paid OpenRouter models can be chosen with the same env vars
    llm = load(LLM_API_KEY="sk-or-v1-abc", FAST_MODEL="openai/gpt-4.1-mini", SMART_MODEL="anthropic/claude-sonnet-5")
    assert llm.FAST_MODEL == "openai/gpt-4.1-mini" and llm.default_scoring_passes() == 1

    # Startup check: retired free models are replaced by what OpenRouter offers today
    llm = load(LLM_API_KEY="sk-or-v1-abc", SMART_MODEL="old/gone-model:free")
    llm.httpx.AsyncClient = FakeClient
    FakeClient.ids = ["nvidia/nemotron-3-super-120b-a12b:free", "cohere/north-mini-code:free",
                      "qwen/qwen3.8-27b:free", "openrouter/free", "openai/gpt-4.1"]
    asyncio.run(llm.resolve_models())
    assert llm.SMART_CHAIN[0] == "nvidia/nemotron-3-super-120b-a12b:free", llm.SMART_CHAIN
    assert "cohere/north-mini-code:free" not in llm.SMART_CHAIN
    assert llm.FAST_CHAIN[0] == "qwen/qwen3.8-27b:free", llm.FAST_CHAIN
    assert llm.MODEL_CHECK["note"]

    # reasoning models: <think> blocks stripped before JSON parsing
    assert llm.parse_json('<think>{"x": 1} maybe</think>\n```json\n{"action": "end"}\n```') == {"action": "end"}
    print("LLM CHECKS PASSED")


if __name__ == "__main__":
    main()
