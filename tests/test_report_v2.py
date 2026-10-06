"""The AI match report can't invent evidence:  python -m tests.test_report_v2
A fake AI returns a report with real quotes, invented quotes, an invented link id and a "proven" skill with no proof; the
system must strip every unverifiable bit, keep the rest, show the public findings, and never make a failure look like
success. A check passes when the problem does NOT happen."""
import json, os, socket, tempfile, threading, time
os.environ.update({"LLM_MOCK": "0", "OPENROUTER_API_KEY": "sk-or-fake", "DATA_DIR": tempfile.mkdtemp(), "DATABASE_URL": "", "ALLOW_SAMPLE_DATA": "1",
                   "APP_ENV": "development", "SKIP_EMAIL_VERIFICATION": "1", "SWEEP_EVERY_SEC": "0", "MESSAGES_EVERY_SEC": "0", "LLM_BACKUP": "off"})
import logging; logging.disable(logging.CRITICAL)
import uvicorn
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from backend import db, llm, matching, research
from backend.main import app

RES = []
def check(name, bug_if, detail=""):
    RES.append((name, bool(bug_if))); print(("FAIL " if bug_if else "ok   ") + "no longer: " + name + (f"  [{detail}]" if detail and bug_if else ""))

RESUME = """Asha Rao
Backend Engineer at Meridian Bank, Pune. 5 years.
Built the order-matching service in Java handling 2M events a day.
Reduced p95 latency by 40% with Redis caching.
Skills: Java, Kafka, Docker, Kubernetes"""
WEB = {f"W{i}" for i in (1, 2)}
raw = {"score": 140, "verdict": "amazing", "confidence": "very high", "summary": "Strong backend engineer.",
       "recommendation": {"action": "hire now", "why": "Because."},
       "must_haves": [{"skill": "Java", "status": "proven", "where": "Meridian Bank", "quote": "Built the order-matching service in Java handling 2M events a day"},
                      {"skill": "Kafka", "status": "proven", "where": "Meridian Bank", "quote": "Led the Kafka migration for all payments"},
                      {"skill": "Rust", "status": "missing", "where": "", "quote": ""}, {"skill": "", "status": "proven"}],
       "strengths": [{"point": "Cut latency", "quote": "Reduced p95 latency by 40% with Redis caching"}, {"point": "Invented strength", "quote": "Won the national coding award in 2019"}],
       "gaps": [{"point": "No Rust", "quote": ""}], "risks": ["A plain string risk"],
       "red_flags": [{"flag": "Inflated claim", "quote": "Managed a team of 500 engineers"}, {"flag": "Real quote flag", "quote": "Backend Engineer at Meridian Bank, Pune"}],
       "achievements": [{"what": "2M events a day", "quote": "handling 2M events a day"}, {"what": "Made up", "quote": "Saved the company 50 crore rupees"}],
       "career": {"total_years": 5, "jobs": "many", "avg_tenure_months": 9999, "trajectory": "sideways", "notes": "ok"},
       "online": {"consistency": "consistent", "notes": ["GitHub code is in Java"], "evidence_ids": ["W1", "W9"]},
       "interview_focus": [{"topic": "Kafka", "why": "Only listed", "question": "Walk me through a Kafka topic you designed."}], "verify_next": ["Call the Meridian referee"]}
