"""Interview scheduling checks:  python -m tests.test_scheduling

Human interviews (book, reschedule, cancel, limits and cut-off, HR booking for the candidate, freed slots, interviewer
clashes, "none of these times work", new-times emails), AI interview times run by the platform (open times, capacity,
book, move, cancel, reminders, missed times), company time zone in every email, calendar invites that update instead
of duplicating, the status page, and candidate sign-in at /me. A check passes when the problem does NOT happen.
TEST_DATABASE_URL runs it on Postgres."""
import os, re, sys, tempfile, time, asyncio
os.environ.update({"ALLOW_SAMPLE_DATA": "1", "LLM_MOCK": "1", "PUBLIC_URL": "https://x.test", "VAPI_PUBLIC_KEY": "pk", "ADMIN_KEY": "", "DATA_DIR": tempfile.mkdtemp(),
                   "DATABASE_URL": os.getenv("TEST_DATABASE_URL", ""), "FINISH_DELAY_SEC": "0", "PLATFORM_ADMIN_EMAILS": "", "APP_URL": "https://hire.test", "SWEEP_EVERY_SEC": "0"})
import logging; logging.disable(logging.CRITICAL)
from fastapi.testclient import TestClient
from backend.main import app
from backend import db, worker, scheduling, tzfmt

def C(): return TestClient(app, raise_server_exceptions=False)
def ok(r, code=200):
    assert r.status_code == code, f"{r.request.method} {r.request.url.path}: {r.status_code} {r.text[:300]}"
    return r.json()
def tok(link): return link.rstrip("/").rsplit("/", 1)[1]
RES = []
def check(name, bug_if, detail=""):
    RES.append((name, bool(bug_if), detail)); print(("FAIL " if bug_if else "ok   ") + "no longer: " + name + (f"  [{detail}]" if detail and bug_if else ""))
def mails(template=None, to=None):
    with db.session() as s:
        q = s.query(db.Message).filter(db.Message.channel == "email")
        if template: q = q.filter(db.Message.template == template)
        if to: q = q.filter(db.Message.to == to)
        return [(m.to, m.subject, m.body) for m in q.order_by(db.Message.created_at)]

hr = C(); ok(hr.post("/api/auth/signup", json={"email": "o@a.test", "password": "password-123", "name": "Olga Rao", "company": "Acme"}))
me = ok(hr.get("/api/auth/me"))
other = C(); ok(other.post("/api/auth/signup", json={"email": "x@b.test", "password": "password-123", "name": "Xan", "company": "Beta"}))
pub = C()
F = {"title": "Support Lead", "department": "Ops", "employment_type": "Full-time", "workplace_type": "On-site", "locations": ["Pune"], "experience_min": 0}

def mkjob(types, title="Support Lead"):
    j = ok(hr.post("/api/jobs", json={"fields": {**F, "title": title}, "status": "draft"}))
    ok(hr.put(f"/api/jobs/{j['id']}/flow", json={"rounds": [{"type": t, "advance": "hr"} for t in types]}))
    return j, {r["type"]: r for r in ok(hr.get(f"/api/jobs/{j['id']}/flow"))["rounds"]}
k = [0]
def mkapp(j, email=None):
    k[0] += 1
    c = ok(hr.post("/api/candidates", json={"name": f"Cand {k[0]}", "email": email or f"c{k[0]}@m.test", "phone": f"98765{k[0]:05d}", "resume_text": "Support 2 years"}))
    ok(hr.post(f"/api/jobs/{j['id']}/applications", json={"candidate_id": c["id"]}))
    return next(a for a in ok(hr.get(f"/api/jobs/{j['id']}/pipeline"))["items"] if a["candidate"]["id"] == c["id"])["id"]
