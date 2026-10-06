"""AI reports keep working when the main provider fails:  python -m tests.test_ai_backup
Fake servers stand in for OpenRouter (daily free limit used up) and a backup provider. A check passes when the problem
does NOT happen."""
import os, socket, tempfile, threading, time
os.environ.update({"LLM_MOCK": "0", "OPENROUTER_API_KEY": "sk-or-fake", "OPENAI_API_KEY": "sk-fake", "DATA_DIR": tempfile.mkdtemp(), "DATABASE_URL": "",
                   "ALLOW_SAMPLE_DATA": "1", "APP_ENV": "development", "SKIP_EMAIL_VERIFICATION": "1", "SWEEP_EVERY_SEC": "0", "MESSAGES_EVERY_SEC": "0"})
import logging; logging.disable(logging.CRITICAL)
import asyncio
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from backend import db, llm
from backend.main import app

RES = []
def check(name, bug_if, detail=""):
    RES.append((name, bool(bug_if))); print(("FAIL " if bug_if else "ok   ") + "no longer: " + name + (f"  [{detail}]" if detail and bug_if else ""))

CALLS = {"or": 0, "bk": 0}
MODE = {"or": "daily", "bk": "ok"}
REPORT = {"score": 77, "verdict": "good", "summary": "Backup wrote this.", "strengths": ["s"], "gaps": ["g"], "risks": [], "interview_questions": ["q"]}
def chat_reply(model, content):
    return {"id": "x", "object": "chat.completion", "created": 1, "model": model,
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}]}
or_app, bk_app = FastAPI(), FastAPI()
@or_app.post("/v1/chat/completions")
async def or_chat(req: Request):
    CALLS["or"] += 1
    b = await req.json()
    if MODE["or"] == "daily":
        return JSONResponse({"error": {"message": "Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000 free model requests per day", "code": 429}}, status_code=429)
    return chat_reply(b["model"], '{"score": 66, "verdict": "good", "summary": "Main wrote this.", "strengths": [], "gaps": [], "risks": [], "interview_questions": []}')
@bk_app.post("/v1/chat/completions")
async def bk_chat(req: Request):
    CALLS["bk"] += 1
    b = await req.json()
    if MODE["bk"] == "down":
        return JSONResponse({"error": {"message": "Service unavailable", "code": 503}}, status_code=503)
    import json
    return chat_reply(b["model"], json.dumps(REPORT))

def serve(a):
    port = (lambda s: (s.bind(("127.0.0.1", 0)), s.getsockname()[1], s.close())[1])(socket.socket())
    threading.Thread(target=uvicorn.Server(uvicorn.Config(a, port=port, log_level="error")).run, daemon=True).start()
    return port
p_or, p_bk = serve(or_app), serve(bk_app)
time.sleep(1.5)
def point():
    llm.PROVIDERS["openrouter"]["base_url"] = f"http://127.0.0.1:{p_or}/v1"
    llm.PROVIDERS["openai"]["base_url"] = f"http://127.0.0.1:{p_bk}/v1"
    llm._BLOCKED.clear(); llm._clients.clear()
point()
llm.apply_config({}); point()
check("the main provider isn't OpenRouter in this test", llm.FAST_PROVIDER != "openrouter", llm.FAST_PROVIDER)
check("OpenAI isn't seen as a backup provider", ("openai", "gpt-4.1-mini") not in llm._backup_targets(llm.FAST_MODEL), str(llm._backup_targets(llm.FAST_MODEL)))

LOOP = asyncio.new_event_loop()      # one loop, like the server: the HTTP clients are cached across calls
def call(**kw):
    return LOOP.run_until_complete(llm.complete_json("Output JSON", "Rate this", llm.FAST_MODEL, max_tokens=700, **kw))

out = call()
check("a daily-limit refusal with a backup configured gives no answer", out.get("summary") != "Backup wrote this.", str(out))
check("the answer doesn't say which provider wrote it", not str(out.get("_backup", "")).startswith("openai"))
n_or = CALLS["or"]
check("the daily limit isn't tried on every model of the chain", n_or > 2, str(n_or))
call()
check("OpenRouter is asked again right after its daily limit was reached", CALLS["or"] != n_or, f"{CALLS['or']} vs {n_or}")
check("the breaker isn't recorded", not llm._blocked("openrouter"))
try:
    call(backup=False); raised = None
