"""Write with AI for job descriptions:  python -m tests.test_ai_write

Runs with a fake AI provider (no network) to check what the feature sends and how it handles answers and failures.
A check passes when the problem does NOT happen."""
import json, os, tempfile
os.environ.update({"LLM_MOCK": "0", "OPENROUTER_API_KEY": "sk-or-fake", "DATA_DIR": tempfile.mkdtemp(), "DATABASE_URL": os.getenv("TEST_DATABASE_URL", ""),
                   "ADMIN_KEY": "", "SWEEP_EVERY_SEC": "0", "MESSAGES_EVERY_SEC": "0", "PLATFORM_ADMIN_EMAILS": ""})
import logging; logging.disable(logging.CRITICAL)
from fastapi.testclient import TestClient
from backend.main import app
from backend import db, llm

RES = []
def check(name, bug_if, detail=""):
    RES.append((name, bool(bug_if))); print(("FAIL " if bug_if else "ok   ") + "no longer: " + name + (f"  [{detail}]" if detail and bug_if else ""))

CALLS, ANSWER = [], {"v": None, "err": None}
async def fake(system, user, model, temperature=0.2, max_tokens=1500, timeout=60.0, fallbacks=None, fast=False):
    CALLS.append({"user": json.loads(user), "max_tokens": max_tokens, "fast": fast})
    if ANSWER["err"]:
        raise ANSWER["err"]
    return ANSWER["v"]
llm.complete_json = fake
GOOD = {"summary": "Own our data platform.", "responsibilities": ["Build pipelines", "Model data"], "first_90_days": ["Ship one dashboard"],
        "nice_to_have_skills": ["dbt"], "day_in_life": "Pairing and building."}

c = TestClient(app)
c.post("/api/auth/signup", json={"email": "o@w.test", "password": "correct-horse-1", "name": "O", "company": "W"})
with db.session() as s:
    for u in s.query(db.User): u.email_verified_at = 1.0

# a job that isn't saved yet: nothing is created
ANSWER["v"] = GOOD
before = len(c.get("/api/jobs").json().get("items", c.get("/api/jobs").json()) if isinstance(c.get("/api/jobs").json(), dict) else c.get("/api/jobs").json())
r = c.post("/api/jobs/ai-write", json={"fields": {"title": "Data Engineer", "must_have_skills": ["SQL", "Python"]}})
check("a new job can't be written with AI", r.status_code != 200 or r.json().get("summary") != "Own our data platform.", r.text[:200])
after = c.get("/api/jobs").json(); after = len(after.get("items", after) if isinstance(after, dict) else after)
check("writing with AI creates a draft job", after != before)
check("the AI isn't told the title and skills on screen", CALLS[-1]["user"].get("title") != "Data Engineer" or "SQL" not in CALLS[-1]["user"].get("must_have_skills", []))
check("the AI gets too few tokens for reasoning models", CALLS[-1]["max_tokens"] < 2000)
check("the AI may spend its budget thinking", not CALLS[-1]["fast"])
check("no title is accepted", c.post("/api/jobs/ai-write", json={"fields": {}}).status_code != 400)

# a saved job: the unsaved title on screen wins over the saved one
jid = c.post("/api/jobs", json={"fields": {"title": "Old title"}, "status": "draft"}).json()["ref"]
c.post(f"/api/jobs/{jid}/ai-write", json={"fields": {"title": "New title on screen"}})
check("the AI writes for the saved title, not the edited one", CALLS[-1]["user"].get("title") != "New title on screen", str(CALLS[-1]["user"]))
c.post(f"/api/jobs/{jid}/ai-write")
check("an old client (no body) breaks", CALLS[-1]["user"].get("title") != "Old title")

# bad answers and provider errors give a clear message, never a silent empty draft
ANSWER["v"] = {"unrelated": "x"}
r = c.post("/api/jobs/ai-write", json={"fields": {"title": "X"}})
check("an empty AI answer looks like success", r.status_code == 200, r.text[:200])
ANSWER["v"], ANSWER["err"] = None, RuntimeError("Error code: 429 - rate limit")
r = c.post("/api/jobs/ai-write", json={"fields": {"title": "X"}})
check("a rate limit isn't explained", r.status_code != 503 or "rate" not in r.json().get("detail", "").lower(), r.text[:200])
ANSWER["err"] = RuntimeError("Error code: 401 - invalid api key")
check("a rejected key names an env var that no longer decides the provider", "LLM_API_KEY" in c.post("/api/jobs/ai-write", json={"fields": {"title": "X"}}).json().get("detail", ""))
other = TestClient(app); other.post("/api/auth/signup", json={"email": "x@y.test", "password": "correct-horse-1", "name": "X", "company": "Y"})
check("another company can write on this job", other.post(f"/api/jobs/{jid}/ai-write", json={"fields": {"title": "Z"}}).status_code not in (403, 404))

bugs = [n for n, b in RES if b]
print(f"\n{'AI WRITE CHECKS PASSED' if not bugs else 'AI WRITE CHECKS FAILED'} ({len(RES)})")
assert not bugs, bugs