def detail(aid): return ok(hr.get(f"/api/applications/{aid}"))
def rnd(aid, t): return next(x for x in detail(aid)["rounds"] if x["round"]["type"] == t)
def move(aid, rid): ok(hr.post(f"/api/applications/{aid}/decide", json={"action": "move", "round_id": rid}))
def day_at(days, hh, mm=0):
    """A UTC timestamp `days` from now at hh:mm UTC."""
    t = time.gmtime(time.time() + days * 86400)
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, hh, mm, 0, 0, 0, 0)) - time.timezone

job, R = mkjob(["application", "human_interview", "ai_interview"])
HI = R["human_interview"]["id"]
s0 = day_at(3, 9, 30)                                    # 09:30 UTC = 03:00 PM IST
ok(hr.post(f"/api/jobs/{job['id']}/rounds/{HI}/slots", json={"slots": [{"starts_at": s0 + i * 3600, "ends_at": s0 + i * 3600 + 2700} for i in range(5)],
                                                             "meeting_url": "https://meet.test/abc"}))
slots = ok(hr.get(f"/api/jobs/{job['id']}/rounds/{HI}/slots"))
check("five slots weren't created", len(slots) != 5, str(len(slots)))

# ---- book, with company time zone in the email
a1 = mkapp(job, "ravi@m.test"); move(a1, HI)
t1 = tok(rnd(a1, "human_interview")["result"]["candidate_link"])
page = ok(pub.get(f"/api/r/{t1}"))
check("the candidate doesn't see the open slots", len(page["interview"]["slots"]) != 5, str(len(page["interview"]["slots"])))
ok(pub.post(f"/api/r/{t1}/book", json={"slot_id": slots[0]["id"]}))
m = mails("interview_booked", "ravi@m.test")
check("no confirmation email after booking", not m)
body = m[-1][2] if m else ""
check("the confirmation shows server (UTC) time instead of the company's time zone", "03:00 PM IST" not in body, body[:400])
check("the confirmation has no join link", f"/r/{t1}/join" not in body)
check("the confirmation has no change/cancel link", "change or cancel" not in body.lower() or f"/r/{t1}" not in body)
check("the confirmation has a doubled colon", "::" in body)
check("the confirmation has no status page link", "/status/" not in body)
check("the confirmation has no calendar invite", "BEGIN:VCALENDAR" not in body)
check("the confirmation doesn't name the interviewer", "Olga Rao" not in body)
check("the interviewer isn't told about the booking", not mails("interviewer_booked", "o@a.test"))
st = ok(pub.get(f"/api/status/{tok(detail(a1)['status_link'])}"))
cur = next(x for x in st["steps"] if x["current"])
check("the status page doesn't show the booked time", not cur.get("booking") or cur["booking"]["starts_at"] != slots[0]["starts_at"], str(cur))

# ---- reschedule frees the old slot; calendar updates the same event
ok(pub.post(f"/api/r/{t1}/book", json={"slot_id": slots[1]["id"]}))
sl_ = {x["id"]: x for x in ok(hr.get(f"/api/jobs/{job['id']}/rounds/{HI}/slots"))}
check("the old slot isn't freed after a reschedule", sl_[slots[0]["id"]]["booked"])
check("the new slot isn't booked", not sl_[slots[1]["id"]]["booked"])
body2 = mails("interview_booked", "ravi@m.test")[-1][2]
check("the reschedule email doesn't show the old time", "Was: " not in body2, body2[:300])
uids = re.findall(r"UID:(\S+)", body + body2); seqs = re.findall(r"SEQUENCE:(\d+)", body + body2)
check("a reschedule adds a second calendar event instead of updating it", len(set(uids)) != 1 or seqs != ["0", "1"], f"{uids} {seqs}")
other_c = mkapp(job); move(other_c, HI); t_o = tok(rnd(other_c, "human_interview")["result"]["candidate_link"])
check("a freed slot isn't offered to other candidates", slots[0]["id"] not in [x["id"] for x in ok(pub.get(f"/api/r/{t_o}"))["interview"]["slots"]])
check("someone else's booked slot is offered", slots[1]["id"] in [x["id"] for x in ok(pub.get(f"/api/r/{t_o}"))["interview"]["slots"]])

