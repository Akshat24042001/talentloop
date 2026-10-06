"""Candidate requests reach the right people:  python -m tests.test_requests_sync
Accommodations, human-interview requests (status page and interview page), "no time works" and withdrawals must be
emailed to HR and the job's team, visible to everyone working on the job, and decidable only by those who may.
A check passes when the problem does NOT happen."""
import os
import tempfile

os.environ.update({"ALLOW_SAMPLE_DATA": "1", "LLM_MOCK": "1", "PUBLIC_URL": "https://x.test", "VAPI_PUBLIC_KEY": "pk", "ADMIN_KEY": "",
                   "DATA_DIR": tempfile.mkdtemp(), "DATABASE_URL": os.getenv("TEST_DATABASE_URL", ""), "SKIP_EMAIL_VERIFICATION": "1",
                   "APP_ENV": "development", "DEV_EMAIL_TO": "dev@x.test", "SMTP_HOST": "h", "SMTP_FROM": "a@x.test",
                   "SWEEP_EVERY_SEC": "0", "MESSAGES_EVERY_SEC": "0"})
import logging  # noqa: E402
logging.disable(logging.CRITICAL)
from fastapi.testclient import TestClient  # noqa: E402

from backend import db, interviews, messages, store  # noqa: E402
from backend.main import app  # noqa: E402

messages.kick = lambda: None
RES = []


def check(name, bug_if, detail=""):
    RES.append((name, bool(bug_if)))
    print(("FAIL " if bug_if else "ok   ") + "no longer: " + name + (f"  [{detail}]" if detail and bug_if else ""))


def ok(r):
    assert r.status_code < 300, f"{r.request.url.path}: {r.status_code} {r.text[:300]}"
    return r.json()


def mails(subject_like):
    with db.session() as s:
        return sorted({m.to for m in s.query(db.Message).filter(db.Message.subject.ilike(f"%{subject_like}%"))})


own = TestClient(app)
ok(own.post("/api/auth/signup", json={"email": "o@a.test", "password": "password-123", "name": "Olga", "company": "Acme"}))
ok(own.post("/api/demo/seed"))
users = {}
for role, email in (("recruiter", "hr@a.test"), ("hiring_manager", "mgr@a.test"), ("viewer", "vw@a.test"), ("hiring_manager2", "mgr2@a.test")):
    inv = ok(own.post("/api/team/invites", json={"email": email, "role": role.rstrip("2")}))
    users[role] = TestClient(app)
    ok(users[role].post(f"/api/invites/{inv['path'].rsplit('/', 1)[1]}/accept", json={"name": role, "password": "password-123"}))
jobs = ok(own.get("/api/jobs"))
jobs = jobs["items"] if isinstance(jobs, dict) else jobs
job = jobs[0]
team = ok(own.get("/api/team"))["members"]
mid = next(m["user_id"] for m in team if m["email"] == "mgr@a.test")
ok(own.post(f"/api/jobs/{job['id']}/collaborators", json={"user_id": mid, "permission": "edit"}))
with db.session() as s:
    apps = s.query(db.Application).filter_by(job_id=job["id"]).filter(db.Application.portal_token.isnot(None)).limit(3).all()
    (t1, a1), (t2, a2), (t3, a3) = [(a.portal_token, a.id) for a in apps]
    for a in apps:                                    # sample candidates are never emailed; requests to the team still are
        pass
cand = TestClient(app)

ok(cand.post(f"/api/status/{t1}/accommodation", json={"request": "I am hard of hearing; please enable captions and allow extra time."}))
got = mails("Accommodation request")
check("an accommodation request reaches nobody", not got)
check("HR (owner and recruiter) don't hear about accommodations", not {"o@a.test", "hr@a.test"} <= set(got), str(got))
check("the job's assigned manager doesn't hear about accommodations", "mgr@a.test" not in got, str(got))
check("a manager NOT on the job is told about it", "mgr2@a.test" in got or "vw@a.test" in got, str(got))

ok(cand.post(f"/api/status/{t2}/human", json={"note": "I prefer a person"}))
got = mails("human interview")
check("a human-interview request skips HR when the job has a manager", not {"o@a.test", "hr@a.test", "mgr@a.test"} <= set(got), str(got))

