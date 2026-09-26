"""End-to-end flow test with a fake LLM (no keys needed): python -m tests.test_flow

Covers the happy path plus the failure modes that break real voice calls: Vapi re-requesting a
turn, Vapi discarding an unspoken reply, idle prompts in the history, stale calls after a
reconnect, failed call starts, running out of time, forged webhooks and chunked video upload."""
import json
import os
import tempfile

os.environ.update({"LLM_MOCK": "1", "PUBLIC_URL": "https://example.trycloudflare.com",
                   "VAPI_PUBLIC_KEY": "pk_test", "ADMIN_KEY": "", "DATA_DIR": tempfile.mkdtemp()})

from pathlib import Path  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from backend import brain, store  # noqa: E402
from backend.main import _recording_url_ok, app  # noqa: E402

S = Path(__file__).resolve().parent.parent / "web" / "samples"
c = TestClient(app)
ANSWER = ("Sure. In my current role I built the tracking API, added composite indexes and Redis caching which "
          "cut p95 latency from 1.8 seconds to 350 ms, and we moved notifications to Kafka consumers.")


def sse(r):
    return "".join(json.loads(l[6:])["choices"][0]["delta"].get("content", "")
                   for l in r.text.splitlines() if l.startswith("data: ") and "[DONE]" not in l)


def llm_path(assistant):
    return "/llm/" + assistant["model"]["url"].split("/llm/", 1)[1] + "/chat/completions"


def turn(path, messages, status=200):
    r = c.post(path, json={"messages": messages, "stream": True})
    assert r.status_code == status, r.text
    if status != 200:
        return None
    assert r.headers["content-type"].startswith("text/event-stream")
    return sse(r)


def state(iid):
    return c.get(f"/api/interviews/{iid}").json()["state"]


def new_interview(inp, plan):
    iid = c.post("/api/interviews", json={"plan": plan, "inputs": inp}).json()["id"]
    a = c.post(f"/api/interviews/{iid}/assistant").json()["assistant"]
    return iid, a, llm_path(a)


