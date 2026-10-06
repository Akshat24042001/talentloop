"""Candidate interview links: no ids, an access code, and the candidate picking their own time.
python -m tests.test_interview_access    (a check passes when the problem does NOT happen)"""
import os
import re
import tempfile
import time

os.environ.update({"LLM_MOCK": "1", "DATA_DIR": tempfile.mkdtemp(), "DATABASE_URL": os.getenv("TEST_DATABASE_URL", ""), "ADMIN_KEY": "",
                   "SKIP_EMAIL_VERIFICATION": "1", "APP_ENV": "development", "DEV_EMAIL_TO": "dev@inbox.test", "SMTP_HOST": "smtp.x.test",
                   "SMTP_FROM": "T <t@x.test>", "PUBLIC_URL": "https://x.test", "VAPI_PUBLIC_KEY": "pk", "SWEEP_EVERY_SEC": "0", "MESSAGES_EVERY_SEC": "0"})
import logging  # noqa: E402
logging.disable(logging.CRITICAL)
from fastapi.testclient import TestClient  # noqa: E402

from backend import brain, db, messages, store  # noqa: E402
from backend.main import app  # noqa: E402

messages.kick = lambda: None          # keep emails in the outbox so the test can read them
RES = []


def check(name, bug_if, detail=""):
    RES.append((name, bool(bug_if)))
    print(("FAIL " if bug_if else "ok   ") + "no longer: " + name + (f"  [{detail}]" if detail and bug_if else ""))


hr = TestClient(app)
assert hr.post("/api/auth/signup", json={"email": "hr@acme.test", "password": "password-123", "name": "Hana", "company": "Acme"}).status_code == 200
plan = brain.normalize_plan({"role": "Backend Engineer", "candidate_name": "Asha Rao", "company": "Acme", "duration_min": 15,
                             "questions": [{"id": "q1", "ask": "Tell me about yourself.", "scored": True}]})


def new(opening="pick", email="asha@gmail.com", **extra):
    r = hr.post("/api/interviews", json={"plan": plan, "inputs": {}, "expires_hours": 72,
                                         "settings": {"candidate_email": email, "opening": opening, **extra}})
    assert r.status_code == 200, r.text
    return r.json()


def mails(to="asha@gmail.com"):
    with db.session() as s:
        return [(m.subject, m.body) for m in s.query(db.Message).filter_by(to=to).order_by(db.Message.created_at)]


out = new()
iid, path, code = out["id"], out["candidate_path"], out["access_code"]
key = path.split("k=")[1]
check("the candidate link carries the interview id", iid in path or "id=" in path, path)
check("the access code isn't 6 digits", not re.fullmatch(r"\d{6}", code or ""), code)
check("HR is not told the invitation went out", not out.get("invited"))
m = mails()
check("the candidate gets no invitation plus a separate code email", len(m) != 2, str([x[0] for x in m]))
inv, cod = (m + [("", ""), ("", "")])[:2]
check("the invitation has no link with the key", key not in inv[1])
check("the invitation contains the access code", code in inv[1] or code in inv[0])
check("the code email is missing the code", code not in cod[1])
check("the code email also carries the link", key in cod[1] or "interview.html" in cod[1])
check("the invitation leaks the interview id", iid in inv[1] + cod[1])

cand = TestClient(app)                  # the candidate's browser: no HR session
pub = cand.get(f"/api/interviews/{key}/public").json()
check("before the code, the page learns the candidate's name or the role", not pub.get("locked") or "candidate_name" in pub or "role" in pub, str(pub))
check("a raw interview id opens the interview for a stranger", cand.get(f"/api/interviews/{iid}/public").status_code != 404)
check("a raw interview id lets a stranger post events", cand.post(f"/api/interviews/{iid}/events", json={"events": []}).status_code != 404)
check("the key without the code lets calls through", cand.post(f"/api/interviews/{key}/events", json={"events": []}).status_code != 401)
check("the key without the code starts the AI", cand.post(f"/api/interviews/{key}/assistant", json={}).status_code != 401)
bad = key[:-2] + ("aa" if key[-2:] != "aa" else "bb")
check("a tampered key opens an interview", cand.get(f"/api/interviews/{bad}/public").status_code != 404)