rep = matching.clean_report(raw, RESUME, WEB)
mh = {m["skill"]: m for m in rep["must_haves"]}
check("an out-of-range score is kept", rep["score"] != 100, str(rep["score"]))
check("an unknown verdict is kept", rep["verdict"] == "amazing")
check("an unknown confidence is kept", rep["confidence"] == "very high")
check("a made-up recommendation action is kept", rep["recommendation"]["action"] != "hold")
check("a proven skill with a real quote is downgraded", mh["Java"]["status"] != "proven")
check("a proven skill with an invented quote stays proven", mh["Kafka"]["status"] == "proven", str(mh["Kafka"]))
check("an invented quote is kept on a skill", mh["Kafka"]["quote"] != "")
check("a nameless skill is kept", "" in mh)
check("an invented strength is kept", any("Invented" in x for x in rep["strengths"]))
check("a real strength is dropped", not any("Cut latency" in x for x in rep["strengths"]))
check("a gap with no quote (about something absent) is dropped", not rep["gaps"])
check("a plain-string risk is dropped", not rep["risks"])
check("an inflated claim with an invented quote is kept as a red flag", any("Inflated" in x["flag"] for x in rep["red_flags"]))
check("a red flag with a real quote is dropped", not any("Real quote" in x["flag"] for x in rep["red_flags"]))
check("an invented achievement is kept", any("Made up" in x["what"] for x in rep["achievements"]))
check("a real achievement is dropped", not any("2M events" in x["what"] for x in rep["achievements"]))
check("a non-numeric job count is kept", rep["career"]["jobs"] is not None)
check("an absurd tenure isn't capped", rep["career"]["avg_tenure_months"] != 600)
check("an unknown trajectory is kept", rep["career"]["trajectory"] != "unclear")
check("an invented evidence id is kept", "W9" in rep["online"]["evidence_ids"])
check("a real evidence id is dropped", "W1" not in rep["online"]["evidence_ids"])
check("the interview questions aren't derived from the focus", rep["interview_questions"] != ["Walk me through a Kafka topic you designed."])
check("no evidence at all still claims 'consistent'", matching.clean_report(raw, RESUME, set())["online"]["consistency"] != "not_checked")
check("a quote with different spacing or case doesn't match", not matching.clean_report({"strengths": [{"point": "x", "quote": "reduced  P95 latency by 40%  with redis caching"}]}, RESUME, set())["strengths"])
check("the schema marker is missing", rep.get("schema") != 2)
para = matching.clean_report({"strengths": [{"point": "Faster", "quote": "Reduced p95 latency by 40% using Redis caching"}]}, RESUME, set())["strengths"]
check("a near-exact quote (one word swapped) is dropped", not para)
sn = matching.clean_report({"strengths": [{"point": "Faster", "quote": "reduced p95 latency by 40% using redis caching"}]}, RESUME, set())["strengths_detail"]
check("a near-exact quote isn't shown in the resume's own words", not sn or sn[0]["quote"].rstrip(".") != "Reduced p95 latency by 40% with Redis caching", str(sn))
check("a quote under four words is accepted", bool(matching.clean_report({"strengths": [{"point": "x", "quote": "Redis caching"}]}, RESUME, set())["strengths"]))
check("a quote with half its words invented is accepted", bool(matching.clean_report({"strengths": [{"point": "x", "quote": "Reduced the cost of the cloud bill by 90% at Meridian"}]}, RESUME, set())["strengths"]))