def main():
    inp = {"company": "Demo", "role": "Java Backend Developer", "candidate_name": "Rohan Mehta", "duration_min": 15,
           "jd": (S / "sample_jd.txt").read_text(), "resume": (S / "sample_resume.txt").read_text(),
           "questions": [q for q in (S / "sample_questions.txt").read_text().splitlines() if q.strip()]}
    r = c.post("/api/plan", json=inp).json()
    plan = r["plan"]
    assert isinstance(r["warnings"], list)
    iid, a, path = new_interview(inp, plan)
    assert a["model"]["url"].startswith(f"https://example.trycloudflare.com/llm/{iid}/")
    assert a["endCallPhrases"] == ["this concludes our interview"]
    assert a["transcriber"]["language"] == "en-IN"
    assert a["silenceTimeoutSeconds"] >= 60, "Vapi's 30 s default would hang up on a thinking candidate"
    assert a["server"]["url"].endswith(path.split("/")[3])
    print("FIRST:", a["firstMessage"][:90], "...")

    msgs = [{"role": "system", "content": "x"}, {"role": "assistant", "content": a["firstMessage"]}]

    # 1) cut-off answer -> invite_continue
    msgs.append({"role": "user", "content": "I am a backend developer and"})
    say = turn(path, msgs); print("T1:", say); assert "go on" in say.lower()
    msgs.append({"role": "assistant", "content": say})

    # 2) re-request of the same turn with a longer transcript -> recomputed from the same base
    msgs.append({"role": "user", "content": "I work at ShipKart building Spring Boot APIs for three years now"})
    turn(path, msgs)
    msgs[-1]["content"] += " and I lead a small team of three developers on the rate card module."
    say_b = turn(path, msgs)
    print("T2 (re-request):", say_b)
    cands = [e for e in state(iid)["log"] if e["role"] == "candidate"]
    assert len(cands) == 2, f"re-request duplicated log entries: {len(cands)}"
    msgs.append({"role": "assistant", "content": say_b})
    q_before = state(iid)["q_idx"]

    # 3) Vapi DISCARDS our reply (candidate kept talking) and appends a NEW user message.
    #    Old code built on the unspoken reply and silently skipped a question.
    msgs.append({"role": "user", "content": ANSWER})
    unspoken = turn(path, msgs)
    msgs.append({"role": "user", "content": "Also I mentored two juniors on that project."})
    say = turn(path, msgs)
    st = state(iid)
    print("T3 (unspoken reply discarded):", say)
    assert st["q_idx"] == q_before + 1, f"question skipped: q_idx {st['q_idx']} vs expected {q_before + 1}"
    assert any("mentored two juniors" in e["text"] and "tracking API" in e["text"]
               for e in st["log"] if e["role"] == "candidate"), "merged answer not recorded"
    assert not any(e["text"] == unspoken and e["role"] == "ai" for e in st["log"][:-1]) or unspoken == say
    msgs.append({"role": "assistant", "content": say})

    # 4) Vapi idle prompt appears in history (we never produced it) -> still matched correctly
    msgs.append({"role": "assistant", "content": "Take your time. Let me know when you're ready to answer."})
    msgs.append({"role": "user", "content": "sorry can you repeat the question"})
    say = turn(path, msgs); print("T4 (after idle prompt):", say)
    assert say.lower().startswith("sure"), say
    msgs.append({"role": "assistant", "content": say})

    # 5) answer until the end
    for _ in range(30):
        msgs.append({"role": "user", "content": ANSWER + " My notice period is 60 days."})
        say = turn(path, msgs); msgs.append({"role": "assistant", "content": say})
        if "concludes our interview" in say.lower():
            break
    print("LAST:", say)
    assert "concludes our interview" in say.lower()
    assert say.lower().count("concludes our interview") == 1

    # after end, further turns must not restart anything
    msgs.append({"role": "user", "content": "hello?"})
    assert "concludes" in turn(path, msgs).lower()

    # forged webhook: wrong token rejected; SSRF host rejected
    assert c.post(f"/webhook/vapi/{iid}/wrongtoken", json={"message": {}}).status_code == 403
    assert not _recording_url_ok("http://169.254.169.254/latest/meta-data")
    assert not _recording_url_ok("https://evil.example.com/x.wav")
    assert not _recording_url_ok("https://vapi.ai.evil.com/x.wav")
    assert _recording_url_ok("https://storage.vapi.ai/abc-mono.wav")

    # events, webhook (real token) -> scoring kicks off even if the browser never calls /complete
    c.post(f"/api/interviews/{iid}/events", json=[{"type": "tab_hidden", "ts": 1000}, {"type": "tab_visible", "ts": 41000}])
    token = a["server"]["url"].rsplit("/", 1)[1]
    c.post(f"/webhook/vapi/{iid}/{token}", json={"message": {"type": "end-of-call-report",
                                                             "endedReason": "assistant-said-end-call-phrase"}})
    rec = c.get(f"/api/interviews/{iid}").json()
    assert rec["status"] == "scored" and rec["report"], "webhook did not trigger scoring"
    assert "token" not in rec["state"] and "tokens" not in rec["state"], "session token leaked to HR API"
    assert c.post(f"/api/interviews/{iid}/complete").json()["status"] == "scored"
    rep = rec["report"]
    print("REPORT computed:", rep["computed"])
    print("REVIEW:", rep["human_review_reasons"])
    assert rep["computed"]["questions_asked"] == rep["computed"]["questions_planned"]
    assert rep["computed"]["avg_turn_latency_ms"] is not None
    assert any("Left the interview tab" in r for r in rep["human_review_reasons"])
    assert [q["q_id"] for q in rep["questions"]] == [q["id"] for q in plan["questions"]]

    # HR re-score runs in the background and does not break the report
    assert c.post(f"/api/interviews/{iid}/score").json()["status"] == "scoring"
    assert c.get(f"/api/interviews/{iid}").json()["report"]

    # link can't be reused
    assert c.post(f"/api/interviews/{iid}/assistant").status_code == 409

    # HR calibration
    qid = [q for q in plan["questions"] if q["scored"]][0]["id"]
    c.post(f"/api/interviews/{iid}/hr", json={"scores": {qid: 4}, "decision": "next_round"})
    print("CALIBRATION:", c.get("/api/calibration").json())

    # --- failed start (mic/Vapi error before the candidate spoke) must not count as a reconnect
    iid2, a2, p2 = new_interview(inp, plan)
    a2b = c.post(f"/api/interviews/{iid2}/assistant").json()["assistant"]
    assert a2b["firstMessage"].startswith("Hi "), "a failed start was treated as a reconnect"
    assert state(iid2)["reconnects"] == 0
    # ...and the dead first call's token no longer works
    turn(p2, [{"role": "assistant", "content": a2["firstMessage"]}, {"role": "user", "content": "hi"}], status=403)
    p2 = llm_path(a2b)

    # --- dropped call + reconnect resumes the same question; old call is locked out
    turn(p2, [{"role": "assistant", "content": a2b["firstMessage"]},
              {"role": "user", "content": "Hi I'm Rohan, three years in backend dev with Spring Boot, currently at ShipKart."}])
    assert c.post(f"/api/interviews/{iid2}/complete").json()["status"] == "in_progress"
    assert c.get(f"/api/interviews/{iid2}/public").json()["resuming"] is True
    a3 = c.post(f"/api/interviews/{iid2}/assistant").json()["assistant"]
    print("RESUME:", a3["firstMessage"][:120])
    assert a3["firstMessage"].startswith("Welcome back")
    turn(p2, [{"role": "assistant", "content": a2b["firstMessage"]}, {"role": "user", "content": "late packet"}], status=403)
    s2 = turn(llm_path(a3), [{"role": "assistant", "content": a3["firstMessage"]}, {"role": "user", "content": "Can you repeat?"}])
    print("AFTER RESUME:", s2[:100])
    assert s2.lower().startswith("sure")

    # --- chunked recording upload: in order, idempotent, out-of-order rejected
    u = f"/api/interviews/{iid2}/media/chunk?rid=abc123&ext=webm"
    assert c.post(u + "&seq=0", content=b"AAAA").status_code == 200
    assert c.post(u + "&seq=0", content=b"AAAA").json().get("duplicate")
    assert c.post(u + "&seq=2", content=b"CCCC").status_code == 409
    assert c.post(u + "&seq=1", content=b"BBBB").status_code == 200
    assert (store.MEDIA_DIR / iid2 / "candidate_abc123.webm").read_bytes() == b"AAAABBBB"

    # --- delete removes interview and media
    assert c.delete(f"/api/interviews/{iid2}").status_code == 200
    assert c.get(f"/api/interviews/{iid2}").status_code == 404
    assert not (store.MEDIA_DIR / iid2).exists()

    # --- running out of time: optional questions are skipped, HR-mandatory ones are still asked
    tight = brain.normalize_plan({"duration_min": 5, "questions": [
        {"id": "w", "type": "warmup", "ask": "Introduce yourself.", "time_budget_sec": 60},
        {"id": "r1", "type": "resume_probe", "ask": "Tell me about project A.", "time_budget_sec": 200},
        {"id": "r2", "type": "jd_skill", "ask": "Explain indexing.", "time_budget_sec": 200},
        {"id": "h1", "type": "hr_mandatory", "ask": "What is your notice period?", "time_budget_sec": 60},
        {"id": "h2", "type": "hr_mandatory", "ask": "Can you work from our office?", "time_budget_sec": 60}]})
    rec = {"id": "tight", "plan": tight, "state": None}
    brain.start_session(rec)
    rec["state"]["session_started"] -= 150  # 2.5 minutes already used on the warm-up
    rec["snapshots"][0]["state"]["session_started"] -= 150
    import asyncio
    say = asyncio.run(brain.handle_turn(rec, [{"role": "assistant", "content": rec["state"]["last_say"]},
                                              {"role": "user", "content": ANSWER}]))
    print("TIGHT:", say, "| skipped:", rec["state"]["skipped"])
    assert rec["plan"]["questions"][rec["state"]["q_idx"]]["id"] == "h1", "mandatory question not prioritised"
    assert rec["state"]["skipped"] == ["r1", "r2"]

    # --- plan normalisation survives junk from the LLM or HR edits
    junk = brain.normalize_plan({"duration_min": "abc", "competencies": [{"id": "c1", "weight": 0}],
                                 "questions": [{"ask": "Q?", "competency_id": "nope", "time_budget_sec": "x",
                                                "type": "weird"}]})
    assert junk["questions"][0]["competency_id"] == "c1" and junk["questions"][0]["type"] == "jd_skill"
    assert junk["competencies"][0]["weight"] == 1.0 and junk["duration_min"] == 20

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
