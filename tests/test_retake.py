"""A finished AI interview: no "resend" (the link leads nowhere), and an HR-only retake with a reason that keeps the
earlier attempt:  python -m tests.test_retake      (a check passes when the problem does NOT happen)"""
import os
import tempfile

os.environ.update({"ALLOW_SAMPLE_DATA": "1", "LLM_MOCK": "1", "PUBLIC_URL": "https://x.test", "VAPI_PUBLIC_KEY": "pk", "ADMIN_KEY": "",
                   "DATA_DIR": tempfile.mkdtemp(), "DATABASE_URL": os.getenv("TEST_DATABASE_URL", ""), "SKIP_EMAIL_VERIFICATION": "1",
                   "APP_ENV": "development", "SWEEP_EVERY_SEC": "0", "MESSAGES_EVERY_SEC": "0"})
import logging  # noqa: E402
logging.disable(logging.CRITICAL)
from fastapi.testclient import TestClient  # noqa: E402

from backend import db, flows  # noqa: E402
from backend.main import app  # noqa: E402

RES = []


def check(name, bug_if, detail=""):
    RES.append((name, bool(bug_if)))
    print(("FAIL " if bug_if else "ok   ") + "no longer: " + name + (f"  [{detail}]" if detail and bug_if else ""))


def ok(r):
    assert r.status_code < 300, f"{r.request.url.path}: {r.status_code} {r.text[:300]}"
    return r.json()


own = TestClient(app)
ok(own.post("/api/auth/signup", json={"email": "o@a.test", "password": "password-123", "name": "Olga", "company": "Acme"}))
ok(own.post("/api/demo/seed"))
inv = ok(own.post("/api/team/invites", json={"email": "mgr@a.test", "role": "hiring_manager"}))
mgr = TestClient(app)
ok(mgr.post(f"/api/invites/{inv['path'].rsplit('/', 1)[1]}/accept", json={"name": "M", "password": "password-123"}))
with db.session() as s:
    job = next(j for j in s.query(db.Job).all() if any(r["type"] == "ai_interview" for r in flows.flow_of(j)))
    a = s.query(db.Application).filter_by(job_id=job.id).first()
    rnd = next(r for r in flows.flow_of(job) if r["type"] == "ai_interview")
    rr = flows.move_to(s, a, job, rnd["id"], "test")
    rr.status, rr.score = "submitted", 20.0                       # the interview is done and waiting for review
    rr.data = {**(rr.data or {}), "interview_id": "oldInterview1"}
    rid, jid = rr.id, job.id
mid = next(m["user_id"] for m in ok(own.get("/api/team"))["members"] if m["email"] == "mgr@a.test")
ok(own.post(f"/api/jobs/{jid}/collaborators", json={"user_id": mid, "permission": "edit"}))

r = own.post(f"/api/round-results/{rid}/resend")
check("a finished interview can be 'resent'", r.status_code != 409, r.text)
check("the refusal doesn't point to the retake", "retake" not in r.text.lower())
check("a hiring manager can allow an AI retake", mgr.post(f"/api/round-results/{rid}/reset", json={"reason": "call dropped"}).status_code != 403)
check("a retake without a reason is accepted", own.post(f"/api/round-results/{rid}/reset", json={}).status_code != 400)
r = own.post(f"/api/round-results/{rid}/reset", json={"reason": "the call dropped twice"})
check("HR can't allow a retake", r.status_code != 200, r.text)
with db.session() as s:
    rr = s.get(db.RoundResult, rid)
    d = rr.data or {}
    check("the retake doesn't set up a new interview", rr.status != "setting_up", rr.status)
    att = d.get("attempts") or []
    check("the earlier attempt isn't kept with its reason and report", not att or att[0].get("reason") != "the call dropped twice" or not att[0].get("interview_ref") or att[0].get("score") != 20.0, str(att))
    check("the old interview stays attached as the current one", d.get("interview_id") == "oldInterview1")
check("a retake can be started again while the new one is being set up", own.post(f"/api/round-results/{rid}/reset", json={"reason": "again please"}).status_code == 200)

bad = [n for n, f in RES if f]
assert not bad, f"{len(bad)} retake check(s) failed: {bad}"
print(f"RETAKE CHECKS PASSED ({len(RES)})")