# ---------------------------------------------------------------- through the app, with a fake AI and a fake internet
CALLS = []
fake = FastAPI()
@fake.post("/v1/chat/completions")
async def chat(req: Request):
    b = await req.json(); CALLS.append(b)
    return {"id": "x", "object": "chat.completion", "created": 1, "model": b["model"], "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps(raw)}}]}
port = (lambda s: (s.bind(("127.0.0.1", 0)), s.getsockname()[1], s.close())[1])(socket.socket())
threading.Thread(target=uvicorn.Server(uvicorn.Config(fake, port=port, log_level="error")).run, daemon=True).start(); time.sleep(1.5)
llm.apply_config({}); llm.PROVIDERS["openrouter"]["base_url"] = f"http://127.0.0.1:{port}/v1"; llm._clients.clear()

c = TestClient(app)
assert c.post("/api/auth/signup", json={"email": "o@a.test", "password": "password-123", "name": "O", "company": "Acme"}).status_code == 200
assert c.post("/api/demo/seed").status_code == 200
jobs = c.get("/api/jobs").json(); jobs = jobs["items"] if isinstance(jobs, dict) else jobs
job = jobs[0]
items = c.get(f"/api/jobs/{job['id']}/matches?limit=5").json()["items"]
cand = items[0]["candidate"]
with db.session() as s:
    cd = s.get(db.Candidate, cand["id"])
    cd.resume_text = RESUME; cd.name = "Asha Rao"
FOUND = {"v": 2, "at": time.time(), "items": [
    {"id": "W1", "kind": "GitHub", "status": "confirmed", "url": "https://github.com/asharao", "evidence": ["the candidate's own link"], "source": "resume", "github": {"own_repos": 3, "langs": ["java"], "last_push": "2026-09-01", "followers": 41, "top_repos": []}},
    {"id": "W2", "kind": "LinkedIn", "status": "possible", "url": "https://in.linkedin.com/in/asha-rao-pune", "evidence": ["the full name matches", "same city"], "source": "web search", "about": "Backend engineer"}],
    "notes": ["The phone number was not searched (numbers are reassigned and searches mostly find other people)."], "queries": ['"Asha Rao" Meridian Bank'], "used": {"search": "tavily"}}
GATHERS = []
async def fake_gather(cid, force=False):
    GATHERS.append(force); return FOUND
research.gather = fake_gather
r = c.post(f"/api/jobs/{job['id']}/match/{cand['id']}/ai-report"); j = r.json()
check("the report call fails", r.status_code != 200 or j.get("generated") != 1, r.text[:200])
sent = CALLS[-1]["messages"][1]["content"]
check("the public findings aren't in the prompt", "PUBLIC EVIDENCE" not in sent or "W1" not in sent or "github.com/asharao" not in sent)
check("the resume isn't in the prompt", "order-matching service" not in sent)
check("the pre-screen isn't in the prompt", "keyword pre-screen score" not in sent)
check("the system prompt doesn't forbid inventing facts", "Never add employers" not in CALLS[-1]["messages"][0]["content"])
check("the report asks for too little room", CALLS[-1].get("max_tokens", 0) < 3000, str(CALLS[-1].get("max_tokens")))
m = c.get(f"/api/jobs/{job['id']}/match/{cand['id']}").json()
ai = m["ai"]
check("the stored report isn't schema 2", ai.get("schema") != 2)
check("the stored report keeps an invented quote", "Won the national" in json.dumps(ai) or "Managed a team of 500" in json.dumps(ai))
check("the found-online items aren't stored with the report", [i["id"] for i in (ai.get("web") or {}).get("items", [])] != ["W1", "W2"])
check("'what wasn't checked' isn't stored", not (ai.get("web") or {}).get("notes"))
check("the pre-screen score isn't stored for comparison", ai.get("prescreen_score") is None)
check("the resume size isn't recorded", not (ai.get("based_on") or {}).get("resume_chars"))
check("the AI score isn't the cleaned one", m["ai_score"] != 100)
check("the first report forced a fresh lookup", GATHERS and GATHERS[0] is True)
GATHERS.clear()
r = c.post(f"/api/jobs/{job['id']}/match/{cand['id']}/ai-report?refresh=1")
check("a rewrite doesn't force a fresh public lookup", True not in GATHERS, str(GATHERS))

# the AI fails: the automatic summary says why, and doesn't overwrite the real report
llm.PROVIDERS["openrouter"]["base_url"] = "http://127.0.0.1:1/v1"; llm._clients.clear(); llm._BLOCKED.clear()
r = c.post(f"/api/jobs/{job['id']}/match/{cand['id']}/ai-report?refresh=1"); j = r.json()
m2 = c.get(f"/api/jobs/{job['id']}/match/{cand['id']}").json()
check("a failed rewrite replaces the real report", (m2["ai"] or {}).get("source") == "rules", str((m2["ai"] or {}).get("source")))
check("a failed rewrite gives no reason", not j.get("error"))
other = items[1]["candidate"]
r = c.post(f"/api/jobs/{job['id']}/match/{other['id']}/ai-report"); j2 = r.json()
m3 = c.get(f"/api/jobs/{job['id']}/match/{other['id']}").json()
check("the automatic summary doesn't record why the AI failed", not (m3["ai"] or {}).get("why_no_ai"), str(m3["ai"])[:200])
check("the automatic summary has an AI score", m3.get("ai_score") is not None)

bad = [n for n, f in RES if f]
assert not bad, f"{len(bad)} report check(s) failed: {bad}"
print(f"REPORT V2 CHECKS PASSED ({len(RES)})")
