"""Regression checks from the platform audit:  python -m tests.test_audit

Each check describes a bug that was found and fixed (closed applications acted on, interview slots kept after a
candidate left, a deleted job breaking the background worker, other companies' users as interviewers or approvers,
link types mixed up, abandoned tests never scored, permissions of viewers and reviewers). A check passes when the
bug does NOT happen. TEST_DATABASE_URL runs it on Postgres."""
import json, os, sys, tempfile, time, asyncio, traceback
os.environ.update({"LLM_MOCK": "1", "PUBLIC_URL": "https://x.test", "VAPI_PUBLIC_KEY": "pk", "ADMIN_KEY": "", "DATA_DIR": tempfile.mkdtemp(),
                   "DATABASE_URL": os.getenv("TEST_DATABASE_URL", ""), "FINISH_DELAY_SEC": "0", "PLATFORM_ADMIN_EMAILS": "", "APP_URL": "https://hire.test", "SWEEP_EVERY_SEC": "0"})
import logging; logging.disable(logging.CRITICAL)
from fastapi.testclient import TestClient
from backend.main import app
from backend import db, worker, flows

def C(): return TestClient(app, raise_server_exceptions=False)
def ok(r, code=200):
    assert r.status_code == code, f"{r.request.method} {r.request.url.path}: {r.status_code} {r.text[:300]}"
    return r.json()
def tok(link): return link.rstrip("/").rsplit("/", 1)[1]
RES = []
def check(name, bug_if, detail=""):
    RES.append((name, bool(bug_if), detail)); print(("FAIL " if bug_if else "ok   ") + "no longer: " + name + (f"  [{detail}]" if detail and bug_if else ""))

hr = C(); ok(hr.post("/api/auth/signup", json={"email": "o@a.test", "password": "password-123", "name": "Olga", "company": "Acme"}))
other = C(); ok(other.post("/api/auth/signup", json={"email": "x@b.test", "password": "password-123", "name": "Xan", "company": "Beta"}))
xme = ok(other.get("/api/auth/me"))
ok(hr.post("/api/questions/sample"))
F = {"title": "Support Exec", "department": "Sales", "employment_type": "Full-time", "workplace_type": "On-site", "locations": ["Pune"], "experience_min": 0, "must_have_skills": ["Excel"]}

def mkjob(types, title="Support Exec"):
    j = ok(hr.post("/api/jobs", json={"fields": {**F, "title": title}, "status": "open"}))
    ok(hr.put(f"/api/jobs/{j['id']}/flow", json={"rounds": [{"type": t, "advance": "hr"} for t in types]}))
    return j, {r["type"]: r for r in ok(hr.get(f"/api/jobs/{j['id']}/flow"))["rounds"]}
k = [0]
def mkapp(j):
    k[0] += 1
    c = ok(hr.post("/api/candidates", json={"name": f"Cand {k[0]}", "email": f"c{k[0]}@m.test", "phone": "9876500000", "resume_text": "Excel 2 years"}))
    ok(hr.post(f"/api/jobs/{j['id']}/applications", json={"candidate_id": c["id"]}))
    return next(a for a in ok(hr.get(f"/api/jobs/{j['id']}/pipeline"))["items"] if a["candidate"]["id"] == c["id"])["id"]
def detail(aid): return ok(hr.get(f"/api/applications/{aid}"))
def rnd(aid, t): return next(x for x in detail(aid)["rounds"] if x["round"]["type"] == t)
def move(aid, rid): ok(hr.post(f"/api/applications/{aid}/decide", json={"action": "move", "round_id": rid}))
def add_slot(j, R, days=2, hours=0):
    s0 = time.time() + days * 86400 + hours * 3600
    ok(hr.post(f"/api/jobs/{j['id']}/rounds/{R['human_interview']['id']}/slots", json={"slots": [{"starts_at": s0, "ends_at": s0 + 3600}], "meeting_url": "https://meet.test/x"}))
    return [s for s in ok(hr.get(f"/api/jobs/{j['id']}/rounds/{R['human_interview']['id']}/slots")) if not s["booked"]][-1]