except Exception as e:
    raised = e
check("with the backup off, a daily limit doesn't raise", raised is None)
check("the refusal isn't named in the error", "daily" not in str(raised).lower())
os.environ["LLM_BACKUP"] = "off"
try:
    call(); raised = None
except Exception as e:
    raised = e
check("LLM_BACKUP=off still uses a backup provider", raised is None)
os.environ.pop("LLM_BACKUP")

# --- through the app: one candidate's report
c = TestClient(app)
assert c.post("/api/auth/signup", json={"email": "o@a.test", "password": "password-123", "name": "O", "company": "Acme"}).status_code == 200
assert c.post("/api/demo/seed").status_code == 200
jobs = c.get("/api/jobs").json(); jobs = jobs["items"] if isinstance(jobs, dict) else jobs
job = next(j for j in jobs if j["title"] == "Senior Backend Engineer") if any(j["title"] == "Senior Backend Engineer" for j in jobs) else jobs[0]
items = c.get(f"/api/jobs/{job['id']}/matches?limit=10").json()
cand = items["items"][0]["candidate"]
point(); MODE.update(or_="daily", bk="down")
r = c.post(f"/api/jobs/{job['id']}/match/{cand['id']}/ai-report")
check("with every provider down the button returns an error page", r.status_code != 200, r.text[:200])
j = r.json()
check("the reason isn't shown", not j.get("error") or "daily" not in j["error"].lower(), str(j))
check("the message doesn't say how to lift the limit", "$10" not in j.get("error", ""))
check("no automatic summary is kept", not j.get("fallback"))
m = c.get(f"/api/jobs/{job['id']}/match/{cand['id']}").json()
check("the report page doesn't show the automatic summary", (m.get("ai") or {}).get("source") != "rules", str(m.get("ai"))[:150])
check("the automatic summary pretends to have an AI score", m.get("ai_score") is not None)
check("the automatic summary says nothing about the match", not (m.get("ai") or {}).get("summary", "").startswith(cand["name"].split()[0]) and "match" not in (m.get("ai") or {}).get("summary", ""))
check("the automatic summary invents a verdict", (m.get("ai") or {}).get("verdict"))
check("the match is counted as having its AI report", c.get(f"/api/jobs/{job['id']}/matches?limit=10").json()["ai_pending"] == 0)

point(); MODE.update(or_="daily", bk="ok")
r = c.post(f"/api/jobs/{job['id']}/match/{cand['id']}/ai-report"); j = r.json()
check("the backup provider doesn't write the report", j.get("generated") != 1, str(j))
m = c.get(f"/api/jobs/{job['id']}/match/{cand['id']}").json()
check("the report is not the backup's", (m.get("ai") or {}).get("summary") != "Backup wrote this.")
check("the AI score isn't stored", m.get("ai_score") != 77, str(m.get("ai_score")))
with db.session() as s:
    row = s.query(db.Match).filter_by(job_id=job["id"], candidate_id=cand["id"]).first()
    check("the model that really answered isn't recorded", "gpt-4.1-mini" not in (row.ai_model or ""), str(row.ai_model))
    check("the usage isn't billed to the backup's model", s.query(db.AIUsage).filter(db.AIUsage.model.like("%gpt%")).count() == 0)

# a good report is never replaced by an automatic summary when the AI fails later
point(); MODE.update(or_="daily", bk="down")
r = c.post(f"/api/jobs/{job['id']}/match/{cand['id']}/ai-report"); j = r.json()
m = c.get(f"/api/jobs/{job['id']}/match/{cand['id']}").json()
check("a failed rewrite replaces the good report", (m.get("ai") or {}).get("summary") != "Backup wrote this." or m.get("ai_score") != 77, str(m.get("ai"))[:120])
check("a failed rewrite is reported as success", j.get("generated") == 1)

bad = [n for n, f in RES if f]
assert not bad, f"{len(bad)} AI backup check(s) failed: {bad}"
print(f"AI BACKUP CHECKS PASSED ({len(RES)})")
