"""End-to-end flow test with a fake LLM (no keys needed): python -m tests.test_flow

Covers the happy path plus the failure modes that break real voice calls: Vapi re-requesting a
turn, Vapi discarding an unspoken reply, idle prompts in the history, stale calls after a
reconnect, failed call starts, running out of time, forged webhooks and chunked video upload."""
import json
import os
import tempfile

os.environ.update({"ALLOW_SAMPLE_DATA": "1", "LLM_MOCK": "1", "PUBLIC_URL": "https://example.trycloudflare.com",
                   "VAPI_PUBLIC_KEY": "pk_test", "ADMIN_KEY": "test-admin-key-123456", "FINISH_DELAY_SEC": "0", "DATA_DIR": tempfile.mkdtemp()})

from pathlib import Path  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from backend import brain, store  # noqa: E402
from backend.main import app  # noqa: E402
from backend.media import public_https_url  # noqa: E402

S = Path(__file__).resolve().parent.parent / "frontend" / "public" / "samples"
c = TestClient(app, headers={"X-Admin-Key": "test-admin-key-123456"})
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


NOP = {"practice_question": False}   # these checks index the plan's questions; the practice question has its own test


def new_interview(inp, plan):
    iid = c.post("/api/interviews", json={"plan": plan, "inputs": inp, "settings": NOP}).json()["id"]
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
    ends = [h for h in a["hooks"] if any(x.get("type") == "tool" for x in h["do"])]
    assert ends and ends[0]["options"]["timeoutSeconds"] >= 60, "a thinking candidate must not be hung up on"
    assert "silenceTimeoutSeconds" not in a and "messagePlan" not in a, "fields removed from Vapi's API"
    assert a["voice"] == {"provider": "vapi", "voiceId": "Naina", "version": "2", "language": "en"}
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
    assert not public_https_url("http://169.254.169.254/latest/meta-data")   # not https
    assert not public_https_url("https://169.254.169.254/latest/meta-data")  # cloud metadata
    assert not public_https_url("https://127.0.0.1/x") and not public_https_url("https://10.1.2.3/x")
    assert not public_https_url("https://[::1]/x") and not public_https_url("https://192.168.1.5/x")
    assert public_https_url("https://8.8.8.8/recording.wav")

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
    assert any("Left the interview tab" in r for r in rep["human_review_reasons"]), rep["human_review_reasons"]
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
    assert (store.MEDIA_DIR / iid2 / "camera_abc123.webm").read_bytes() == b"AAAABBBB"

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

    # --- HR features: settings, schedule, snapshots, consent, feedback, progress, exports, close, sweeper
    import asyncio
    import io
    import time as _t
    from backend import main as M
    future = _t.time() + 3600
    iid5 = c.post("/api/interviews", json={"plan": plan, "inputs": inp, "expires_hours": 2, "settings": {**NOP, 
        "available_from": future, "require_screen_share": True, "reconnect_window_sec": 5, "candidate_email": "a@b.c"}}).json()["id"]
    pub = c.get(f"/api/interviews/{iid5}/public").json()
    assert pub["not_open_yet"] and pub["require_screen_share"] and pub["reconnect_window_sec"] == 10  # clamped to >= 10
    assert c.post(f"/api/interviews/{iid5}/assistant").status_code == 425, "scheduled link opened early"

    iid6 = c.post("/api/interviews", json={"plan": plan, "inputs": inp, "settings": {**NOP, "reconnect_window_sec": 10}}).json()["id"]
    assert c.post(f"/api/interviews/{iid6}/consent", json={"version": "t"}).status_code == 200
    a6 = c.post(f"/api/interviews/{iid6}/assistant").json()["assistant"]
    p6 = llm_path(a6)
    turn(p6, [{"role": "assistant", "content": a6["firstMessage"]}, {"role": "user", "content": ANSWER}])
    now_ms = _t.time() * 1000
    c.post(f"/api/interviews/{iid6}/events", json={"sent_at": now_ms, "events": [
        {"type": "tab_hidden", "ts": now_ms - 40000}, {"type": "tab_visible", "ts": now_ms - 1000},
        {"type": "paste", "ts": now_ms - 500, "detail": "120 chars"}]})
    assert c.post(f"/api/interviews/{iid6}/snapshot", content=b"not a jpeg").status_code == 400
    from PIL import Image
    buf = io.BytesIO(); Image.new("RGB", (64, 36)).save(buf, "JPEG")
    assert c.post(f"/api/interviews/{iid6}/snapshot?reason=reference", content=buf.getvalue()).json()["ok"]
    prog = c.get(f"/api/interviews/{iid6}/progress").json()
    assert prog["question"]["text"] == plan["questions"][1]["ask"] and prog["question"]["kind"] == "question", prog
    assert "q_total" not in prog and "remaining_sec" not in prog, "the candidate must not see counts or a timer"
    pub6 = c.get(f"/api/interviews/{iid6}/public").json()
    assert "questions" not in pub6 and "duration_min" not in pub6, pub6
    pr = c.get(f"/api/interviews/{iid6}/proctoring").json()["proctoring"]
    assert pr["durations"]["tab_hidden"] >= 38 and pr["counts"]["paste"] == 1 and pr["risk"] in ("medium", "high"), pr
    assert c.get(f"/media/{iid6}/snap_001_reference.jpg").status_code == 200
    assert c.get(f"/media/{iid6}/..%2Fsecret.json").status_code in (400, 404)
    assert c.get(f"/media/{iid6}/not_listed.webm").status_code == 404
    for path, ctype in (("report.pdf", "application/pdf"), ("transcript.txt", "text/plain"), ("export.json", "application/json")):
        r = c.get(f"/api/interviews/{iid6}/{path}")
        assert r.status_code == 200 and r.headers["content-type"].startswith(ctype) and "attachment" in r.headers["content-disposition"], path
    exp = c.get(f"/api/interviews/{iid6}/export.json").json()
    assert "token" not in exp["state"] and exp["proctoring"]["counts"]["paste"] == 1
    csv_txt = c.get("/api/interviews.csv").text
    assert csv_txt.startswith("interview_id,") and iid6 in csv_txt
    # candidate drops and never returns: the sweeper closes and scores it after the window
    M._presence.pop(iid6, None)
    import json as _json
    rec6 = _json.loads((store.INT_DIR / f"{iid6}.json").read_text())
    rec6["last_seen"] = _t.time() - 500
    for e in rec6["state"]["log"]:
        e["ts"] = _t.time() - 500
    for sn in rec6["snapshots"]:
        for e in sn["state"]["log"]:
            e["ts"] = _t.time() - 500
    (store.INT_DIR / f"{iid6}.json").write_text(_json.dumps(rec6))
    asyncio.run(M.sweep_once())
    r6 = c.get(f"/api/interviews/{iid6}").json()
    assert r6["status"] == "scored" and r6["ended_early"] and r6["report"], r6["status"]
    assert c.post(f"/api/interviews/{iid6}/assistant").status_code == 409, "abandoned interview reopened"
    assert c.post(f"/api/interviews/{iid6}/feedback", json={"rating": 9}).json()["ok"]
    assert c.get(f"/api/interviews/{iid6}").json()["feedback"]["rating"] == 5
    # HR can close a link that was never used
    iid7 = c.post("/api/interviews", json={"plan": plan, "inputs": inp, "settings": NOP}).json()["id"]
    assert c.post(f"/api/interviews/{iid7}/close").json()["status"] == "cancelled"
    assert c.post(f"/api/interviews/{iid7}/assistant").status_code == 409
    # after a deploy, a browser must never pair a new page with an old cached script
    import re as _re
    for pg in ("/", "/app", "/app/jobs/abc", "/careers/acme/jobs/x", "/login", "/interview.html"):
        r = c.get(pg)
        assert r.status_code == 200 and '<div id="root">' in r.text, pg
        assert r.headers.get("cache-control") == "no-cache", (pg, r.headers.get("cache-control"))
        assert not _re.search(r'(src|href)="/(common|charts)\.js"|href="/style\.css"', r.text), f"{pg} loads an unversioned asset"
    assert c.get("/common.js").headers.get("cache-control") == "no-cache"
    # links from the earlier version redirect into the app
    assert c.get("/report.html?id=abc", follow_redirects=False).headers["location"] == "/app/interviews/abc"
    assert c.get("/dashboard.html", follow_redirects=False).headers["location"] == "/app/interviews"
    idx = c.get("/samples/index.json").json()
    assert len(idx) >= 7 and all(c.get("/samples/" + s[k]).status_code == 200 for s in idx for k in ("jd", "resume", "questions"))
    print("HR FEATURES: OK")
    integrity_checks(inp, plan)
    opening_checks(inp, plan)
    warning_at_start_does_not_stall(inp, plan)
    no_question_loop()
    no_question_loop(split=True)

    print("\nALL CHECKS PASSED")


