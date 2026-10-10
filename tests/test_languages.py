"""Interview languages:  python -m tests.test_languages
The candidate picks the language; questions are translated from the plan HR approved; voice and speech recognition follow.
A check passes when the problem does NOT happen."""
import json, os, tempfile
os.environ.update({"LLM_MOCK": "0", "OPENROUTER_API_KEY": "sk-or-fake", "DATA_DIR": tempfile.mkdtemp(), "DATABASE_URL": os.getenv("TEST_DATABASE_URL", ""),
                   "ADMIN_KEY": "k" * 32, "SWEEP_EVERY_SEC": "0", "MESSAGES_EVERY_SEC": "0", "PUBLIC_URL": "https://example.test", "VAPI_PUBLIC_KEY": "pk"})
import logging; logging.disable(logging.CRITICAL)
from fastapi.testclient import TestClient
from backend.main import app
from backend import brain, llm, store, vapi_config

RES = []
def check(name, bug_if, detail=""):
    RES.append((name, bool(bug_if))); print(("FAIL " if bug_if else "ok   ") + "no longer: " + name + (f"  [{detail}]" if detail and bug_if else ""))

# --- every offered language has speech recognition and a voice that Vapi accepts
AZ_STT = {"bn-IN", "en-IN", "gu-IN", "hi-IN", "kn-IN", "ml-IN", "mr-IN", "pa-IN", "ta-IN", "te-IN", "ur-IN"}   # @vapi-ai/server-sdk 3.0.0
SONIOX = {"as", "bn", "gu", "hi", "kn", "ks", "ml", "mr", "ne", "or", "pa", "sa", "sd", "ta", "te", "ur"}
plan0 = brain.normalize_plan({"role": "Engineer", "candidate_name": "Asha Rao", "company": "Acme", "duration_min": 10,
                              "questions": [{"id": "q1", "type": "warmup", "ask": "Tell me about yourself.", "scored": False},
                                            {"id": "q2", "type": "hr_mandatory", "ask": "What is your notice period?", "scored": True}]})
for code, name, native in vapi_config.LANGUAGES:
    a = vapi_config.build_assistant("iid", plan0, "Hi", "tok", language=code)
    t, v = a["transcriber"], a["voice"]
    ok_stt = (t["provider"] == "deepgram" and t["language"] in ("en-IN", "hi", "multi")) or (t["provider"] == "azure" and t["language"] in AZ_STT) \
        or (t["provider"] == "soniox" and t["language"] in SONIOX)
    check(f"{name}: speech recognition is not set to a language Vapi accepts", not ok_stt, json.dumps(t))
    check(f"{name}: no voice for the language", code not in ("en", "hi-en") and not (v["provider"] == "azure" and v["voiceId"].split("-IN-")[0] in (code, "hi")), json.dumps(v))
    check(f"{name}: the language has no name for the model", code not in __import__("backend.prompts", fromlist=["x"]).LANGUAGE_NAMES)
check("Punjabi is not offered", "pa" not in vapi_config.LANGUAGE_CODES)
check("Odia is not offered", "or" not in vapi_config.LANGUAGE_CODES)
check("Assamese is not offered", "as" not in vapi_config.LANGUAGE_CODES)
check("Urdu is not offered", "ur" not in vapi_config.LANGUAGE_CODES)

# --- the candidate chooses; the questions are translated from HR's plan
CALLS, MODE = [], {"v": "ok"}
async def fake(system, user, model, **kw):
    CALLS.append(system)
    src = json.loads(user)
    if MODE["v"] == "fail":
        raise RuntimeError("model down")
    if "translate" in system.lower() and "questions" in system.lower():
        return {k: f"[ta] {v}" for k, v in src.items()} if MODE["v"] == "ok" else {list(src)[0]: "x"}
    return {k: f"[ta] {v}" for k, v in src.items()}          # fixed lines
llm.complete_json = fake; llm.FAST_MODEL = "fake/fast"

c = TestClient(app, headers={"X-Admin-Key": "k" * 32})
def new(**settings):
    r = c.post("/api/interviews", json={"plan": plan0, "inputs": {}, "settings": settings})
    assert r.status_code == 200, r.text
    return r.json()["id"]