pub = C()

job, R = mkjob(["application", "video_intro", "practical_task", "human_interview", "manager_approval"])

# B2: a rejected candidate can still act on their round links
a = mkapp(job); move(a, R["video_intro"]["id"]); vt = tok(rnd(a, "video_intro")["result"]["candidate_link"])
ok(hr.post(f"/api/applications/{a}/decide", json={"action": "reject", "reason": "x", "notify": False}))
r = pub.post(f"/api/r/{vt}/recording", files={"video": ("v.webm", b"\x1aE" + b"0" * 4000, "video/webm")}, data={"meta": "{}"})
check("rejected candidate can upload a recording", r.status_code == 200, f"{r.status_code}; stage after: {detail(a)['stage']}/{detail(a)['round_status']}")
a = mkapp(job); move(a, R["human_interview"]["id"]); ht = tok(rnd(a, "human_interview")["result"]["candidate_link"]); sl = add_slot(job, R)
ok(hr.post(f"/api/applications/{a}/decide", json={"action": "reject", "reason": "x", "notify": False}))
r = pub.post(f"/api/r/{ht}/book", json={"slot_id": sl["id"]})
check("rejected candidate can book an interview slot", r.status_code == 200, str(r.status_code))
page = ok(pub.get(f"/api/r/{vt}"))
check("round page of a rejected candidate isn't marked closed", not page.get("closed"), json.dumps({k_: page.get(k_) for k_ in ("status", "finished", "current")}))

# B3: decisions on closed applications
a = mkapp(job); ok(hr.post(f"/api/applications/{a}/decide", json={"action": "reject", "reason": "x", "notify": False}))
ok(hr.post("/api/applications/bulk", json={"ids": [a], "action": "pass"}))
check("bulk 'pass' re-opens a rejected candidate", detail(a)["stage"] != "rejected", detail(a)["stage"])
a = mkapp(job); ok(hr.post(f"/api/applications/{a}/decide", json={"action": "select"}))
n0 = len(ok(hr.get("/api/messages"))["items"])
ok(hr.post("/api/applications/bulk", json={"ids": [a], "action": "reject"}))
msgs = [m for m in ok(hr.get("/api/messages"))["items"] if m["template"] == "closure"]
check("bulk 'reject' on a selected candidate sends a closure message", detail(a)["stage"] == "rejected", f"stage {detail(a)['stage']}")
a = mkapp(job); ok(hr.post(f"/api/applications/{a}/decide", json={"action": "reject", "reason": "x", "notify": False}))
ok(hr.post("/api/applications/bulk", json={"ids": [a], "action": "select"}))
check("bulk 'select' turns a rejected candidate into an offer", detail(a)["stage"] == "offer", detail(a)["stage"])

# B4: interviewer feedback after HR rejected the candidate
a = mkapp(job); move(a, R["human_interview"]["id"]); ht = tok(rnd(a, "human_interview")["result"]["candidate_link"]); sl = add_slot(job, R, 3)
ok(pub.post(f"/api/r/{ht}/book", json={"slot_id": sl["id"]}))
fb = tok(rnd(a, "human_interview")["result"]["manager_link"])
ok(hr.post(f"/api/applications/{a}/decide", json={"action": "reject", "reason": "x", "notify": False}))
slot_after = next(s for s in ok(hr.get(f"/api/jobs/{job['id']}/rounds/{R['human_interview']['id']}/slots")) if s["id"] == sl["id"])
check("slot stays booked after the candidate is rejected", slot_after["booked"])
r = pub.post(f"/api/feedback/{fb}", data={"data": json.dumps({"decision": "pass", "name": "Ira", "notes": "good"})})
check("interviewer 'Select' after rejection re-opens the candidate", detail(a)["stage"] != "rejected", f"{r.status_code} stage {detail(a)['stage']}")