NUM_WORDS = {"1.8": "one point eight", "350": "three hundred and fifty", "5": "five", "3": "three", "40": "forty", "60": "sixty"}


def vapi_formatted(text: str) -> str:
    """What Vapi may keep in its history for a line we produced: the TTS-formatted text (numbers spelled
    out, punctuation changed, sentences split). Our server must still recognise it as its own line."""
    import re
    for k in sorted(NUM_WORDS, key=len, reverse=True):
        text = re.sub(rf"(?<![\d.]){re.escape(k)}(?![\d.])", NUM_WORDS[k], text)
    return text.replace("ms", " milliseconds").replace("?", " ?").replace(",", "")


def no_question_loop(split: bool = False):
    """Regression: the interviewer got stuck re-asking one question, acknowledging the previous answer each
    time. Cause: Vapi's copy of our line differed slightly (numbers spelled out), the exact-text match failed,
    and the turn was silently rebuilt from an OLDER question. It must move forward, one question at a time."""
    plan = brain.normalize_plan({"duration_min": 20, "company": "Demo", "role": "Backend Developer",
                                 "candidate_name": "Akshat Shah", "questions": [
        {"id": "w", "type": "warmup", "ask": "Please introduce yourself.", "time_budget_sec": 60, "max_followups": 0},
        {"id": "c", "type": "hr_mandatory", "ask": "Can you commute to our office 5 days a week?", "max_followups": 0},
        {"id": "r", "type": "resume_probe", "ask": "You cut API latency from 1.8s to 350ms. What exactly did you change?", "max_followups": 0},
        {"id": "t", "type": "resume_probe", "ask": "You led a team of 3. How did you split the work, given 40 tickets a sprint?", "max_followups": 0},
        {"id": "n", "type": "hr_mandatory", "ask": "What is your notice period?", "max_followups": 0}]})
    iid = c.post("/api/interviews", json={"plan": plan, "inputs": {}, "settings": NOP}).json()["id"]
    a = c.post(f"/api/interviews/{iid}/assistant").json()["assistant"]
    p = llm_path(a)
    msgs = [{"role": "system", "content": "x"}, {"role": "assistant", "content": vapi_formatted(a["firstMessage"])}]
    long_answer = " Honestly I have thought about this a lot and I can explain it properly with the details of what I did and why it mattered for the team."
    asked = []
    for ans in ["I'm Akshat, a backend developer.", "Yes, I stay nearby and I can commute easily.",
                "I added indexes and Redis caching.", "I split the work by module and paired juniors with seniors.",
                "My notice period is 60 days."]:
        msgs.append({"role": "user", "content": ans + long_answer})
        say = turn(p, msgs)
        asked.append(state(iid)["q_idx"])
        # Vapi keeps the reply as it was formatted for speech (numbers spelled out, punctuation changed),
        # sometimes split into one message per sentence.
        parts = [x for x in vapi_formatted(say).split(". ") if x] if split else [vapi_formatted(say)]
        msgs.extend({"role": "assistant", "content": x} for x in parts)
        if "concludes our interview" in say.lower():
            break
    print("LOOP CHECK q_idx after each answer:", asked)
    assert asked == [1, 2, 3, 4, 4], f"interview did not move forward one question per answer: {asked}"
    assert state(iid)["ended"], "interview should have reached its end"
    cands = [e["q_id"] for e in state(iid)["log"] if e["role"] == "candidate"]
    assert cands == ["w", "c", "r", "t", "n"], cands
    print(f"NO QUESTION LOOP ({'split' if split else 'single'} messages): OK")