# wrong codes lock the link; HR sees the attempts
o2 = new(email="x@gmail.com")
k2 = o2["candidate_path"].split("k=")[1]
wrong = "000000" if o2["access_code"] != "000000" else "111111"
codes = [cand.post(f"/api/interviews/{k2}/unlock", json={"code": wrong}).status_code for _ in range(6)]
check("wrong codes are not refused, then locked", codes[:5] != [403] * 5 or codes[5] != 429, str(codes))
check("the right code works during a lockout", cand.post(f"/api/interviews/{k2}/unlock", json={"code": o2["access_code"]}).status_code != 429)
hrv = hr.get(f"/api/interviews/{o2['ref']}").json()
check("HR doesn't see the wrong tries", (hrv.get("access") or {}).get("wrong_tries", 0) < 5 or not any(e.get("type") == "access_code_wrong" for e in hrv.get("events", [])))

# the right code
r = cand.post(f"/api/interviews/{key}/unlock", json={"code": code})
check("the right code is refused", r.status_code != 200, r.text)
check("the pass cookie is readable by scripts or not scoped to this interview",
      "httponly" not in r.headers.get("set-cookie", "").lower() or f"path=/api/interviews/{key}" not in r.headers.get("set-cookie", "").lower(), r.headers.get("set-cookie"))
pub = cand.get(f"/api/interviews/{key}/public").json()
check("after the code the page is still locked", pub.get("locked") or pub.get("role") != "Backend Engineer", str(pub)[:200])
check("the page doesn't ask for a time first", not pub.get("needs_booking"))
check("the AI starts before a time is booked", cand.post(f"/api/interviews/{key}/assistant", json={}).status_code != 425)
check("another browser with only the link gets in", TestClient(app).post(f"/api/interviews/{key}/events", json={"events": []}).status_code != 401)

# picking a time
v = cand.get(f"/api/interviews/{key}/slots").json()
check("no times are offered", len(v.get("slots", [])) < 5, str(v)[:200])
check("a time outside the list can be booked", cand.post(f"/api/interviews/{key}/book", json={"starts_at": time.time() + 600}).status_code != 409)
t0 = v["slots"][3]
b = cand.post(f"/api/interviews/{key}/book", json={"starts_at": t0})
check("booking a listed time fails", b.status_code != 200, b.text)
pub = cand.get(f"/api/interviews/{key}/public").json()
check("the page doesn't show the booking", not pub.get("booking") or pub["booking"]["starts_at"] != t0 or pub.get("needs_booking"))
check("the interview is open long before the booked time", not pub.get("not_open_yet"))
check("the AI starts before the booked time", cand.post(f"/api/interviews/{key}/assistant", json={}).status_code != 425)
conf = mails()[-1]
check("no confirmation with a calendar invite", "booked" not in conf[0].lower() or "BEGIN:VCALENDAR" not in conf[1])
check("the confirmation leaks the code or the id", code in conf[1] or iid in conf[1])
b2 = cand.post(f"/api/interviews/{key}/book", json={"starts_at": v["slots"][6]}).json()
check("moving the time doesn't count a change", b2.get("changes_left") != 2, str(b2)[:200])
rec = store.load(iid)
check("the open time doesn't follow the moved booking", abs(rec["settings"]["available_from"] - (v["slots"][6] - 600)) > 1)