# ---- limits: 3 changes by default, then refused; HR can still move it
ok(pub.post(f"/api/r/{t1}/book", json={"slot_id": slots[2]["id"]}))
ok(pub.post(f"/api/r/{t1}/book", json={"slot_id": slots[3]["id"]}))
r_ = pub.post(f"/api/r/{t1}/book", json={"slot_id": slots[4]["id"]})
check("a fourth change by the candidate is accepted", r_.status_code == 200, r_.text[:150])
check("the page still offers a change after the limit", ok(pub.get(f"/api/r/{t1}"))["interview"]["can_change"])
rrid = rnd(a1, "human_interview")["result"]["id"]
ot = ok(hr.get(f"/api/round-results/{rrid}/open-times"))
check("HR can't see open slots for the candidate", ot["kind"] != "slots" or not ot["slots"])
ok(hr.post(f"/api/round-results/{rrid}/book", json={"slot_id": slots[4]["id"]}))
d_ = rnd(a1, "human_interview")
check("an HR booking isn't recorded as by HR", (d_["data"]["booking"] or {}).get("by") != "Olga Rao", str(d_["data"]["booking"]))
check("an HR booking counts against the candidate's changes", d_["data"].get("reschedules") != 3)
check("the candidate isn't emailed about HR's change", "by the hiring team" not in mails("interview_booked", "ravi@m.test")[-1][2])
check("another company can book for this candidate", other.post(f"/api/round-results/{rrid}/book", json={"slot_id": slots[0]["id"]}).status_code != 404)

# ---- cut-off: within 2 hours the candidate can't change, HR can cancel
soon = time.time() + 5400
ok(hr.post(f"/api/jobs/{job['id']}/rounds/{HI}/slots", json={"slots": [{"starts_at": soon, "ends_at": soon + 2700}]}))
soon_id = next(x["id"] for x in ok(hr.get(f"/api/jobs/{job['id']}/rounds/{HI}/slots")) if abs(x["starts_at"] - soon) < 1)
a2 = mkapp(job, "meera@m.test"); move(a2, HI); t2 = tok(rnd(a2, "human_interview")["result"]["candidate_link"])
rr2 = rnd(a2, "human_interview")["result"]["id"]
ok(hr.post(f"/api/round-results/{rr2}/book", json={"slot_id": soon_id}))
check("the candidate can cancel 90 minutes before", pub.post(f"/api/r/{t2}/cancel", json={}).status_code == 200)
check("the page offers a change inside the cut-off", ok(pub.get(f"/api/r/{t2}"))["interview"]["can_change"])
ok(hr.post(f"/api/round-results/{rr2}/cancel-booking", json={"reason": "Interviewer unwell"}))
p2 = ok(pub.get(f"/api/r/{t2}"))
check("after HR cancels, the candidate's page still shows a booking", p2["interview"]["booking"] is not None)
check("the candidate isn't told why HR cancelled", "Interviewer unwell" not in (p2["interview"]["cancelled"] or {}).get("cancel_reason", ""))
cm = mails("interview_cancelled", "meera@m.test")
check("no cancellation email", not cm)
check("the cancellation doesn't remove the calendar event", not cm or "METHOD:CANCEL" not in cm[-1][2])
check("the slot isn't freed after HR cancels", next(x for x in ok(hr.get(f"/api/jobs/{job['id']}/rounds/{HI}/slots")) if x["id"] == soon_id)["booked"])