def warning_at_start_does_not_stall(inp, plan):
    """Regression: a tab switch during the opening. The spoken warning cut the interviewer off mid-question and
    ended with "Let's continue.", so the candidate never heard a question and the call sat silent.
    The warning must re-ask the current question, and the next answer must count for that question."""
    iid = c.post("/api/interviews", json={"plan": plan, "inputs": inp, "settings": {**NOP, "max_warnings": 2}}).json()["id"]
    a = c.post(f"/api/interviews/{iid}/assistant").json()["assistant"]
    p = llm_path(a)
    q1 = plan["questions"][0]["ask"]
    w = c.post(f"/api/interviews/{iid}/violation", json={"type": "tab_hidden"}).json()
    print("WARN AT START:", w["say"])
    assert w["action"] == "warn" and w["say"].rstrip().endswith(q1), "the warning must end by asking the question again"
    # Vapi history: the opening was interrupted after a few words, then the warning was spoken, then the answer.
    msgs = [{"role": "system", "content": "x"}, {"role": "assistant", "content": a["firstMessage"][:22]},
            {"role": "assistant", "content": w["say"]},
            {"role": "user", "content": "Sure. I'm Rohan, I have three years of backend experience with Spring Boot at ShipKart."}]
    say = turn(p, msgs)
    st = state(iid)
    print("AFTER WARNING:", say)
    assert [e["q_id"] for e in st["log"] if e["role"] == "candidate"] == [plan["questions"][0]["id"]]
    assert st["q_idx"] == 1 and plan["questions"][1]["ask"] in say, "the interview must move on to the next question"
    print("WARNING AT START: OK")