# B5: reminders to rejected candidates with a booking
a = mkapp(job); move(a, R["human_interview"]["id"]); ht = tok(rnd(a, "human_interview")["result"]["candidate_link"]); sl = add_slot(job, R, 0, 5)
ok(pub.post(f"/api/r/{ht}/book", json={"slot_id": sl["id"]}))
ok(hr.post(f"/api/applications/{a}/decide", json={"action": "reject", "reason": "x", "notify": False}))
def reminders():
    with db.session() as s_:
        return s_.query(db.Message).filter(db.Message.template == "interview_reminder").count()
before = reminders()
worker.time_rules()
after = reminders()
check("interview reminder sent to a rejected candidate", after > before, f"{before}->{after}")

# B8: removing an application leaves its slot booked
a = mkapp(job); move(a, R["human_interview"]["id"]); ht = tok(rnd(a, "human_interview")["result"]["candidate_link"]); sl = add_slot(job, R, 4)
ok(pub.post(f"/api/r/{ht}/book", json={"slot_id": sl["id"]}))
ok(hr.delete(f"/api/applications/{a}"))
slot_after = next(s for s in ok(hr.get(f"/api/jobs/{job['id']}/rounds/{R['human_interview']['id']}/slots")) if s["id"] == sl["id"])
check("slot stays booked after the application is removed", slot_after["booked"])

# B6b: moving a booked candidate to another round
a = mkapp(job); move(a, R["human_interview"]["id"]); ht = tok(rnd(a, "human_interview")["result"]["candidate_link"]); sl = add_slot(job, R, 6)
ok(pub.post(f"/api/r/{ht}/book", json={"slot_id": sl["id"]}))
move(a, R["manager_approval"]["id"])
slot_after = next(s for s in ok(hr.get(f"/api/jobs/{job['id']}/rounds/{R['human_interview']['id']}/slots")) if s["id"] == sl["id"])
check("slot stays booked after the candidate moved past the interview", slot_after["booked"])

# B1: deleting a job with a booked interview breaks the background worker
job2, R2 = mkjob(["application", "human_interview"], "Temp Job")
a = mkapp(job2); ht = tok(rnd(a, "human_interview")["result"]["candidate_link"]); sl = add_slot(job2, R2, 0, 5)
ok(pub.post(f"/api/r/{ht}/book", json={"slot_id": sl["id"]}))
d2 = ok(hr.post(f"/api/jobs/{job2['id']}/drives", json={"college": "X College"}))
ok(hr.delete(f"/api/jobs/{job2['id']}"))
try:
    worker.time_rules(); err = None
except Exception as e:
    err = f"{type(e).__name__}: {e}"
check("deleting a job breaks the deadline/reminder worker", err is not None, err or "")
with db.session() as s:
    left = {m.__name__: s.query(m).filter(m.job_id == job2["id"]).count() for m in (db.RoundResult, db.Slot, db.Drive)}
check("deleting a job leaves round results, slots and drives behind", any(left.values()), str(left))
r = pub.get(f"/api/drive/{d2['code']}")
check("a deleted job's drive link errors", r.status_code >= 500, str(r.status_code))
# clean the orphans so later checks run
with db.session() as s:
    for m in (db.RoundResult, db.Slot, db.Drive):
        s.query(m).filter(m.job_id == job2["id"]).delete()

# B7: slots and approvers can point at another company's user
r = hr.post(f"/api/jobs/{job['id']}/rounds/{R['human_interview']['id']}/slots", json={"slots": [{"starts_at": time.time() + 20 * 86400}], "interviewer_id": xme["user"]["id"]})
check("slot interviewer can be a user from another company", r.status_code == 200 and r.json()["created"] == 1)
flow = ok(hr.get(f"/api/jobs/{job['id']}/flow"))["rounds"]
for x in flow:
    if x["type"] == "manager_approval":
        x["config"]["approvers"] = [xme["user"]["id"]]
ok(hr.put(f"/api/jobs/{job['id']}/flow", json={"rounds": flow}))
a = mkapp(job); move(a, R["manager_approval"]["id"])
check("manager approval request goes to another company's user", xme["user"]["email"] in rnd(a, "manager_approval")["data"].get("approvers", []),
      str(rnd(a, "manager_approval")["data"].get("approvers")))