# ---- candidate cancels, says no time works, gets emailed when new times open
a3 = mkapp(job, "arun@m.test"); move(a3, HI); t3 = tok(rnd(a3, "human_interview")["result"]["candidate_link"])
free = [x for x in ok(pub.get(f"/api/r/{t3}"))["interview"]["slots"] if x["starts_at"] > time.time() + 6 * 3600]
ok(pub.post(f"/api/r/{t3}/book", json={"slot_id": free[0]["id"]}))
ok(pub.post(f"/api/r/{t3}/cancel", json={"reason": "Exam that day"}))
p3 = ok(pub.get(f"/api/r/{t3}"))
check("a cancelled booking still shows as booked", p3["interview"]["booking"] is not None or rnd(a3, "human_interview")["result"]["status"] != "invited")
check("the interviewer isn't told about the cancellation", not any("Cancelled" in x[1] for x in mails("interviewer_booked", "o@a.test")))
check("a too-short time suggestion is accepted", pub.post(f"/api/r/{t3}/request-times", json={"note": "x"}).status_code == 200)
ok(pub.post(f"/api/r/{t3}/request-times", json={"note": "Weekdays after 6 pm"}))
check("HR isn't told the candidate needs other times", not mails("time_request"))
check("HR can't see the candidate's suggested times", (rnd(a3, "human_interview")["data"].get("time_request") or {}).get("note") != "Weekdays after 6 pm")
n_before = len(mails("interview_times", "arun@m.test"))
s9 = day_at(5, 12, 30)
told = ok(hr.post(f"/api/jobs/{job['id']}/rounds/{HI}/slots", json={"slots": [{"starts_at": s9, "ends_at": s9 + 2700}]}))
check("waiting candidates aren't emailed when new times open", len(mails("interview_times", "arun@m.test")) != n_before + 1, str(told))
told2 = ok(hr.post(f"/api/jobs/{job['id']}/rounds/{HI}/slots", json={"slots": [{"starts_at": s9 + 7200, "ends_at": s9 + 9900}]}))
check("waiting candidates are emailed again on the same day", len(mails("interview_times", "arun@m.test")) != n_before + 1)

# ---- interviewer clashes: no overlapping slots, and a booked interviewer isn't offered twice
dup = ok(hr.post(f"/api/jobs/{job['id']}/rounds/{HI}/slots", json={"slots": [{"starts_at": s9 + 600, "ends_at": s9 + 3000}]}))
check("an overlapping slot for the same interviewer is created", dup["created"] != 0 or dup["skipped_overlaps"] != 1, str(dup))
job2, R2 = mkjob(["application", "human_interview"], "Ops Lead")
with db.session() as s:                                # an overlapping slot in another job (made before the rule existed)
    sl1 = s.query(db.Slot).filter(db.Slot.job_id == job["id"], db.Slot.booked_by.isnot(None)).first()
    s.add(db.Slot(org_id=sl1.org_id, job_id=job2["id"], round_id=R2["human_interview"]["id"], interviewer_id=sl1.interviewer_id,
                  starts_at=sl1.starts_at + 600, ends_at=sl1.ends_at + 600, meeting_url=""))
b1 = mkapp(job2); move(b1, R2["human_interview"]["id"]); tb = tok(rnd(b1, "human_interview")["result"]["candidate_link"])
check("an interviewer already booked at that time is offered again", len(ok(pub.get(f"/api/r/{tb}"))["interview"]["slots"]) != 0)

# ---- reminders in the company's time zone
with db.session() as s:
    rr_ = s.get(db.RoundResult, rrid)
    b_ = dict(rr_.data["booking"]); start = time.time() + 20 * 3600
    b_.update(starts_at=start, ends_at=start + 2700); rr_.data = {**rr_.data, "booking": b_}
worker.time_rules()
rem = [x for x in mails("interview_reminder", "ravi@m.test")]
check("no reminder a day before", not rem)
check("the reminder shows UTC time", rem and "IST" not in rem[-1][2], rem[-1][2][:200] if rem else "")

