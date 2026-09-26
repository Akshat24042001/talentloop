"""End-to-end flow test with a fake LLM (no keys needed): python -m tests.test_flow"""
import json
import os
import tempfile

os.environ.update({"LLM_MOCK": "1", "PUBLIC_URL": "https://example.trycloudflare.com",
                   "VAPI_PUBLIC_KEY": "pk_test", "ADMIN_KEY": "", "DATA_DIR": tempfile.mkdtemp()})

from pathlib import Path  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402

S = Path(__file__).resolve().parent.parent / "web" / "samples"
c = TestClient(app)


def sse(r):
    return "".join(json.loads(l[6:])["choices"][0]["delta"].get("content", "")
                   for l in r.text.splitlines() if l.startswith("data: ") and "[DONE]" not in l)


def turn(iid, messages):
    r = c.post(f"/llm/{iid}/chat/completions", json={"messages": messages, "stream": True})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    return sse(r)


def main():
    inp = {"company": "Demo", "role": "Java Backend Developer", "candidate_name": "Rohan Mehta", "duration_min": 15,
           "jd": (S / "sample_jd.txt").read_text(), "resume": (S / "sample_resume.txt").read_text(),
           "questions": [q for q in (S / "sample_questions.txt").read_text().splitlines() if q.strip()]}
    plan = c.post("/api/plan", json=inp).json()["plan"]
    iid = c.post("/api/interviews", json={"plan": plan, "inputs": inp}).json()["id"]
    a = c.post(f"/api/interviews/{iid}/assistant").json()["assistant"]
    assert a["model"]["url"].endswith(f"/llm/{iid}") and a["endCallPhrases"] == ["this concludes our interview"]
    assert a["transcriber"]["language"] == "en-IN"
    print("FIRST:", a["firstMessage"][:90], "...")

    msgs = [{"role": "system", "content": "x"}, {"role": "assistant", "content": a["firstMessage"]}]

    # 1) cut-off answer -> invite_continue
    msgs.append({"role": "user", "content": "I am a backend developer and"})
    say = turn(iid, msgs); print("T1:", say); assert "go on" in say.lower()
    msgs.append({"role": "assistant", "content": say})

    # 2) idempotency: Vapi re-requests same turn with a longer transcript -> recomputed from same base
    msgs.append({"role": "user", "content": "I work at ShipKart building Spring Boot APIs for three years now"})
    say_a = turn(iid, msgs)
    msgs[-1]["content"] += " and I lead a small team of three developers on the rate card module."
    say_b = turn(iid, msgs)
    print("T2 (re-request):", say_b)
    rec = c.get(f"/api/interviews/{iid}").json()
    cands = [e for e in rec["state"]["log"] if e["role"] == "candidate"]
    assert len(cands) == 2, f"re-request duplicated log entries: {len(cands)}"
    msgs.append({"role": "assistant", "content": say_b})

    # 3) repeat request
    msgs.append({"role": "user", "content": "sorry can you repeat the question"})
    say = turn(iid, msgs); print("T3:", say)
    msgs.append({"role": "assistant", "content": say})

    # 4) answer until the end
    for i in range(30):
        msgs.append({"role": "user", "content": "Sure. In my current role I built the tracking API, added composite "
                     "indexes and Redis caching which cut p95 latency from 1.8 seconds to 350 ms, and we moved "
                     "notifications to Kafka consumers. My notice period is 60 days and I can travel to the office."})
        say = turn(iid, msgs); msgs.append({"role": "assistant", "content": say})
        if "concludes our interview" in say.lower():
            break
    print("LAST:", say)
    assert "concludes our interview" in say.lower()

    # after end, further turns must not restart anything
    msgs.append({"role": "user", "content": "hello?"})
    assert "concludes" in turn(iid, msgs).lower()

    # webhook, events, complete, score
    c.post(f"/api/interviews/{iid}/events", json=[{"type": "tab_hidden", "ts": 1000}, {"type": "tab_visible", "ts": 41000}])
    c.post(f"/webhook/vapi/{iid}", json={"message": {"type": "end-of-call-report", "endedReason": "assistant-said-end-call-phrase"}})
    assert c.post(f"/api/interviews/{iid}/complete").json()["status"] == "completed"
    rep = c.post(f"/api/interviews/{iid}/score").json()
    print("REPORT computed:", rep["computed"])
    print("REVIEW:", rep["human_review_reasons"])
    assert rep["computed"]["questions_asked"] == rep["computed"]["questions_planned"]
    assert any("Left the interview tab" in r for r in rep["human_review_reasons"])

    # link can't be reused
    assert c.post(f"/api/interviews/{iid}/assistant").status_code == 409

    # HR calibration
    qid = [q for q in plan["questions"] if q["scored"]][0]["id"]
    c.post(f"/api/interviews/{iid}/hr", json={"scores": {qid: 4}, "decision": "next_round"})
    print("CALIBRATION:", c.get("/api/calibration").json())

    # dropped call + reconnect resumes the same question
    iid2 = c.post("/api/interviews", json={"plan": plan, "inputs": inp}).json()["id"]
    a2 = c.post(f"/api/interviews/{iid2}/assistant").json()["assistant"]
    m2 = [{"role": "assistant", "content": a2["firstMessage"]}, {"role": "user", "content": "Hi I'm Rohan, three years in backend dev with Spring Boot, currently at ShipKart."}]
    s1 = turn(iid2, m2)
    assert c.post(f"/api/interviews/{iid2}/complete").json()["status"] == "in_progress"
    a3 = c.post(f"/api/interviews/{iid2}/assistant").json()["assistant"]
    print("RESUME:", a3["firstMessage"][:120])
    assert a3["firstMessage"].startswith("Welcome back")
    s2 = turn(iid2, [{"role": "assistant", "content": a3["firstMessage"]}, {"role": "user", "content": "Can you repeat?"}])
    print("AFTER RESUME:", s2[:100])

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