for who, c in (("owner", own), ("recruiter", users["recruiter"]), ("assigned manager", users["hiring_manager"])):
    r = c.get("/api/requests")
    kinds = {x["kind"] for x in r.json()} if r.status_code == 200 else set()
    check(f"the {who} can't see the requests they were emailed about", r.status_code != 200 or not {"accommodation", "human"} <= kinds, f"{r.status_code} {kinds}")
mr = ok(users["hiring_manager"].get("/api/requests"))
check("an assigned manager is offered HR's decision buttons", any(x["can_act"] for x in mr))
check("a manager sees requests on jobs they aren't on", any(x["job_ref"] != mr[0]["job_ref"] for x in mr) or ok(users["hiring_manager2"].get("/api/requests")))
check("the owner can't act on requests", not all(x["can_act"] for x in ok(own.get("/api/requests"))))
check("the sidebar count is wrong", ok(own.get("/api/requests/count"))["open"] != 2, str(ok(own.get("/api/requests/count"))))

# approving reaches the AI interview that's already set up: more time and the request itself
with db.session() as s:
    a = s.get(db.Application, a1)
    plan = {"role": "Analyst", "candidate_name": "X", "company": "Acme", "duration_min": 20,
            "questions": [{"id": "q1", "ask": "Tell me about yourself.", "scored": True, "time_budget_sec": 200}]}
rec = interviews.create_record(org_id=a.org_id, created_by=None, job_id=job["id"], candidate_id=a.candidate_id, application_id=a1,
                               plan=plan, inputs={}, settings=interviews.settings_from({}))
r = own.post(f"/api/applications/{a1}/accommodation", json={"status": "approved", "extra_time_pct": 50})
check("approving fails", r.status_code != 200, r.text)
rec = store.load(rec["id"])
check("the AI interview doesn't get the extra time", rec["plan"]["duration_min"] != 30 or next(q for q in rec["plan"]["questions"] if q["id"] == "q1")["time_budget_sec"] != 300, str(rec["plan"]["duration_min"]))
check("the AI interviewer isn't told about the accommodation", "hard of hearing" not in (rec["plan"].get("accommodation") or ""))
check("approving twice adds the time twice", (lambda r2: r2["plan"]["duration_min"] != 30)(
    (own.post(f"/api/applications/{a1}/accommodation", json={"status": "approved", "extra_time_pct": 50}), store.load(rec["id"]))[1]))
st = [x for x in ok(own.get("/api/requests")) if x["kind"] == "accommodation"][0]
check("an approved accommodation still shows as waiting", st["status"] != "approved")

# withdrawing tells the team and shows in requests
ok(cand.post(f"/api/status/{t3}/withdraw"))
check("a withdrawal reaches nobody", not mails("withdrew"))
check("a withdrawal doesn't show in requests", not any(x["kind"] == "withdrawn" for x in ok(own.get("/api/requests"))))
check("a withdrawn candidate's open request still waits", any(x["status"] in ("open", "requested") and x["stage"] == "withdrawn" for x in ok(own.get("/api/requests"))))

# the interview page's own "I'd rather talk to a person" (standalone interview: no application)
from backend import brain  # noqa: E402
out = ok(own.post("/api/interviews", json={"plan": brain.normalize_plan(plan), "inputs": {}, "settings": {"candidate_email": "c@gmail.com"}}))
key = out["candidate_path"].split("k=")[1]
c2 = TestClient(app)
check("asking for a person works without the access code", c2.post(f"/api/interviews/{key}/request-human", json={}).status_code != 401)
ok(c2.post(f"/api/interviews/{key}/unlock", json={"code": out["access_code"]}))
ok(c2.post(f"/api/interviews/{key}/request-human", json={"note": "anxiety with AI"}))
check("the interview page doesn't remember the request", not ok(c2.get(f"/api/interviews/{key}/public")).get("human_requested"))
check("HR isn't emailed when asked from the interview page", not {"o@a.test", "hr@a.test"} <= set(mails("human interview")))
check("the request isn't in the interview's integrity log", not any(e.get("type") == "human_requested" for e in store.load(out["id"]).get("events", [])))

bad = [n for n, f in RES if f]
assert not bad, f"{len(bad)} request check(s) failed: {bad}"
print(f"REQUEST SYNC CHECKS PASSED ({len(RES)})")
