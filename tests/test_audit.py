"""Regression checks from the platform audit:  python -m tests.test_audit

Each check describes a bug that was found and fixed (closed applications acted on, interview slots kept after a
candidate left, a deleted job breaking the background worker, other companies' users as interviewers or approvers,
link types mixed up, abandoned tests never scored, permissions of viewers and reviewers). A check passes when the
bug does NOT happen. TEST_DATABASE_URL runs it on Postgres."""
import json, os, sys, tempfile, time, asyncio, traceback
os.environ.update({"ALLOW_SAMPLE_DATA": "1", "LLM_MOCK": "1", "PUBLIC_URL": "https://x.test", "VAPI_PUBLIC_KEY": "pk", "ADMIN_KEY": "", "DATA_DIR": tempfile.mkdtemp(),
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

# best-fit jobs: a candidate who fits no job is shown no job; the minimum score is a company setting
fitc = ok(hr.post("/api/candidates", json={"name": "Fit Nobody", "email": "fitn@m.test", "resume_text": "Pastry chef, croissants, 4 years"}))
d = ok(hr.get(f"/api/candidates/{fitc['id']}"))
check("a candidate with no good fit still lists every open job as best fit", bool(d["best_jobs"]), str([(b["title"], b["score"]) for b in d["best_jobs"]]))
ok(hr.patch("/api/org", json={"settings": {"best_fit_min_score": 0}}))
d = ok(hr.get(f"/api/candidates/{fitc['id']}"))
check("best-fit minimum score setting is ignored", not d["best_jobs"] or d["best_fit_min_score"] != 0, str(d.get("best_fit_min_score")))
ok(hr.patch("/api/org", json={"settings": {"best_fit_min_score": 55}}))

# URLs carry encrypted tokens only: no titles, names, running numbers or database ids
from backend import refs
jj = ok(hr.get(f"/api/jobs/{job['id']}"))
check("job links show the title or a number", "support" in jj["ref"] or jj["ref"][-1:].isdigit() and "-" in jj["ref"] or jj["ref"] == job["id"], jj["ref"])
check("the careers link of a job is readable", "support" in jj.get("careers_url", "").lower(), jj.get("careers_url"))
check("a job token does not open the job", ok(hr.get(f"/api/jobs/{jj['ref']}"))["id"] != job["id"])
check("the public job page does not open with its token", pub.get(f"/api/public/orgs/acme/jobs/{jj['ref']}").status_code != 200)
check("another company can open a job with its token", other.get(f"/api/jobs/{jj['ref']}").status_code != 404)
check("a job token works as a candidate token", hr.get(f"/api/candidates/{jj['ref']}").status_code != 404)
a = mkapp(job); item = next(x for x in ok(hr.get(f"/api/jobs/{job['id']}/pipeline"))["items"] if x["id"] == a)
check("pipeline rows have no application token", not item.get("ref") or item["ref"] == a, str(item.get("ref")))
check("an application token does not open the application", ok(hr.get(f"/api/applications/{item['ref']}"))["id"] != a)
check("candidate links show the name", "cand" in item["candidate"]["ref"].lower() or item["candidate"]["ref"] == item["candidate"]["id"], item["candidate"]["ref"])
tampered = jj["ref"][:-2] + ("aa" if not jj["ref"].endswith("aa") else "bb")
check("a tampered token opens a job", hr.get(f"/api/jobs/{tampered}").status_code != 404)

# server configuration and sample data belong to the platform admin, not company users
h = ok(hr.get("/api/health"))
check("company users see server configuration in /api/health", any(k in h for k in ("fast_model", "storage", "llm_key_set", "platform")), str(sorted(h)))
check("anonymous visitors see server configuration", any(k in ok(pub.get("/api/health")) for k in ("fast_model", "storage")))
os.environ["ALLOW_SAMPLE_DATA"] = "0"
check("a company owner can load sample data", hr.post("/api/demo/seed").status_code != 403)
os.environ["ALLOW_SAMPLE_DATA"] = "1"
me_ = ok(hr.get("/api/auth/me"))
check("the account payload doesn't say the user's role and title", not me_["memberships"][0].get("role_label"), str(me_["memberships"][0]))

# AI interview: a failing or slow live model must not make the interviewer race through the questions
from backend import brain
pl = {"questions": [{"id": "q1", "type": "resume_probe", "ask": "Tell me about the caching work.", "max_followups": 1, "time_budget_sec": 150, "good_answer_covers": []},
                    {"id": "q2", "type": "behavioral", "ask": "A conflict you handled?", "max_followups": 1, "time_budget_sec": 150, "good_answer_covers": []}]}
mk = lambda said, allowed=("next_question", "invite_continue", "clarify_repeat", "follow_up"): {"st": {"q_idx": 0, "stall": 0, "fu_used": 0}, "said": said, "allowed": list(allowed), "progress": "next_question"}
check("model failure on a short answer moves to the next question", brain._fallback(mk("I used Redis."), pl)["action"] == "next_question")
check("model failure on a cut-off answer moves on", brain._fallback(mk("We first profiled the queries and"), pl)["action"] != "invite_continue")
check("model failure when asked to repeat moves on", brain._fallback(mk("Sorry, could you repeat that?"), pl)["action"] != "clarify_repeat")
long_ = "We profiled the slow endpoints, added a Redis cache in front of the product queries with a five minute expiry, " * 3
check("model failure on a full answer never moves on", brain._fallback(mk(long_), pl)["action"] != "next_question")
check("model failure when the candidate doesn't know keeps probing", brain._fallback(mk("Sorry, I don't know this one."), pl)["action"] == "follow_up")
check("integrity warning numbering says 'second' for a third warning", "third" not in brain.integrity_message({"candidate_name": "A B", "questions": []}, "window_blur", 3, 3)[0])

# detailed match report: JSON for the page, PDF download, scoped to the company
mc = ok(hr.post("/api/candidates", json={"name": "Report Person", "email": "rp@m.test", "resume_text": "Excel reporting, customer support 3 years, Pune"}))
rep_ = hr.get(f"/api/jobs/{job['id']}/match/{mc['id']}")
check("the match report endpoint fails", rep_.status_code != 200 or not rep_.json().get("signals"), rep_.text[:200])
pdf_ = hr.get(f"/api/jobs/{job['id']}/match/{mc['id']}?format=pdf")
check("the match report PDF download fails", pdf_.status_code != 200 or not pdf_.content.startswith(b"%PDF"), str(pdf_.status_code))
check("another company can read a match report", other.get(f"/api/jobs/{job['id']}/match/{mc['id']}").status_code != 404)

# campus drive covering several roles: one link, students pick roles, one application per role
j2 = ok(hr.post("/api/jobs", json={"fields": {**F, "title": "Sales Trainee"}, "status": "open"}))
j3 = ok(hr.post("/api/jobs", json={"fields": {**F, "title": "Ops Trainee"}, "status": "open"}))
dr = ok(hr.post("/api/drives", json={"college": "COEP Pune", "job_ids": [j2["id"], j3["id"]], "settings": {"require_photo": False}}))
check("a drive can't cover several roles", len(dr.get("jobs") or []) != 2, str(dr.get("jobs")))
pg_ = ok(pub.get(f"/api/drive/{dr['code']}"))
check("the drive page doesn't list every role", [r["title"] for r in pg_.get("roles", [])] != ["Sales Trainee", "Ops Trainee"], str(pg_.get("roles")))
stu = {"name": "Kiran Patil", "email": "kiran.multi@coep.test", "phone": "9822000009", "degree": "B.E.", "graduation_year": "2026", "consent": True,
       "location": "Pune", "expected_salary": 300000, "notice_days": 0}
r_ = pub.post(f"/api/drive/{dr['code']}/register", data={"data": json.dumps(stu)})
check("a multi-role drive accepts a registration with no role picked", r_.status_code != 400, r_.text[:150])
reg_ = pub.post(f"/api/drive/{dr['code']}/register", data={"data": json.dumps({**stu, "roles": [r["key"] for r in pg_["roles"]]})})
check("registering for two roles doesn't create two applications", reg_.status_code != 200 or len(reg_.json().get("roles") or []) != 2, reg_.text[:200])
again = pub.post(f"/api/drive/{dr['code']}/register", data={"data": json.dumps({**stu, "roles": [r["key"] for r in pg_["roles"]]})})
check("registering again for the same roles is allowed", again.status_code != 409, str(again.status_code))
res_ = ok(pub.get(f"/api/results/{dr['share_code']}"))
check("drive results count a student twice", res_["summary"]["registered"] != 1 or res_["summary"].get("applications") != 2, str(res_["summary"]))
lst = ok(hr.get("/api/drives"))
check("the drives list doesn't show the role count", next(x for x in lst if x["id"] == dr["id"]).get("registered") != 1)
ok(hr.delete(f"/api/jobs/{j2['id']}"))
check("deleting one role deletes the whole multi-role drive", not any(x["id"] == dr["id"] for x in ok(hr.get("/api/drives"))))

# AI-drafted test questions: a wrong answer key is caught by an independent second pass
from backend import assessments, llm as _llm
async def _solver(*a, **k): return {"answers": [1, 0]}
_m, _c = _llm.MOCK, _llm.complete_json
_llm.MOCK, _llm.complete_json = False, _solver
_qs = [{"text": "2+2?", "options": ["3", "4", "5", "6"], "answer": [0]}, {"text": "3+3?", "options": ["6", "7", "8", "9"], "answer": [0]}]
asyncio.run(assessments.verify_answers(_qs))
_llm.MOCK, _llm.complete_json = _m, _c
check("a drafted question with a wrong answer key is saved without a warning", "check" not in _qs[0], str(_qs[0]))
check("a drafted question the second pass agrees with is flagged anyway", "check" in _qs[1], str(_qs[1]))
jq = ok(hr.post("/api/questions/draft", json={"job_id": job["id"], "count": 3}))
check("suggesting questions from a job's JD fails", len(jq.get("items") or []) != 3, str(jq)[:200])


# Live task with screen sharing: task hidden until start, server clock, autosave, screenshots, file attach, scoring, abandoned tasks
from backend import assessments as _as
lj, LR = mkjob(["application", "live_task", "human_interview"], "Python Developer")
cfg_ = {**LR["live_task"]["config"], "instructions": "Write fizzbuzz.", "minutes": 20}
fl_ = ok(hr.get(f"/api/jobs/{lj['id']}/flow"))["rounds"]
for x in fl_:
    if x["type"] == "live_task": x["config"] = cfg_
ok(hr.put(f"/api/jobs/{lj['id']}/flow", json={"rounds": fl_}))
la = mkapp(lj); move(la, LR["live_task"]["id"]); lt = tok(rnd(la, "live_task")["result"]["candidate_link"])
lp = ok(pub.get(f"/api/r/{lt}"))
check("a live task shows the task before the clock starts", lp["live"]["instructions"] != "", lp["live"]["instructions"])
check("saving a live task before it starts is accepted", ok(pub.post(f"/api/r/{lt}/live/save", json={"content": "x"}))["ok"])
st_ = ok(pub.post(f"/api/r/{lt}/live/start"))
check("the live task clock isn't the configured minutes", abs(st_["ends_at"] - st_["started_at"] - (20 * 60 + 15)) > 2, str(st_))
st2 = ok(pub.post(f"/api/r/{lt}/live/start"))
check("starting a live task again resets the clock", st2["ends_at"] != st_["ends_at"])
check("the task stays hidden after the clock starts", ok(pub.get(f"/api/r/{lt}"))["live"]["instructions"] != "Write fizzbuzz.")
ok(pub.post(f"/api/r/{lt}/live/save", json={"content": "def fb(n): pass"}))
check("autosave of a live task is lost on reload", ok(pub.get(f"/api/r/{lt}"))["live"]["draft"] != "def fb(n): pass")
jpg_ = b"\xff\xd8\xff\xe0" + b"0" * 2000
ok(pub.post(f"/api/r/{lt}/snapshot", files={"image": ("s.jpg", jpg_, "image/jpeg")}, data={"reason": "screen"}))
up_ = pub.post(f"/api/r/{lt}/upload", files={"file": ("design.fig", b"FIG", "application/octet-stream")})
check("attaching a file ends the live task early", up_.status_code != 200 or rnd(la, "live_task")["result"]["status"] != "in_progress", up_.text[:150])
ok(pub.post(f"/api/r/{lt}/live/submit", json={"content": "def fb(n): return n", "note": "done"}))
check("a live task can be submitted twice", pub.post(f"/api/r/{lt}/live/submit", json={"content": "x"}).status_code != 409)
asyncio.run(worker.tick())
lr_ = rnd(la, "live_task")["result"]
ld_ = detail(la)["rounds"]; ldd = next(x for x in ld_ if x["round"]["type"] == "live_task")["data"]
check("a submitted live task isn't scored against the rubric", lr_["score"] is None or not (ldd.get("assessment") or {}).get("criteria"), str(ldd.get("assessment"))[:200])
check("the live task review ignores the screenshots", (ldd.get("assessment") or {}).get("screens") != 1, str(ldd.get("assessment"))[:200])
lb = mkapp(lj); move(lb, LR["live_task"]["id"]); lt2 = tok(rnd(lb, "live_task")["result"]["candidate_link"])
ok(pub.post(f"/api/r/{lt2}/live/start")); ok(pub.post(f"/api/r/{lt2}/live/save", json={"content": "partial work"}))
with db.session() as s_:
    rr_ = s_.get(db.RoundResult, rnd(lb, "live_task")["result"]["id"]); rr_.data = {**rr_.data, "live_ends_at": time.time() - 300}
worker.time_rules()
lb_ = rnd(lb, "live_task")["result"]
check("a live task abandoned after time ran out is never submitted", lb_["status"] != "submitted", lb_["status"])
check("an abandoned live task loses the autosaved work", next(x for x in detail(lb)["rounds"] if x["round"]["type"] == "live_task")["data"].get("live_content") != "partial work")


# Cross-candidate integrity scan: copied live-task work, shared wrong test answers, one phone on two records
CODE = """def top_customers(orders, k=3):
    totals = {}
    for order in orders:
        cid = order["customer_id"]
        totals[cid] = totals.get(cid, 0) + order["amount"] * order.get("qty", 1)
    ranked = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    return [cid for cid, _ in ranked[:k]] if ranked else []
"""
OTHER = """from collections import Counter
def best(orders, n=3):
    spend = Counter()
    for o in orders:
        spend[o['customer_id']] += o['amount']
    return [c for c, _ in spend.most_common(n)]
"""
sim_apps = []
for body in (CODE, CODE.replace("ranked", "ordered"), OTHER):
    x = mkapp(lj); move(x, LR["live_task"]["id"]); t_ = tok(rnd(x, "live_task")["result"]["candidate_link"])
    ok(pub.post(f"/api/r/{t_}/live/start")); ok(pub.post(f"/api/r/{t_}/live/submit", json={"content": body})); sim_apps.append(x)
sc_ = ok(hr.get(f"/api/jobs/{lj['id']}/integrity-scan"))
lp_ = [p for p in sc_["pairs"] if p["kind"] == "live_task"]
check("copied live-task work between two candidates isn't found", not any({p["a"]["application_id"], p["b"]["application_id"]} == {sim_apps[0], sim_apps[1]} for p in lp_), str(lp_)[:300])
check("different solutions to the same task are reported as copied", any(sim_apps[2] in (p["a"]["application_id"], p["b"]["application_id"]) for p in lp_), str(lp_)[:300])
check("one phone number on two candidate records isn't reported", not any(p["kind"] == "contact" for p in sc_["pairs"]))
check("another company can scan this job", other.get(f"/api/jobs/{lj['id']}/integrity-scan").status_code != 404)
from backend import similarity as _sim
from types import SimpleNamespace as _NS
with db.session() as s_:
    qs_ = [q for q in s_.query(db.Question).filter(db.Question.kind == "single").limit(6)]
    wrong_ = {q.id: [next(i for i in range(len(q.options)) if i not in (q.answer or []))] for q in qs_}
    right_ = {q.id: list(q.answer) for q in qs_}
    t_pairs = _sim._test_pairs(s_, [_NS(application_id="A", data={"answers": wrong_}), _NS(application_id="B", data={"answers": dict(wrong_)}),
                                    _NS(application_id="C", data={"answers": right_})], "Test")
check("two candidates with the same wrong options aren't flagged", not any({p["a"], p["b"]} == {"A", "B"} for p in t_pairs), str(t_pairs))
check("a candidate with all answers right is flagged as copying", any("C" in (p["a"], p["b"]) for p in t_pairs), str(t_pairs))

# AI vs your team: agreement counts people's decisions only
cal_apps = [mkapp(lj) for _ in range(6)]
for x in cal_apps:
    move(x, LR["live_task"]["id"])
plan_ = [(80, "pass", "Olga"), (85, "pass", "Olga"), (30, "fail", "Olga"), (75, "fail", "Olga"), (40, "pass", "Olga"), (90, "pass", "Automatic")]
with db.session() as s_:
    for x, (sc, dec, by) in zip(cal_apps, plan_):
        rr_ = s_.query(db.RoundResult).filter(db.RoundResult.application_id == x, db.RoundResult.round_id == LR["live_task"]["id"]).one()
        rr_.score, rr_.decision, rr_.decided_by, rr_.status = sc, dec, by, {"pass": "passed", "fail": "failed"}[dec]
cr_ = next(r for r in ok(hr.get(f"/api/jobs/{lj['id']}/calibration"))["rounds"] if r["type"] == "live_task")
check("automatic decisions count as the team agreeing with the AI", cr_["decided"] != 5, str(cr_)[:300])
check("AI vs team agreement is miscounted", cr_["agree"] != 3 or cr_["compared"] != 5 or cr_["agreement"] != 60, str(cr_)[:300])
check("the biggest disagreements aren't listed first", [d["score"] for d in cr_["disagreements"]][:1] != [75], str(cr_["disagreements"]))

bugs = [n for n, b, _ in RES if b]
assert not bugs, f"{len(bugs)} audit check(s) failed: {bugs}"
print(f"\nAUDIT CHECKS PASSED ({len(RES)})")