iid = new()
pub = c.get(f"/api/interviews/{iid}/public").json()
check("the interview page is not told which languages to offer", len(pub.get("languages") or []) != len(vapi_config.LANGUAGES), str(pub.get("languages"))[:200])
check("languages are not shown in their own script", not any(l.get("native") == "தமிழ்" for l in pub.get("languages") or []))
r = c.post(f"/api/interviews/{iid}/language", json={"language": "ta"})
rec = store.load(iid)
check("choosing Tamil fails", r.status_code != 200, r.text)
check("the questions are not translated", not all(q["ask"].startswith("[ta]") for q in rec["plan"]["questions"] if not q.get("practice")), str([q["ask"] for q in rec["plan"]["questions"]]))
check("the interview language is not saved", rec["settings"]["language"] != "ta")
check("HR's original plan is lost", rec["plan_source"]["questions"][1]["ask"] != "What is your notice period?")
check("the fixed lines are not translated", not str(rec.get("lines", {}).get("opening", "")).startswith("[ta]"))
r = c.post(f"/api/interviews/{iid}/language", json={"language": "en"})
rec = store.load(iid)
q2 = next(q for q in rec["plan"]["questions"] if q["id"] == "q2")
check("going back to English keeps the translation", q2["ask"] != "What is your notice period?", q2["ask"])
check("the practice question is lost when the language changes", not rec["plan"]["questions"][0].get("practice"))
check("a language that is not offered is accepted", c.post(f"/api/interviews/{iid}/language", json={"language": "xx"}).status_code != 400)
iid2 = new(languages=["en", "hi"])
check("a language HR did not allow is accepted", c.post(f"/api/interviews/{iid2}/language", json={"language": "ta"}).status_code != 400)
check("HR's list is not what the page offers", [l["code"] for l in c.get(f"/api/interviews/{iid2}/public").json()["languages"]] != ["en", "hi"])
MODE["v"] = "fail"
iid3 = new()
r = c.post(f"/api/interviews/{iid3}/language", json={"language": "bn"})
check("a failed translation is not reported to the candidate", r.status_code != 503, r.text)
check("a failed translation changes the interview", store.load(iid3)["settings"]["language"] != "en")
MODE["v"] = "bad"
r = c.post(f"/api/interviews/{iid3}/language", json={"language": "bn"})
check("a half translation is used", r.status_code == 200 or store.load(iid3)["plan"]["questions"][0]["ask"] == "x")
MODE["v"] = "ok"
# after the candidate has spoken the language is fixed
rec = store.load(iid3); brain.start_session(rec); rec["state"]["log"].append({"role": "candidate", "text": "hello", "q_id": "q1", "t": 1, "ts": 1}); store.save(rec)
check("the language changes after the interview started", c.post(f"/api/interviews/{iid3}/language", json={"language": "gu"}).status_code != 409)
# the call uses the chosen language: Azure Tamil voice and recognition
iid4 = new()
c.post(f"/api/interviews/{iid4}/language", json={"language": "pa"})
r = c.post(f"/api/interviews/{iid4}/assistant", json={})
a = (r.json().get("assistant") or {}) if r.status_code == 200 else {}
check("the call does not speak Punjabi", a.get("voice", {}).get("voiceId") != "pa-IN-VaaniNeural", r.text[:200])
check("the call does not listen in Punjabi", a.get("transcriber", {}).get("language") != "pa-IN")
check("the opening line is not in the chosen language", not str(a.get("firstMessage", "")).startswith("[ta]"), str(a.get("firstMessage"))[:80])
# HR set Tamil as the default but the plan is English: the call must not speak English questions with a Tamil voice
iid5 = new(language="ta")
rec = store.load(iid5); rec["plan"]["language"] = "en"; rec["plan_lang"] = "en"; store.save(rec)
c.post(f"/api/interviews/{iid5}/assistant", json={})
check("English questions are read out by a Tamil voice", not store.load(iid5)["plan"]["questions"][0]["ask"].startswith("[ta]"))

bad = [n for n, b in RES if b]
print(f"\n{len(RES) - len(bad)}/{len(RES)} ok"); raise SystemExit(1 if bad else 0)
