"""Follow-up quality of the live interviewer:  python -m tests.test_followups
A check passes when the problem does NOT happen."""
import asyncio, os, tempfile
os.environ.update({"LLM_MOCK": "1", "DATA_DIR": tempfile.mkdtemp(), "DATABASE_URL": os.getenv("TEST_DATABASE_URL", "")})
from backend import brain, prompts

RES = []
def check(name, bug_if, detail=""):
    RES.append((name, bool(bug_if))); print(("FAIL " if bug_if else "ok   ") + "no longer: " + name + (f"  [{detail}]" if detail and bug_if else ""))

plan = brain.normalize_plan({"duration_min": 30, "company": "Acme", "role": "Backend Engineer", "candidate_name": "Rohan", "questions": [
    {"id": "q1", "type": "warmup", "ask": "Tell me about yourself.", "scored": False, "max_followups": 0, "time_budget_sec": 60},
    {"id": "q2", "type": "resume_probe", "ask": "How did you cut latency in the tracking API?", "scored": True, "max_followups": 2, "time_budget_sec": 200,
     "good_answer_covers": ["names the bottleneck", "explains the fix", "gives a number", "says what they owned"]},
    {"id": "q3", "type": "jd_skill", "ask": "How do you design a retry policy?", "scored": True, "max_followups": 1, "time_budget_sec": 150, "good_answer_covers": ["backoff"]}]})
rec = {"id": "x", "plan": plan, "settings": {}, "events": [], "snapshots": []}
brain.start_session(rec)
st = rec["state"]
# the answer to q2 arrives in three pieces; q1's words and the interviewer's lines are not part of it
st["log"] += [{"role": "candidate", "text": "I am Rohan from Pune", "q_id": "q1", "t": 5, "ts": 1},
              {"role": "ai", "text": "Nice. How did you cut latency?", "q_id": "q2", "action": "next_question", "t": 9, "ts": 2},
              {"role": "candidate", "text": "We added caching", "q_id": "q2", "t": 20, "ts": 3},
              {"role": "ai", "text": "Please go on.", "q_id": "q2", "action": "invite_continue", "t": 21, "ts": 4},
              {"role": "candidate", "text": "and also some indexes", "q_id": "q2", "t": 30, "ts": 5}]
so_far = brain.answer_so_far(st, "q2", "on the orders table")
check("a piece of the answer is missing from the whole answer", not all(x in so_far for x in ["caching", "indexes", "orders table"]), so_far)
check("the previous question's words are part of this answer", "Pune" in so_far)
check("the prompt does not carry the whole answer", "{so_far}" not in prompts.TURN_USER_TEMPLATE or "answer_so_far" not in prompts.TURN_SYSTEM)
check("the prompt does not carry the follow-ups already asked", "{fu_asked}" not in prompts.TURN_USER_TEMPLATE)
check("the prompt does not carry the points still missing", "{uncovered}" not in prompts.TURN_USER_TEMPLATE)

def turn(said, d, qi=1):
    r = {"id": "x", "plan": plan, "settings": {}, "events": [], "snapshots": [], "state": None}
    brain.start_session(r); s = r["state"]; s["q_idx"] = qi; s["q_started_active"] = 0.0
    s["display"] = brain._display(plan["questions"][qi]); s["last_say"] = plan["questions"][qi]["ask"]
    r["snapshots"] = [brain._snap(s)]
    prep = brain.prepare_turn(r, [{"role": "assistant", "content": s["last_say"]}, {"role": "user", "content": said}])
    if "reply" in prep:
        return "reply", prep["reply"], r
    prep["active"] = 100.0     # well past the "don't rush" window, so only the coverage rule can decide
    s2 = prep["st"]; s2["q_started_active"] = 0.0
    say = brain.apply_turn(r, prep, d, 50, False)
    return r["state"]["log"][-1].get("action"), say, r

LONG = "We improved a lot of things in the system over time and the team worked on many parts of it together, it was a good learning " * 3
act, say, _ = turn(LONG, {"action": "next_question", "ack": "Got it.", "followup": "You said many parts of it. Which part did you change yourself?", "covered": [1]})
check("a long generic answer with most key points missing moves on", act != "follow_up", f"{act}: {say}")
act, say, _ = turn(LONG, {"action": "next_question", "ack": "Got it.", "followup": "", "covered": [0, 1, 2]})
check("an answer that covered most points is probed anyway", act != "next_question", f"{act}: {say}")
act, say, _ = turn("I don't know, let's move on", {"action": "next_question", "ack": "Okay.", "followup": "Which part did you change?", "covered": []})
check("someone who says they don't know is grilled", act == "follow_up", say)
act, say, r = turn(LONG, {"action": "next_question", "ack": "Got it.", "followup": "You said many parts of it. Which part did you change yourself?", "covered": [1]})
check("the probe is not about the candidate's own words", "which part" not in say.lower(), say)
check("the interview state did not stay on the same question after the probe", r["state"]["q_idx"] != 1)
act, say, r = turn(LONG, {"action": "next_question", "ack": "Got it.", "followup": "Which part?", "covered": []}, qi=2)
check("a question with one key point and a missing probe is probed twice", act == "follow_up" and r["state"]["fu_used"] > 1)

# barge-in: the candidate cuts in while the interviewer is speaking; Vapi keeps only the words actually spoken
def cut_turn(said):
    r = {"id": "x", "plan": plan, "settings": {}, "events": [], "snapshots": [], "state": None}
    brain.start_session(r); s = r["state"]; s["q_idx"] = 1; s["display"] = brain._display(plan["questions"][1])
    s["last_say"] = "Thanks, that's clear. Let's switch gears a bit. How did you cut latency in the tracking API?"; r["snapshots"] = [brain._snap(s)]
    return brain.prepare_turn(r, [{"role": "assistant", "content": "Thanks, that's clear. Let's switch gears a bit."}, {"role": "user", "content": said}])
p1 = cut_turn("sorry, wait")
check("'wait' while the interviewer speaks is not answered with 'go ahead'", "go ahead" not in p1.get("reply", "").lower(), str(p1)[:120])
p2 = cut_turn("sorry, please continue")
check("'please continue' after a cut-off line does not repeat the question", "tracking API" not in p2.get("reply", ""), str(p2)[:120])
p3 = cut_turn("I think the main issue was the database queries, we added indexes")
check("an early answer after cutting in is not judged as an answer", "reply" in p3 or not p3.get("cut_off"), str(p3)[:120])
check("the judge is not told what the candidate did not hear", "tracking API" not in p3.get("unheard", ""))
from backend import vapi_config

bad = [n for n, b in RES if b]
print(f"\n{len(RES) - len(bad)}/{len(RES)} ok"); raise SystemExit(1 if bad else 0)
