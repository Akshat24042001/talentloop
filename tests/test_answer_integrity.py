"""Answers that may not be the candidate's own:  python -m tests.test_answer_integrity
The live interviewer's "scripted"/"contradiction" signals reach the integrity risk, and the scorer's authenticity
verdict needs real quotes before it says "likely assisted". A check passes when the problem does NOT happen."""
import asyncio
import os
import tempfile

os.environ.update({"LLM_MOCK": "0", "OPENROUTER_API_KEY": "sk-or-fake", "DATA_DIR": tempfile.mkdtemp(), "DATABASE_URL": "", "SCORING_PASSES": "1"})
import logging  # noqa: E402
logging.disable(logging.CRITICAL)
from backend import brain, prompts, proctor  # noqa: E402

RES = []


def check(name, bug_if, detail=""):
    RES.append((name, bool(bug_if)))
    print(("FAIL " if bug_if else "ok   ") + "no longer: " + name + (f"  [{detail}]" if detail and bug_if else ""))


check("the live prompt doesn't ask for integrity signals", "signal" not in prompts.TURN_SYSTEM or "{claims}" not in prompts.TURN_USER_TEMPLATE)
check("the live prompt lets nervousness or accents count as signals", "never signals" not in prompts.TURN_SYSTEM)
check("the scorer doesn't judge authenticity", "authenticity" not in prompts.SCORE_USER_TEMPLATE)
check("the scorer may lower scores for authenticity", "Never lower question scores for this" not in prompts.SCORE_SYSTEM)

plan = brain.normalize_plan({"role": "Backend", "candidate_name": "A", "company": "C", "duration_min": 15,
                             "questions": [{"id": "q1", "ask": "Tell me about caching.", "scored": True, "type": "resume_probe"}]})
said = "Caching is a technique that stores frequently accessed data in a fast storage layer to reduce latency."
rec = {"id": "x", "plan": plan, "events": [], "settings": {}, "status": "completed",
       "state": {"log": [{"role": "ai", "text": "Tell me about caching.", "q_id": "q1", "t": 0, "ts": 1},
                         {"role": "candidate", "text": said, "q_id": "q1", "t": 40, "ts": 41}],
                 "signals": [{"q_id": "q1", "kind": "scripted", "detail": "textbook definition, no own example", "t": 40},
                             {"q_id": "q1", "kind": "contradiction", "detail": "said 2 years, resume says 5", "t": 90}],
                 "notes": {}, "covered": {}, "skipped": []}}
p = proctor.summary(rec)
check("live signals don't reach the integrity summary", not any("sounded read" in r for r in p["reasons"]), str(p["reasons"]))
check("live signals alone make the risk high", p["risk"] == "high")


async def fake(rec_, transcript, model):
    return {"questions": [{"q_id": "q1", "score": 3, "evidence": [{"quote": said[:40], "t": "00:40"}], "rationale": "ok"}],
            "recommendation": "maybe", "summary": "s", "_model": "fake",
            "authenticity": {"level": "likely_assisted", "note": "n", "signals": [
                {"sign": "Recited a textbook definition", "quote": said[:50], "t": "00:40"},
                {"sign": "Invented quote", "quote": "I used Redis Cluster with 40 shards in Mumbai", "t": "01:10"}]}}
brain._score_once = fake
rep = asyncio.run(brain.score_interview(rec))
au = rep.get("authenticity") or {}
check("'likely assisted' stands on a quote the candidate never said", au.get("level") == "likely_assisted", str(au)[:200])
check("signs aren't checked against the transcript", not any(x.get("verified") == "unverified" for x in au.get("signals", [])))
check("HR isn't asked to review possible outside help", not any("may not be the candidate's own" in r for r in rep["human_review_reasons"]))
check("the authenticity verdict changed the question score", rep["questions"][0]["score"] != 3)

bad = [n for n, f in RES if f]
assert not bad, f"{len(bad)} integrity check(s) failed: {bad}"
print(f"ANSWER INTEGRITY CHECKS PASSED ({len(RES)})")