for x in flow:
    if x["type"] == "manager_approval":
        x["config"]["approvers"] = []
ok(hr.put(f"/api/jobs/{job['id']}/flow", json={"rounds": flow}))

# B9: token type confusion between decision and feedback links
a = mkapp(job); move(a, R["manager_approval"]["id"]); mt = tok(rnd(a, "manager_approval")["result"]["manager_link"])
r = pub.post(f"/api/feedback/{mt}", data={"data": json.dumps({"decision": "pass", "name": "x"})})
check("a manager's decision link accepts interviewer feedback", r.status_code == 200, str(r.status_code))

# B10: accommodation re-request wipes an approved accommodation
a = mkapp(job); st = tok(detail(a)["status_link"])
ok(pub.post(f"/api/status/{st}/accommodation", json={"request": "Extra time please"}))
ok(hr.post(f"/api/applications/{a}/accommodation", json={"status": "approved", "extra_time_pct": 50}))
r = pub.post(f"/api/status/{st}/accommodation", json={"request": "Another thing"})
check("a new request resets an approved accommodation", detail(a)["accommodation"].get("status") != "approved", str(detail(a)["accommodation"].get("status")))

# B12: a test abandoned mid-way is finished and scored by the server
jt, RT = mkjob(["application", "test"], "Test Job")
flow = ok(hr.get(f"/api/jobs/{jt['id']}/flow"))["rounds"]
for x in flow:
    if x["type"] == "test":
        x["config"]["sections"] = [{"section": "quantitative", "count": 3, "minutes": 1, "cutoff": 0}]
ok(hr.put(f"/api/jobs/{jt['id']}/flow", json={"rounds": flow}))
a = mkapp(jt); tt = tok(rnd(a, "test")["result"]["candidate_link"])
ok(pub.post(f"/api/r/{tt}/test/start", data={"consent": "1"}))
with db.session() as s_:
    rr = s_.get(db.RoundResult, rnd(a, "test")["result"]["id"])
    d = dict(rr.data); d["section_started"] = {"0": time.time() - 600}; d["last_seen"] = time.time() - 600; rr.data = d
worker.time_rules()
check("an abandoned test stays in progress forever", rnd(a, "test")["result"]["status"] == "in_progress", rnd(a, "test")["result"]["status"])
# permissions: viewers are read-only; reviewers rate and comment but don't decide
for role, email in (("viewer", "vw@a.test"), ("hiring_manager", "hv@a.test")):
    inv = ok(hr.post("/api/team/invites", json={"email": email, "role": role}))
    globals()[role] = C()
    ok(globals()[role].post(f"/api/invites/{inv['path'].rsplit('/', 1)[1]}/accept", json={"name": role, "password": "password-123"}))
hv_id = next(m["user_id"] for m in ok(hr.get("/api/team"))["members"] if m["email"] == "hv@a.test")
ok(hr.post(f"/api/jobs/{job['id']}/collaborators", json={"user_id": hv_id, "permission": "reviewer"}))
a = mkapp(job); move(a, R["human_interview"]["id"]); rid = rnd(a, "human_interview")["result"]["id"]
check("a viewer can record interview feedback (a hiring decision)", viewer.post(f"/api/round-results/{rid}/feedback", json={"decision": "pass"}).status_code != 403)
check("a reviewer can record interview feedback (a hiring decision)", hiring_manager.post(f"/api/round-results/{rid}/feedback", json={"decision": "pass"}).status_code != 403)
check("a viewer can write notes", viewer.patch(f"/api/applications/{a}", json={"notes": "x"}).status_code != 403)
check("a reviewer can't rate", hiring_manager.patch(f"/api/applications/{a}", json={"rating": 4}).status_code != 200)
qs = ok(viewer.get("/api/questions"))["items"]
check("answer keys are visible to non-HR roles", any("answer" in q for q in qs))

bugs = [n for n, b, _ in RES if b]
assert not bugs, f"{len(bugs)} audit check(s) failed: {bugs}"
print(f"\nAUDIT CHECKS PASSED ({len(RES)})")
