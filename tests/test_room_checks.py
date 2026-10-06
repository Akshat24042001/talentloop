"""Someone else in the room, phones, earphones:  python -m tests.test_room_checks

Server side of the room scan, ear check and AI photo checks, with a fake vision model (no network).
A check passes when the problem does NOT happen."""
import base64, io, os, tempfile
os.environ.update({"LLM_MOCK": "0", "OPENROUTER_API_KEY": "sk-or-fake", "VISION_MODEL": "fake/vision", "DATA_DIR": tempfile.mkdtemp(),
                   "DATABASE_URL": os.getenv("TEST_DATABASE_URL", ""), "ADMIN_KEY": "k" * 32, "SWEEP_EVERY_SEC": "0", "MESSAGES_EVERY_SEC": "0"})
import logging; logging.disable(logging.CRITICAL)
from PIL import Image
from fastapi.testclient import TestClient
from backend.main import app
from backend import llm, proctor, store
import backend.main as M

RES = []
def check(name, bug_if, detail=""):
    RES.append((name, bool(bug_if))); print(("FAIL " if bug_if else "ok   ") + "no longer: " + name + (f"  [{detail}]" if detail and bug_if else ""))

ANS = {"v": {"people": 1, "earphones": "no", "phone": False, "second_screen": False, "note": ""}}
SEEN = []
async def fake_vision(system, text, images, model=None, max_tokens=1500, timeout=120.0):
    SEEN.append(len(images)); return ANS["v"]
llm.complete_json_vision = fake_vision
llm.VISION_MODEL = "fake/vision"

def jpeg() -> str:
    b = io.BytesIO(); Image.new("RGB", (64, 48), (90, 90, 90)).save(b, "JPEG"); return base64.b64encode(b.getvalue()).decode()

c = TestClient(app, headers={"X-Admin-Key": "k" * 32})
plan = {"role": "Engineer", "candidate_name": "Asha", "company": "Acme", "duration_min": 10,
        "questions": [{"id": "q1", "ask": "Tell me about yourself.", "scored": True}]}
def new(**settings):
    from backend import brain
    r = c.post("/api/interviews", json={"plan": brain.normalize_plan(plan), "inputs": {}, "settings": settings})
    assert r.status_code == 200, r.text
    return r.json()["id"]
def live(iid):                          # as if the call were running
    rec = store.load(iid); rec["status"] = "in_progress"; rec["state"] = rec.get("state") or {}; rec["state"]["log"] = [{"role": "ai", "text": "Hi", "ts": 1, "q_id": "q1"}]
    rec["state"]["display"] = {"kind": "question", "text": "Tell me about yourself.", "q_id": "q1"}; store.save(rec)

iid = new()
info = c.get(f"/api/interviews/{iid}/public").json()
for k in ("room_scan", "ear_check", "vision_check_sec", "vision_available"):
    check(f"the interview page isn't told {k}", k not in info, str(sorted(info))[:300])
check("room scan and ear check are off by default", not (info.get("room_scan") and info.get("ear_check")))

# AI photo check: input validation, findings recorded on the server
check("a non-JPEG is accepted", c.post(f"/api/interviews/{iid}/vision-check", json={"reason": "room", "images": [base64.b64encode(b"nope").decode()]}).status_code != 400)
check("an unknown reason is accepted", c.post(f"/api/interviews/{iid}/vision-check", json={"reason": "x", "images": [jpeg()]}).status_code != 400)
ANS["v"] = {"people": 2, "earphones": "no", "phone": False, "second_screen": False, "note": "a man behind the sofa"}
r = c.post(f"/api/interviews/{iid}/vision-check", json={"reason": "room", "images": [jpeg(), jpeg(), jpeg()]}).json()
check("the room photos aren't checked by AI", not r.get("checked") or r.get("people") != 2 or SEEN[-1] != 3, str(r))
ev = store.load(iid).get("events", [])
check("another person found by AI isn't recorded on the server", not any(e["type"] == "vision_flag" and "other people" in e["detail"] for e in ev), str(ev[-2:]))
check("the room photos aren't kept for HR", sum(1 for i in store.load(iid)["images"] if i["reason"] == "vision_room") != 3)
ANS["v"] = {"people": 1, "earphones": "yes", "phone": False, "second_screen": False, "note": "white earbud in left ear"}
r = c.post(f"/api/interviews/{iid}/vision-check", json={"reason": "ears", "images": [jpeg(), jpeg()]}).json()
check("earbuds aren't reported to the page", r.get("earphones") != "yes")
check("earbuds aren't recorded on the server", not any(e["type"] == "vision_flag" and "earphones" in e["detail"] for e in store.load(iid)["events"]))
check("periodic checks can be spammed", c.post(f"/api/interviews/{iid}/vision-check", json={"reason": "periodic", "images": [jpeg()]}).json().get("checked") and
      c.post(f"/api/interviews/{iid}/vision-check", json={"reason": "periodic", "images": [jpeg()]}).json().get("checked"))
llm.VISION_MODEL = ""
r = c.post(f"/api/interviews/{iid}/vision-check", json={"reason": "ears", "images": [jpeg()]}).json()
check("without a vision model the page is told it was checked", r.get("checked") is not False)
llm.VISION_MODEL = "fake/vision"

# violations: someone else / a phone / earphones are real warnings (strict_room on by default), soft when switched off
iid2 = new(max_warnings=2); live(iid2)
r = c.post(f"/api/interviews/{iid2}/violation", json={"type": "multiple_people", "detail": "2 people"}).json()
check("someone else in the room is only a reminder", r.get("action") not in ("warn", "terminate"), str(r))
import time as _t; _t.sleep(4.2)
r = c.post(f"/api/interviews/{iid2}/violation", json={"type": "phone_visible", "detail": "phone"}).json()
check("a phone in view is only a reminder", r.get("action") not in ("warn", "terminate"), str(r))
check("a warning doesn't name the phone", "phone" not in r.get("say", "").lower(), r.get("say", ""))
_t.sleep(4.2)
r = c.post(f"/api/interviews/{iid2}/violation", json={"type": "earphones", "detail": "earbuds"}).json()
check("earphones after the last warning don't stop the interview", r.get("action") != "terminate", str(r))
iid3 = new(strict_room=False); live(iid3)
r3 = c.post(f"/api/interviews/{iid3}/violation", json={"type": "multiple_people"}).json()
check("strict_room off still counts someone else as a warning", r3.get("action") != "remind", str(r3))
iid4 = new(face_detection=False); live(iid4)
check("camera warnings run with camera checks switched off", c.post(f"/api/interviews/{iid4}/violation", json={"type": "phone_visible"}).json().get("action") != "ignored")
iid5 = new(enforce_focus=False); live(iid5)
check("switching off focus rules also switches off the room rules", c.post(f"/api/interviews/{iid5}/violation", json={"type": "multiple_people"}).json().get("action") == "ignored")

# the report: another person makes the interview high risk on its own
rec = store.load(iid); rec["events"].append({"type": "extra_person", "ts": None, "server_ts": 10, "detail": "2 people", "source": "client"})
sm = proctor.summary(rec)
check("another person in the room isn't high risk", sm["risk"] != "high", str(sm["reasons"]))
check("the report doesn't say why", not any("Another person" in x for x in sm["reasons"]))

bugs = [n for n, b in RES if b]
print(f"\n{'ROOM CHECKS PASSED' if not bugs else 'ROOM CHECKS FAILED'} ({len(RES)})")
assert not bugs, bugs