def opening_checks(inp, plan):
    """The opening discloses the AI and asks for recording consent; an unscored practice question comes first; saying no
    to recording ends politely; Hinglish gets its own lines; company questions are answered from the HR-approved FAQ."""
    import asyncio
    from backend import llm
    iid = c.post("/api/interviews", json={"plan": plan, "inputs": inp}).json()["id"]
    a = c.post(f"/api/interviews/{iid}/assistant").json()["assistant"]
    first = a["firstMessage"]
    assert "AI interviewer, not a person" in first and "recorded" in first and "practice question that doesn't count" in first, first
    p = llm_path(a)
    msgs = [{"role": "system", "content": "x"}, {"role": "assistant", "content": first}, {"role": "user", "content": "Pretty good, thanks"}]
    say = turn(p, msgs)
    assert say.startswith("Thanks, I can hear you clearly.") and plan["questions"][0]["ask"] in say, say
    st = state(iid)
    assert st["q_idx"] == 1 and st["log"][-1]["action"] == "next_question", st["log"][-1]
    # saying no to recording ends the interview and tells HR
    iid = c.post("/api/interviews", json={"plan": plan, "inputs": inp}).json()["id"]
    a = c.post(f"/api/interviews/{iid}/assistant").json()["assistant"]
    say = turn(llm_path(a), [{"role": "system", "content": "x"}, {"role": "assistant", "content": a["firstMessage"]},
                             {"role": "user", "content": "Sorry, I don't want this recorded."}])
    assert "different format" in say and say.count("concludes our interview") == 1, say
    rec = c.get(f"/api/interviews/{iid}").json()
    assert rec["state"]["ended"] and rec["status"] in ("completed", "scored", "incomplete"), rec["status"]
    assert brain.declines_recording("recording mat karo please") and brain.declines_recording("मुझे रिकॉर्डिंग नहीं चाहिए")
    assert not brain.declines_recording("I recorded a demo for the client") and not brain.declines_recording("Pretty good, thanks")
    # Hinglish lines
    iid = c.post("/api/interviews", json={"plan": plan, "inputs": inp, "settings": {"language": "hi-en"}}).json()["id"]
    first = c.post(f"/api/interviews/{iid}/assistant").json()["assistant"]["firstMessage"]
    assert "Main ek AI interviewer hoon" in first and "practice question" in first, first
    # the live judge sees the HR FAQ and the language
    seen = {}

    async def fake(system, user, *a, **k):
        seen["system"], seen["user"] = system, user
        return {"action": "answer_candidate_question", "reply": "Yes, three days a week in the office."}
    real, mock = llm.complete_json, llm.MOCK
    llm.complete_json, llm.MOCK = fake, False
    try:
        st = {"q_idx": 0, "fu_used": 0, "covered": {}, "log": []}
        asyncio.run(brain._judge(st, plan, "Is this role hybrid?", ["answer_candidate_question"],
                                 [{"q": "Is the role hybrid?", "a": "Yes, three days a week in the office."}], "hi-en"))
    finally:
        llm.complete_json, llm.MOCK = real, mock
    assert "three days a week" in seen["user"] and "Hinglish" in seen["user"] and "ONLY company_faq" in seen["system"], seen["user"][:400]
    print("OPENING (AI disclosure, consent, practice question, Hinglish, FAQ): OK")