# ---- AI interview times run by the platform
ai_app = mkapp(job, "zara@m.test"); move(ai_app, R["ai_interview"]["id"])
asyncio.run(worker.tick())
ta = tok(rnd(ai_app, "ai_interview")["result"]["candidate_link"])
pa = ok(pub.get(f"/api/r/{ta}"))
sch = pa["interview"].get("schedule") or {}
check("candidates can't book an AI interview time", not sch.get("allowed") or not sch.get("slots"), str(sch)[:200])
hours = {tzfmt.local(t, "Asia/Kolkata").hour for t in sch.get("slots", [])}
check("AI times are offered at night in the company's time zone", bool(hours) and (min(hours) < 8 or max(hours) >= 22), str(sorted(hours)))
check("AI times aren't on the half hour", any(t % 1800 for t in sch.get("slots", [])))
check("a made-up AI time is accepted", pub.post(f"/api/r/{ta}/ai-book", json={"starts_at": sch["slots"][0] + 60}).status_code == 200)
first = sch["slots"][0]
ok(pub.post(f"/api/r/{ta}/ai-book", json={"starts_at": first}))
am = mails("ai_interview_scheduled", "zara@m.test")
check("no confirmation email for an AI interview time", not am)
check("the AI confirmation has no interview link", am and f"/r/{ta}" not in am[-1][2])
check("the AI confirmation has no calendar invite", am and "BEGIN:VCALENDAR" not in am[-1][2])
check("the AI confirmation isn't in the company's time zone", am and "IST" not in am[-1][2])
ai_rr = rnd(ai_app, "ai_interview")["result"]["id"]
from backend import store
with db.session() as s:
    iid = s.get(db.RoundResult, ai_rr).data["interview_id"]
check("the AI interview link expires before the booked time", float(store.load(iid)["expires_at"]) < first + 900)
# capacity: with room for 1, a second candidate isn't offered the same time
scheduling.AI_CAPACITY = 1
ai2 = mkapp(job); move(ai2, R["ai_interview"]["id"]); asyncio.run(worker.tick())
t_ai2 = tok(rnd(ai2, "ai_interview")["result"]["candidate_link"])
check("a full AI time is offered to another candidate", first in ok(pub.get(f"/api/r/{t_ai2}"))["interview"]["schedule"]["slots"])
check("the candidate's own booked time disappears from their choices", first not in ok(pub.get(f"/api/r/{ta}"))["interview"]["schedule"]["slots"])
scheduling.AI_CAPACITY = 10
# move, cancel
second = ok(pub.get(f"/api/r/{ta}"))["interview"]["schedule"]["slots"][3]
ok(pub.post(f"/api/r/{ta}/ai-book", json={"starts_at": second}))
check("a moved AI time isn't confirmed as rescheduled", "rescheduled" not in mails("ai_interview_scheduled", "zara@m.test")[-1][1].lower())
ok(pub.post(f"/api/r/{ta}/cancel", json={}))
check("a cancelled AI time still shows", ok(pub.get(f"/api/r/{ta}"))["interview"]["schedule"]["booking"] is not None)
# reminders and a missed time
ok(hr.post(f"/api/round-results/{ai_rr}/book", json={"starts_at": ok(hr.get(f"/api/round-results/{ai_rr}/open-times"))["times"][0]}))
with db.session() as s:
    rr_ = s.get(db.RoundResult, ai_rr); b_ = dict(rr_.data["ai_booking"]); b_.update(starts_at=time.time() + 1800, ends_at=time.time() + 2700)
    rr_.data = {**rr_.data, "ai_booking": b_}
worker.time_rules()
check("no reminder an hour before the AI interview", not mails("ai_interview_reminder", "zara@m.test"))
with db.session() as s:
    rr_ = s.get(db.RoundResult, ai_rr); b_ = dict(rr_.data["ai_booking"]); b_.update(starts_at=time.time() - 4 * 3600, ends_at=time.time() - 3 * 3600)
    rr_.data = {**rr_.data, "ai_booking": b_}
worker.time_rules()
pm = ok(pub.get(f"/api/r/{ta}"))["interview"]["schedule"]
check("a missed AI time isn't released", pm["booking"] is not None or not pm["missed"], str(pm)[:200])
check("the candidate isn't told they missed their time", not any("Missed" in x[1] for x in mails("ai_interview_cancelled", "zara@m.test")))

