"""The AI interview under attack: every way a live call has gone wrong, replayed against the real endpoint.
python -m tests.test_interview_chaos

The live model is replaced by a scripted one that misbehaves on purpose (errors, timeouts, invalid actions,
off-topic follow-ups, questions hidden in acknowledgements, invented salaries, protected-trait questions), and
the candidate side sends what real calls send (backchannels, the interviewer's own echo, silence, a candidate
who runs out of time). Each check states the failure; it passes when the failure does not happen."""
import asyncio
import json
import os
import tempfile

os.environ.update({"ALLOW_SAMPLE_DATA": "1", "LLM_MOCK": "1", "PUBLIC_URL": "https://example.trycloudflare.com", "VAPI_PUBLIC_KEY": "pk_test",
                   "ADMIN_KEY": "test-admin-key-123456", "FINISH_DELAY_SEC": "0", "DATA_DIR": tempfile.mkdtemp(),
                   "DATABASE_URL": os.getenv("TEST_DATABASE_URL", "")})
import logging  # noqa: E402
logging.disable(logging.CRITICAL)

from fastapi.testclient import TestClient  # noqa: E402

from backend import brain, store  # noqa: E402
from backend.main import app  # noqa: E402

c = TestClient(app, headers={"X-Admin-Key": "test-admin-key-123456"}, raise_server_exceptions=False)
RES = []


def check(name, bad, detail=""):
    RES.append((name, bool(bad)))
    print(("FAIL " if bad else "ok   ") + "never: " + name + (f"  [{detail}]" if bad and detail else ""))


def sse(r):
    return "".join(json.loads(l[6:])["choices"][0]["delta"].get("content", "") for l in r.text.splitlines() if l.startswith("data: {"))


PLAN = brain.normalize_plan({"duration_min": 20, "company": "Acme", "role": "Backend Developer", "candidate_name": "Asha Rao",
    "company_facts": ["Acme builds payment software", "The team is in Pune"], "questions": [
        {"id": "w", "type": "warmup", "ask": "Please introduce yourself briefly.", "time_budget_sec": 60, "max_followups": 0},
        {"id": "r", "type": "resume_probe", "ask": "Tell me about the caching work on your last project. What did you build?", "max_followups": 2},
        {"id": "b", "type": "behavioral", "ask": "Tell me about a disagreement with a teammate. How did you handle it?", "max_followups": 1},
        {"id": "n", "type": "hr_mandatory", "ask": "What is your notice period?", "max_followups": 0}]})
LONG = (" I worked on it for about eight months with two other engineers, measured the slow endpoints first, then added a cache layer"
        " in front of the product catalogue, and we watched the hit rate and the error budget every week afterwards.")
script: list = []


async def scripted_judge(st, plan, said, allowed, faq=None, lang="en"):
    if not script:
        return {"action": "next_question", "ack": "Thanks."}
    x = script.pop(0)
    if isinstance(x, Exception):
        raise x
    return x


brain._judge = scripted_judge


def new_call():
    iid = c.post("/api/interviews", json={"plan": PLAN, "inputs": {}, "settings": {"practice_question": False}}).json()["id"]
    a = c.post(f"/api/interviews/{iid}/assistant").json()["assistant"]
    path = "/llm/" + a["model"]["url"].split("/llm/", 1)[1] + "/chat/completions"
    return iid, path, [{"role": "system", "content": "x"}, {"role": "assistant", "content": a["firstMessage"]}]


def say(path, msgs, text):
    msgs.append({"role": "user", "content": text})
    r = c.post(path, json={"messages": msgs, "stream": True})
    out = sse(r) if r.status_code == 200 else ""
    msgs.append({"role": "assistant", "content": out})
    return r.status_code, out


def st(iid):
    return c.get(f"/api/interviews/{iid}").json()["state"]


iid, path, msgs = new_call()
say(path, msgs, "Hi, I'm Asha, a backend developer from Pune with four years of experience in Java services.")   # warmup -> q1 (r)
q0 = st(iid)["q_idx"]

# 1. the live model fails on a short answer: no jump to the next question
script[:] = [TimeoutError("model timed out")]
_, out = say(path, msgs, "I used Redis.")
check("a model timeout on a short answer skips to the next question", st(iid)["q_idx"] != q0, out)

# 2. an invalid action from a confused model
script[:] = [{"action": "fire_the_candidate", "ack": "Bye."}]
_, out = say(path, msgs, "We cached product pages.")
check("an invalid model action moves the interview on", st(iid)["q_idx"] != q0, out)

# 3. a follow-up about a protected trait, and an ack that hides a question
script[:] = [{"action": "follow_up", "ack": "Nice. Are you married?", "followup": "How old are you, and do you have kids?"}]
_, out = say(path, msgs, "We cached product pages and API responses." + LONG)
check("the interviewer asks about age, marriage or family", any(w in out.lower() for w in ("married", "how old", "kids")), out)