def integrity_checks(inp, plan):
    """Leaving the interview: warnings spoken by the interviewer, then disqualification, enforced by the server."""
    assert "minutes" not in brain.opening_message(plan), "opening must not announce the length"
    iid = c.post("/api/interviews", json={"plan": plan, "inputs": inp, "settings": {**NOP,
        "max_warnings": 2, "candidate_email": "Cheat@Example.com"}}).json()["id"]
    v = f"/api/interviews/{iid}/violation"
    assert c.post(v, json={"type": "tab_hidden"}).json()["action"] == "ignored", "no call yet: nothing to enforce"
    a = c.post(f"/api/interviews/{iid}/assistant").json()["assistant"]
    p = llm_path(a)
    assert c.post(v, json={"type": "rm -rf"}).status_code == 400
    r1 = c.post(v, json={"type": "tab_hidden"}).json()
    print("WARN1:", r1["say"])
    assert r1["action"] == "warn" and r1["warning"] == 1 and "Rohan" in r1["say"]
    assert c.post(v, json={"type": "window_blur"}).json().get("debounced"), "one away-episode must count once"
    M_ = __import__("backend.main", fromlist=["x"])
    rec = json.loads((store.INT_DIR / f"{iid}.json").read_text())
    rec["warnings"][-1]["at"] -= 10
    (store.INT_DIR / f"{iid}.json").write_text(json.dumps(rec))
    r2 = c.post(v, json={"type": "window_blur"}).json()
    assert r2["action"] == "warn" and "final warning" in r2["say"], r2
    rec = json.loads((store.INT_DIR / f"{iid}.json").read_text())
    rec["warnings"][-1]["at"] -= 10
    (store.INT_DIR / f"{iid}.json").write_text(json.dumps(rec))
    r3 = c.post(v, json={"type": "multi_monitor", "detail": "screen.isExtended"}).json()
    print("TERMINATE:", r3["say"])
    assert r3["action"] == "terminate" and "concludes our interview" in r3["say"]
    rec = c.get(f"/api/interviews/{iid}").json()
    assert rec["disqualified"] and rec["status"] == "incomplete" and len(rec["warnings"]) == 3
    assert rec["proctoring"]["risk"] == "high" and rec["proctoring"]["reasons"][0].startswith("Disqualified")
    # a tampered page cannot carry on: the interviewer only says goodbye, and rejoining is refused
    say = turn(p, [{"role": "assistant", "content": a["firstMessage"]}, {"role": "user", "content": "anyway, my answer"}])
    assert "concludes our interview" in say.lower(), say
    r = c.post(f"/api/interviews/{iid}/assistant")
    assert r.status_code == 409 and "rules" in r.json()["detail"]
    assert c.get(f"/api/interviews/{iid}/public").json()["disqualified"]
    # warnings are in the transcript, and the next link for the same email warns HR
    txt = c.get(f"/api/interviews/{iid}/transcript.txt").text
    assert "final warning" in txt and "integrity_termination" in txt and "=== Question 1" in txt, txt[:600]
    again = c.post("/api/interviews", json={"plan": plan, "inputs": inp, "settings": {"candidate_email": "cheat@example.com"}}).json()
    assert again["warnings"] and "disqualified" in again["warnings"][0], again
    assert c.get("/api/candidates/history", params={"email": "CHEAT@example.com"}).json()["warnings"]
    row = next(x for x in c.get("/api/interviews").json() if x["id"] == iid)
    assert row["disqualified"] and row["warnings"] == 3
    # HR turned the rule off: nothing is enforced
    iid2 = c.post("/api/interviews", json={"plan": plan, "inputs": inp, "settings": {"enforce_focus": False}}).json()["id"]
    c.post(f"/api/interviews/{iid2}/assistant")
    assert c.post(f"/api/interviews/{iid2}/violation", json={"type": "tab_hidden"}).json()["action"] == "ignored"
    # max_warnings=0: the first violation ends it
    iid3 = c.post("/api/interviews", json={"plan": plan, "inputs": inp, "settings": {"max_warnings": 0}}).json()["id"]
    c.post(f"/api/interviews/{iid3}/assistant")
    assert c.post(f"/api/interviews/{iid3}/violation", json={"type": "tab_hidden"}).json()["action"] == "terminate"
    # screen snapshot is stored separately from camera snapshots
    from PIL import Image
    import io
    buf = io.BytesIO(); Image.new("RGB", (320, 180)).save(buf, "JPEG")
    c.post(f"/api/interviews/{iid2}/snapshot?reason=tab_hidden&source=screen", content=buf.getvalue())
    img = c.get(f"/api/interviews/{iid2}").json()["images"][-1]
    assert img["source"] == "screen" and img["file"] == "snap_001_screen_tab_hidden.jpg", img
    # readable question labels in HR text
    assert brain.question_label(plan, plan["questions"][1]["id"]).startswith("Question 2 (")
    _ = M_
    print("INTEGRITY: OK")


if __name__ == "__main__":
    main()
