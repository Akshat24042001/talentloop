"""The hiring features' real AI path with an OpenRouter key (no network):  python -m tests.test_ai_openrouter

A fake OpenRouter (OpenAI-compatible) server records every request. Checks that AI match reports and
"Write with AI" use the OpenRouter free-model chain with fallbacks, survive a model that rejects JSON mode,
cache reports, respect the per-run budget, and degrade cleanly when the AI provider fails."""
import json
import os
import tempfile
import threading
import time

os.environ.update({"ALLOW_SAMPLE_DATA": "1", "LLM_MOCK": "0", "LLM_API_KEY": "sk-or-test-key", "LLM_BASE_URL": "", "FAST_MODEL": "", "SMART_MODEL": "",
                   "DATA_DIR": tempfile.mkdtemp(), "DATABASE_URL": os.getenv("TEST_DATABASE_URL", ""), "ADMIN_KEY": "",
                   "PUBLIC_URL": "https://example.com", "VAPI_PUBLIC_KEY": "pk",
                   "PLAN_DEADLINE_SEC": "6", "PLAN_HEDGE_SEC": "2"})

import asyncio  # noqa: E402

import uvicorn  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402

from backend import llm  # noqa: E402
from backend.main import app  # noqa: E402

PORT = 8797
CALLS: list[dict] = []
MODE = {"fail": False, "delays": {}, "fail_models": set()}
PLAN = {"company": "Acme", "role": "Backend", "candidate_name": "Asha", "duration_min": 15,
        "competencies": [{"id": "c1", "name": "Java depth", "weight": 0.7, "anchors": {"1": "vague", "3": "ok", "5": "deep"}},
                         {"id": "c2", "name": "Communication", "weight": 0.3, "anchors": {}}],
        "questions": [{"id": "q1", "type": "warmup", "ask": "Introduce yourself briefly.", "scored": False, "max_followups": 0, "time_budget_sec": 60, "competency_id": "c2"},
                      {"id": "q2", "type": "resume_probe", "ask": "How did you cut payment latency by 40%?", "scored": True, "max_followups": 2,
                       "time_budget_sec": 180, "competency_id": "c1", "good_answer_covers": ["profiling", "the fix", "the number"]}],
        "keyterms": ["Spring Boot"], "company_facts": [], "resume_claims_to_verify": [], "do_not_ask": []}
fake = FastAPI()


@fake.post("/api/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    CALLS.append(body)
    await asyncio.sleep(MODE["delays"].get(body["model"], 0))
    if body["model"] in MODE["fail_models"]:
        return JSONResponse({"error": {"message": "Provider returned error", "code": 502}}, status_code=502)
    if MODE["fail"]:
        return JSONResponse({"error": {"message": "Rate limit exceeded: free-models-per-day", "code": 429}}, status_code=429)
    if "response_format" in body and body["model"].startswith("nvidia/"):
        return JSONResponse({"error": {"message": "response_format is not supported by this model", "code": 400}}, status_code=400)
    sys_prompt = body["messages"][0]["content"]
    if "design structured first-round job interviews" in sys_prompt:
        out = PLAN
    elif "assess how well a candidate fits" in sys_prompt:
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
    llm._clients["openrouter"] = AsyncOpenAI(api_key=llm.API_KEY, base_url=f"http://127.0.0.1:{PORT}/api/v1", max_retries=0)

    with TestClient(app) as c:      # one event loop for the whole run, like the real server
        run(c)
    print(f"OpenRouter chains: fast={llm.FAST_CHAIN} smart={llm.SMART_CHAIN}")
    print("AI WITH AN OPENROUTER KEY: OK")


def plan_timing(c):
    """Plans arrive within the deadline whatever the models do (deadline 6 s and hedge 2 s in this test)."""
    inp = {"company": "Acme", "role": "Backend Engineer", "candidate_name": "Asha", "duration_min": 15, "questions": ["Notice period?"],
           "jd": "We need Java, Spring Boot, PostgreSQL and Kafka experience. " * 20,
           "resume": "Asha Rao\nBuilt payment APIs in Java and Spring Boot.\nReduced p95 latency by 40% with caching.\n" * 5}
    m = llm.plan_models()

    def run_case(name, delays, fail=()):
        MODE["delays"], MODE["fail_models"] = delays, set(fail)
        CALLS.clear()
        t0 = time.time()
        r = ok(c.post("/api/plan", json=inp))
        dt = time.time() - t0
        print(f"  {name:38s} {dt:4.1f}s  source={r['plan'].get('source')} model={r['plan'].get('model', '-')}")
        return r["plan"], dt

    plan, dt = run_case("first model fast", {m[0]: 0.3})
    assert plan["source"] == "ai" and plan["model"] == m[0] and dt < 2, (plan.get("source"), dt)
    first = CALLS[0]
    assert first["reasoning"] == {"effort": "low", "exclude": True} and first["provider"] == {"sort": "throughput"}, first
    assert "models" not in first and first["max_tokens"] <= 2600, "each attempt is one model; the hedge picks the next"
    plan, dt = run_case("first slow, backup wins after hedge", {m[0]: 30, m[1]: 0.5})
    assert plan["model"] == m[1] and 2 <= dt < 4, (plan.get("model"), dt)
    plan, dt = run_case("first fails, next starts at once", {m[1]: 0.3}, fail=[m[0]])
    assert plan["model"] == m[1] and dt < 2, (plan.get("model"), dt)
    plan, dt = run_case("all slow: template by the deadline", {x: 30 for x in m})
    assert plan["source"] == "template" and dt < 7.5, (plan.get("source"), dt)
    asks = [q["ask"] for q in plan["questions"]]
    assert plan["questions"][0]["type"] == "warmup" and "Notice period?" in asks, asks
    assert any("40%" in a for a in asks) and any("Spring Boot" in a or "Java" in a for a in asks), asks
    MODE["delays"], MODE["fail_models"] = {}, set()
    print("PLAN SPEED: OK")


def run(c):
    ok(c.post("/api/auth/signup", json={"email": "hr@or.test", "password": "password-123", "name": "HR", "company": "OR Co"}))
    plan_timing(c)
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