# 4. an invented salary when the candidate asks about pay
script[:] = [{"action": "answer_candidate_question", "reply": "The salary is 25 lakhs plus a 10 percent bonus."}]
_, out = say(path, msgs, "Before I continue, what's the salary for this role?")
check("the interviewer states a salary that no approved fact contains", "25" in out or "10 percent" in out, out)
check("after answering a candidate's question the interviewer doesn't return to the interview", "?" not in out, out)

# 5. backchannels and echo are not answers
before = st(iid)["q_idx"]
script[:] = [{"action": "next_question", "ack": "Thanks."}]
_, out = say(path, msgs, "Okay, yeah.")
check("'okay, yeah' while listening counts as an answer and moves on", st(iid)["q_idx"] != before, out)
_, out = say(path, msgs, st(iid)["last_say"])
check("the interviewer's own voice (echo) counts as an answer", st(iid)["q_idx"] != before, out)

# 6. an internal error inside the turn: the call must survive with a safe line
orig = brain.prepare_turn
brain.prepare_turn = lambda rec, m: (_ for _ in ()).throw(KeyError("boom"))
code, out = say(path, msgs, "Shall I continue with the cache details?")
brain.prepare_turn = orig
check("an internal error ends the call (non-200 to Vapi)", code != 200, str(code))
check("after an internal error the interviewer says nothing useful", "missed" not in out.lower(), out)

# 7. the follow-up the model writes is an off-topic monologue
script[:] = [{"action": "follow_up", "ack": "Ok.", "followup": "Let me tell you about our company history " * 8}]
_, out = say(path, msgs, "I mostly did the backend part.")
check("a rambling, question-less follow-up is spoken", "company history" in out, out[:120])

# 8. out of time with HR's must-ask question still pending
iid2, path2, m2 = new_call()
say(path2, m2, "Hi, I'm Asha." + LONG)
rec = store.load(iid2)
rec["state"]["session_started"] -= PLAN["duration_min"] * 60          # the clock ran out mid-interview
store.save(rec)
script[:] = [{"action": "end", "ack": "Thanks."}]
_, out = say(path2, m2, "That's my caching project." + LONG)
check("time running out skips HR's must-ask question", "notice period" not in out.lower() and "concludes" in out.lower(), out[:160])

# 9. plan grounding: invented resume claims, duplicates, HR questions dropped by the model
raw = {"duration_min": 15, "questions": [
    {"type": "resume_probe", "ask": "You cut latency by 73% at Infosys. How?"},
    {"type": "jd_skill", "ask": "How do you design a REST API?"},
    {"type": "jd_skill", "ask": "How do you design a REST API?"}]}
g = brain.ground_plan(brain.normalize_plan(raw), {"resume": "Backend developer at TCS. Java, Redis.", "jd": "REST APIs", "questions": ["Are you okay with night shifts?"]})
asks = [q["ask"] for q in g["questions"]]
check("a made-up resume claim (73% at Infosys) reaches the candidate", any("73" in a or "Infosys" in a for a in asks), str(asks))
check("a duplicated question is asked twice", asks.count("How do you design a REST API?") > 1, str(asks))
check("an HR question the model left out is never asked", not any("night shifts" in a for a in asks), str(asks))

# 10. camera-based signals never end the interview; leaving the screen still does
iid3, path3, m3 = new_call()
say(path3, m3, "Hi, I'm Asha." + LONG)
acts = [c.post(f"/api/interviews/{iid3}/violation", json={"type": k, "detail": "test"}).json().get("action")
        for k in ("left_camera", "multiple_people", "quick_switches")]
for _ in range(6):
    rec = store.load(iid3); [r.__setitem__("at", r["at"] - 120) for r in rec.get("reminders", [])]; store.save(rec)
    acts.append(c.post(f"/api/interviews/{iid3}/violation", json={"type": "left_camera", "detail": "test"}).json().get("action"))
check("camera reminders stop the interview", "terminate" in acts or store.load(iid3).get("disqualified"), str(acts))
hard = []
for _ in range(4):
    rec = store.load(iid3); [w.__setitem__("at", w["at"] - 10) for w in rec.get("warnings", [])]; store.save(rec)
    hard.append(c.post(f"/api/interviews/{iid3}/violation", json={"type": "tab_hidden", "detail": "test"}).json().get("action"))
check("leaving the tab after the final warning does not stop the interview", "terminate" not in hard, str(hard))

# 11. the Vapi config: backchannels don't interrupt the interviewer
a = c.post(f"/api/interviews/{iid}/assistant").json().get("assistant") or {}
ssp = a.get("stopSpeakingPlan") or {}
check("'okay' / 'mm-hmm' can cut the interviewer off mid-question", "okay" not in (ssp.get("acknowledgementPhrases") or []), str(ssp)[:200])

bad = [n for n, b in RES if b]
assert not bad, f"{len(bad)} interview check(s) failed: {bad}"
print(f"\nINTERVIEW CHAOS CHECKS PASSED ({len(RES)})")
