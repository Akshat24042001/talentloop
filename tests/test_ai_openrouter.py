"""The hiring features' real AI path with an OpenRouter key (no network):  python -m tests.test_ai_openrouter

A fake OpenRouter (OpenAI-compatible) server records every request. Checks that AI match reports and
"Write with AI" use the OpenRouter free-model chain with fallbacks, survive a model that rejects JSON mode,
cache reports, respect the per-run budget, and degrade cleanly when the AI provider fails."""
import json
import os
import tempfile
import threading
import time

os.environ.update({"LLM_MOCK": "0", "LLM_API_KEY": "sk-or-test-key", "LLM_BASE_URL": "", "FAST_MODEL": "", "SMART_MODEL": "",
                   "DATA_DIR": tempfile.mkdtemp(), "DATABASE_URL": os.getenv("TEST_DATABASE_URL", ""), "ADMIN_KEY": "",
                   "PUBLIC_URL": "https://example.com", "VAPI_PUBLIC_KEY": "pk"})

import uvicorn  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402

from backend import llm  # noqa: E402
from backend.main import app  # noqa: E402

PORT = 8797
CALLS: list[dict] = []
MODE = {"fail": False}
fake = FastAPI()


@fake.post("/api/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    CALLS.append(body)
    if MODE["fail"]:
        return JSONResponse({"error": {"message": "Rate limit exceeded: free-models-per-day", "code": 429}}, status_code=429)
    if "response_format" in body and body["model"].startswith("nvidia/"):
        return JSONResponse({"error": {"message": "response_format is not supported by this model", "code": 400}}, status_code=400)
    sys_prompt = body["messages"][0]["content"]
    if "assess how well a candidate fits" in sys_prompt:
        out = {"score": 81, "verdict": "strong", "summary": "Solid backend engineer.", "strengths": ["Java at scale"], "gaps": ["No Kafka"],
               "risks": [], "interview_questions": ["Tell me about Kafka."]}
    else:
        out = {"summary": "Build payments.", "responsibilities": ["Design APIs", "Own services"], "first_90_days": ["Ship"], "nice_to_have_skills": ["Kafka"],
               "day_in_life": "Code and review."}
    return {"id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "<think>hmm</think>```json\n" + json.dumps(out) + "\n```"}, "finish_reason": "stop"}]}


def ok(r, code=200):
    assert r.status_code == code, f"{r.request.url.path}: {r.status_code} {r.text[:300]}"
    return r.json()


def main():
    threading.Thread(target=uvicorn.run, args=(fake,), kwargs={"port": PORT, "log_level": "warning"}, daemon=True).start()
    time.sleep(1.5)
    # The key alone switches on OpenRouter and its free models; only the network address is redirected to the fake.
    assert llm.OPENROUTER and llm.BASE_URL == "https://openrouter.ai/api/v1", llm.BASE_URL
    assert all(m.endswith(":free") or m == "openrouter/free" for m in llm.FAST_CHAIN + llm.SMART_CHAIN), (llm.FAST_CHAIN, llm.SMART_CHAIN)
    llm._client = AsyncOpenAI(api_key=llm.API_KEY, base_url=f"http://127.0.0.1:{PORT}/api/v1", max_retries=0)

    with TestClient(app) as c:      # one event loop for the whole run, like the real server
        run(c)
    print(f"OpenRouter chains: fast={llm.FAST_CHAIN} smart={llm.SMART_CHAIN}")
    print("AI WITH AN OPENROUTER KEY: OK")


def run(c):
    ok(c.post("/api/auth/signup", json={"email": "hr@or.test", "password": "password-123", "name": "HR", "company": "OR Co"}))
    ok(c.post("/api/demo/seed"))
    ok(c.patch("/api/org", json={"settings": {"ai_reports_per_run": 3}}))
    job = next(j for j in ok(c.get("/api/jobs")) if j["title"] == "Senior Backend Engineer")
    assert ok(c.get(f"/api/jobs/{job['id']}/matches"))["ai_pending"] == 5

    # AI match reports: the OpenRouter request shape, the budget, the cache
    CALLS.clear()
    r = ok(c.post("/api/match/ai-reports", json={"job_ids": [job["id"]], "max": 10}))
    assert r["generated"] == 3 and r["skipped_over_budget"] == 2, r
    first = CALLS[0]
    assert first["model"] == llm.FAST_MODEL and first["models"][:1] == [llm.FAST_MODEL] and len(first["models"]) >= 2, first.get("models")
    assert first["reasoning"] == {"effort": "low", "exclude": True}
    assert "Senior Backend Engineer" in first["messages"][1]["content"] and "CANDIDATE" in first["messages"][1]["content"]
    rows = ok(c.get(f"/api/jobs/{job['id']}/matches"))["items"]
    assert rows[0]["ai_report"]["verdict"] == "strong" and rows[0]["ai_score"] == 81
    r = ok(c.post("/api/match/ai-reports", json={"job_ids": [job["id"]]}))
    assert r["generated"] == 2 and r["pending_before"] == 2, r
    n = len(CALLS)
    r = ok(c.post("/api/match/ai-reports", json={"job_ids": [job["id"]]}))
    assert r["generated"] == 0 and len(CALLS) == n, "cached reports must not call the AI again"

    # "Write with AI": smart model chain; a model that rejects JSON mode is retried without it
    CALLS.clear()
    out = ok(c.post(f"/api/jobs/{job['id']}/ai-write"))
    assert out["responsibilities"] == ["Design APIs", "Own services"], out
    assert CALLS[0]["model"] == llm.SMART_MODEL and "response_format" in CALLS[0], CALLS[0]["model"]
    if llm.SMART_MODEL.startswith("nvidia/"):
        assert len(CALLS) == 2 and "response_format" not in CALLS[1], "JSON-mode fallback did not happen"

    # Provider down or daily free limit hit: reports fail cleanly, nothing crashes, nothing is stored
    other = next(j for j in ok(c.get("/api/jobs")) if j["title"] == "Data Analyst")
    MODE["fail"] = True
    r = ok(c.post("/api/match/ai-reports", json={"job_ids": [other["id"]]}))
    assert r["generated"] == 0 and r["failed"] == 3 and "rate-limiting" in r["error"], r
    w = c.post(f"/api/jobs/{other['id']}/ai-write")
    assert w.status_code == 503 and "rate-limiting" in w.json()["detail"], w.text
    assert ok(c.get(f"/api/jobs/{other['id']}/matches"))["ai_pending"] == 5, "a failed report must stay pending"
    MODE["fail"] = False
    usage = ok(c.get("/api/dashboard"))["ai_reports"]
    assert usage == 5, usage


if __name__ == "__main__":
    main()