# ---- company time zone setting
check("an invalid time zone is saved", hr.patch("/api/org", json={"settings": {"timezone": "Mars/Base"}}).status_code == 200)
ok(hr.patch("/api/org", json={"settings": {"timezone": "Europe/London"}}))
ok(pub.post(f"/api/r/{t3}/book", json={"slot_id": [x for x in ok(pub.get(f"/api/r/{t3}"))["interview"]["slots"] if x["starts_at"] > time.time() + 6 * 3600][0]["id"]}))
lon = mails("interview_booked", "arun@m.test")[-1][2]
check("the company's time zone setting is ignored in emails", "IST" in lon.split("--ICS--")[0] or not re.search(r"(GMT|BST)", lon), lon[:300])
ok(hr.patch("/api/org", json={"settings": {"timezone": "Asia/Kolkata"}}))

# ---- candidate sign-in at /me
before = len(mails("candidate_login"))
ok(pub.post("/api/me/code", json={"email": "nobody@m.test"}))
check("a code is sent to an email with no applications", len(mails("candidate_login")) != before)
ok(pub.post("/api/me/code", json={"email": "ravi@m.test"}))
lm = mails("candidate_login", "ravi@m.test")
check("no sign-in code is emailed", not lm)
code = re.search(r"\b(\d{6})\b", lm[-1][2]).group(1) if lm else "000000"
check("the code is in the email subject (visible in the company outbox)", lm and code in lm[-1][1])
outbox = hr.get("/api/messages", params={"template": "candidate_login"})
check("the company can read the candidate's sign-in code", outbox.status_code == 200 and code in outbox.text)
cand = C()
check("a wrong code signs in", cand.post("/api/me/verify", json={"email": "ravi@m.test", "code": "123456" if code != "123456" else "654321"}).status_code == 200)
check("the applications page opens without signing in", cand.get("/api/me").status_code != 401)
ok(cand.post("/api/me/verify", json={"email": "ravi@m.test", "code": code}))
mine = ok(cand.get("/api/me"))
check("the signed-in candidate doesn't see their application", len(mine["applications"]) != 1, str(mine)[:200])
step = (mine["applications"] or [{}])[0].get("step") or {}
check("the applications page doesn't show the interview time", not step.get("booking"), str(step))
check("the applications page has no link to change the time", not step.get("link"))
check("a sign-in code works twice", C().post("/api/me/verify", json={"email": "ravi@m.test", "code": code}).status_code == 200)
ok(cand.post("/api/me/logout"))
check("signing out doesn't sign out", cand.get("/api/me").status_code != 401)


# ---- placement officer sign-in at /me
dj = ok(hr.post("/api/drives", json={"job_ids": [job["id"]], "college": "MIT Pune", "settings": {"placement_officer": "Dr Rao", "officer_email": "tpo@mitpune.test"}}))
ok(pub.post("/api/me/code", json={"email": "tpo@mitpune.test"}))
tm = mails("candidate_login", "tpo@mitpune.test")
check("a placement officer gets no sign-in code", not tm)
tpo = C()
if tm:
    ok(tpo.post("/api/me/verify", json={"email": "tpo@mitpune.test", "code": re.search(r"\b(\d{6})\b", tm[-1][2]).group(1)}))
mine_t = tpo.get("/api/me").json() if tm else {}
check("the placement officer doesn't see their drive", [d["college"] for d in mine_t.get("drives", [])] != ["MIT Pune"], str(mine_t)[:200])
check("the placement officer's drive has no results link", not any("/results/" in d["results_link"] for d in mine_t.get("drives", [])))

bugs = [n for n, b, _ in RES if b]
print(f"\n{'SCHEDULING CHECKS PASSED' if not bugs else 'SCHEDULING CHECKS FAILED'} ({len(RES)})")
assert not bugs, f"{len(bugs)} scheduling check(s) failed: {bugs}"
if os.getenv("SHOW_MAIL"):
    for t in ("interview_booked", "ai_interview_scheduled", "interview_cancelled"):
        print("=" * 30, t); print(mails(t)[-1][1]); print(mails(t)[-1][2].split("--ICS--")[0])
