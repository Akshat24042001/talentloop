"""Production hides every development tool:  python -m tests.test_appenv

Starts the real app with APP_ENV=production (in a child process, since the switch is read at import) and checks that
the fake AI, sample data and API docs are off even when their development switches are set. A check passes when the
problem does NOT happen."""
import json, os, subprocess, sys, tempfile

CHILD = r'''
import json, os
from fastapi.testclient import TestClient
from backend.main import app
from backend import llm, messages
c = TestClient(app)
c.post("/api/auth/signup", json={"email": "boss@talentloop.test", "password": "correct-horse-1", "name": "B", "company": "P"})
from backend import db
with db.session() as s:                      # production always asks for email confirmation; confirm directly here
    for u in s.query(db.User): u.email_verified_at = 1.0
h = c.get("/api/health").json()
print(json.dumps({"mock": llm.MOCK, "docs": c.get("/docs").status_code, "openapi": c.get("/openapi.json").status_code,
                  "seed": c.post("/api/demo/seed").status_code, "env": h.get("env"), "production": h.get("production"),
                  "dev_to": messages.status()["dev_email_to"], "msg_prod": messages.PRODUCTION, "me_verified": c.get("/api/auth/me").json().get("email_verified")}))
'''
RES = []
def check(name, bug_if, detail=""):
    RES.append((name, bool(bug_if))); print(("FAIL " if bug_if else "ok   ") + "no longer: " + name + (f"  [{detail}]" if detail and bug_if else ""))

def run(env_name):
    env = {**os.environ, "APP_ENV": env_name, "LLM_MOCK": "1", "ALLOW_SAMPLE_DATA": "1", "DATA_DIR": tempfile.mkdtemp(),
           "DATABASE_URL": os.getenv("TEST_DATABASE_URL", ""), "PLATFORM_ADMIN_EMAILS": "boss@talentloop.test", "DEV_EMAIL_TO": "me@x.test",
           "ADMIN_KEY": "", "SWEEP_EVERY_SEC": "0", "MESSAGES_EVERY_SEC": "0", "VAPI_PUBLIC_KEY": "pk", "PUBLIC_URL": "https://x.test"}
    out = subprocess.run([sys.executable, "-c", CHILD], env=env, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])

p = run("production")
check("production runs the fake AI when LLM_MOCK=1", p["mock"])
check("production serves the API docs", p["docs"] == 200 or p["openapi"] == 200, str(p))
check("production loads sample data", p["seed"] != 403, str(p["seed"]))
check("production isn't reported as production", p["env"] != "production" or p["production"] is not True)
check("production still diverts email to the dev inbox", not p["msg_prod"] or p["dev_to"])
check("the production check ran as an unconfirmed account", p["me_verified"] is not True)
d = run("development")
check("development has no fake AI", not d["mock"])
check("development has no API docs", d["docs"] != 200 or d["openapi"] != 200)
check("development refuses sample data for the platform admin", d["seed"] not in (200, 409), str(d["seed"]))
check("development is reported as production", d["production"] is not False)

bugs = [n for n, b in RES if b]
print(f"\n{'APP_ENV CHECKS PASSED' if not bugs else 'APP_ENV CHECKS FAILED'} ({len(RES)})")
assert not bugs, f"{len(bugs)} check(s) failed: {bugs}"