# HR: preview with the raw id, see the code, issue a new one
check("HR can't preview with the raw id", hr.get(f"/api/interviews/{iid}/public").status_code != 200)
hv = hr.get(f"/api/interviews/{out['ref']}").json()
check("HR can't see the code and the key link", (hv.get("access") or {}).get("code") != code or key not in (hv.get("candidate_link") or ""))
check("exports carry the access code", "access" in hr.get(f"/api/interviews/{out['ref']}/export.json").text and code in hr.get(f"/api/interviews/{out['ref']}/export.json").text)
nc = hr.post(f"/api/interviews/{out['ref']}/access-code", json={"email": True}).json()
check("a new code is the same as the old one", nc.get("code") == code)
check("the old code's browser still works after a new code", cand.post(f"/api/interviews/{key}/events", json={"events": []}).status_code != 401)
check("the old code still unlocks", cand.post(f"/api/interviews/{key}/unlock", json={"code": code}).status_code == 200)
check("the new code doesn't unlock", cand.post(f"/api/interviews/{key}/unlock", json={"code": nc["code"]}).status_code != 200)
check("the new code isn't emailed", nc["code"] not in mails()[-1][1])

# the candidate can have the same code emailed again, but not endlessly
stranger = TestClient(app)
rs = [stranger.post(f"/api/interviews/{key}/resend-code").status_code for _ in range(4)]
check("resending the code is not limited", rs != [200, 200, 200, 429], str(rs))
with db.session() as s_:
    sent_to = {mm.to for mm in s_.query(db.Message).filter_by(template="interview_access_code") if nc["code"] in mm.body}
check("a resent code goes somewhere other than the candidate", sent_to != {"asha@gmail.com"}, str(sent_to))

# "now" and "fixed" openings, and old interviews made before access codes
o3 = new(opening="now", email="n@gmail.com")
check("an interview that opens now asks for a time", TestClient(app).get(f"/api/interviews/{o3['candidate_path'].split('k=')[1]}/public").json().get("needs_booking"))
check("the 'open now' invitation asks to pick a time", "pick a time" in mails("n@gmail.com")[0][1].lower())
o4 = new(opening="now", email="", send_invite=False)
check("an interview without an email sends something", len(mails("")) > 0)
rec = store.load(o4["id"])
rec.pop("access")
store.save(rec)
from backend.main import _CandidateGate  # noqa: E402
_CandidateGate.forget(o4["id"])
check("links made before access codes stop working", TestClient(app).get(f"/api/interviews/{o4['id']}/public").status_code != 200)

# the company decides when candidates can book
from backend import tzfmt  # noqa: E402
r = hr.patch("/api/org", json={"settings": {"booking_hours": {"from": 15, "to": 12}}})
check("booking hours that end before they start are accepted", r.status_code != 400, r.text[:120])
r = hr.patch("/api/org", json={"settings": {"booking_hours": {"from": 10, "to": 13, "weekdays_only": False}}})
check("the company's booking hours aren't saved", r.status_code != 200, r.text[:120])
o5 = hr.post("/api/interviews", json={"plan": plan, "inputs": {}, "expires_hours": 300, "settings": {"candidate_email": "h@gmail.com", "opening": "pick"}}).json()
k5 = o5["candidate_path"].split("k=")[1]
c5 = TestClient(app)
c5.post(f"/api/interviews/{k5}/unlock", json={"code": o5["access_code"]})
sl = c5.get(f"/api/interviews/{k5}/slots").json()["slots"]
with db.session() as s_:
    tz_ = tzfmt.org_tz(s_.query(db.Org).first())
hrs_ = [tzfmt.local(t, tz_) for t in sl]
check("the candidate is offered times outside the company's hours", any(not (10 <= h.hour + h.minute / 60 and h.hour + h.minute / 60 + 0.25 <= 13) for h in hrs_), str([h.strftime('%H:%M') for h in hrs_[:6]]))
check("no times are offered inside the company's hours", len(sl) == 0)
check("weekends are skipped although the company allows them", not any(h.weekday() >= 5 for h in hrs_))
hr.patch("/api/org", json={"settings": {"booking_hours": {"from": 9, "to": 20, "weekdays_only": True}}})
sl2 = c5.get(f"/api/interviews/{k5}/slots").json()["slots"]
check("weekends are offered although the company says weekdays only", any(tzfmt.local(t, tz_).weekday() >= 5 for t in sl2))

bad = [n for n, f in RES if f]
assert not bad, f"{len(bad)} access check(s) failed: {bad}"
print(f"INTERVIEW ACCESS CHECKS PASSED ({len(RES)})")
