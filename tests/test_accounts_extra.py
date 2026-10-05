"""AI model settings and forgotten passwords:  python -m tests.test_accounts_extra

Fresh SQLite database, fake LLM. A check passes when the problem does NOT happen."""
import os, re, tempfile
os.environ.update({"ALLOW_SAMPLE_DATA": "1", "LLM_MOCK": "1", "PUBLIC_URL": "https://x.test", "VAPI_PUBLIC_KEY": "pk", "ADMIN_KEY": "",
                   "DATA_DIR": tempfile.mkdtemp(), "DATABASE_URL": os.getenv("TEST_DATABASE_URL", ""), "PLATFORM_ADMIN_EMAILS": "boss@talentloop.test",
                   "SWEEP_EVERY_SEC": "0", "MESSAGES_EVERY_SEC": "0", "OPENROUTER_API_KEY": "sk-or-test", "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "",
                   "GEMINI_API_KEY": "", "XAI_API_KEY": "", "LLM_API_KEY": "", "MAIL_MODE": "off"})
import logging; logging.disable(logging.CRITICAL)
from fastapi.testclient import TestClient
from backend.main import app
from backend import db, llm

RES = []
def check(name, bug_if, detail=""):
    RES.append((name, bool(bug_if))); print(("FAIL " if bug_if else "ok   ") + "no longer: " + name + (f"  [{detail}]" if detail and bug_if else ""))

def signup(c, email, company):
    return c.post("/api/auth/signup", json={"email": email, "password": "correct-horse-1", "name": "T", "company": company})

with TestClient(app) as boss, TestClient(app) as hr, TestClient(app) as anon:
    signup(boss, "boss@talentloop.test", "Platform Co"); signup(hr, "hr@acme.test", "Acme")
    # --- AI models ---
    check("a company user can read the AI settings", hr.get("/api/platform/llm").status_code != 403)
    check("a company user can change the AI settings", hr.put("/api/platform/llm", json={}).status_code != 403)
    check("a signed-out visitor can read the AI settings", anon.get("/api/platform/llm").status_code not in (401, 403))
    st = boss.get("/api/platform/llm").json()
    prov = {p["id"]: p for p in st["providers"]}
    check("the admin can't see every provider", not {"openrouter", "openai", "anthropic", "gemini", "xai"} <= set(prov), str(list(prov)))
    check("a provider without a key shows as usable", prov["anthropic"]["available"] or prov["openai"]["available"])
    check("a provider with a key shows as not usable", not prov["openrouter"]["available"])
    good = {"fast": {"provider": "openrouter", "models": ["a/fast:free", "b/fast:free"]}, "smart": {"provider": "openrouter", "models": ["c/smart:free"]},
            "vision": {"provider": "openrouter", "models": []}}
    r = boss.put("/api/platform/llm", json={**good, "fast": {"provider": "anthropic", "models": ["claude-haiku-4-5"]}})
    check("saving a provider without a key is allowed", r.status_code != 400, r.text[:200])
    r = boss.put("/api/platform/llm", json={**good, "smart": {"provider": "openrouter", "models": []}})
    check("saving with no smart model is allowed", r.status_code != 400)
    r = boss.put("/api/platform/llm", json={**good, "smart": {"provider": "nope", "models": ["x"]}})
    check("an unknown provider is accepted", r.status_code != 400)
    r = boss.put("/api/platform/llm", json=good)
    check("a valid choice isn't saved", r.status_code != 200 or r.json()["source"] != "admin", r.text[:200])
    check("the choice doesn't apply at once", llm.FAST_MODEL != "a/fast:free" or llm.FAST_CHAIN != ["a/fast:free", "b/fast:free"] or llm.SMART_MODEL != "c/smart:free")
    check("an empty vision list doesn't switch vision off", llm.VISION_MODEL != "" or llm.VISION_CHAIN != [], str(llm.VISION_CHAIN))
    with db.session() as s:
        row = s.get(db.AppSecret, "llm_config")
        check("the choice isn't stored for the next restart", not row or "a/fast:free" not in row.value)
    llm.apply_config({}); llm.load_saved()
    check("a restart loses the saved choice", llm.FAST_MODEL != "a/fast:free" or llm.SOURCE != "admin")
    check("the test button fails in mock mode", not boss.post("/api/platform/llm/test", json={"role": "fast"}).json().get("ok"))
    check("a company user can run the test button", hr.post("/api/platform/llm/test", json={"role": "fast"}).status_code != 403)
    r = boss.delete("/api/platform/llm")
    check("reset doesn't go back to the server settings", r.json()["source"] != "environment" or llm.FAST_MODEL == "a/fast:free")
    with db.session() as s:
        check("reset leaves the saved choice behind", s.get(db.AppSecret, "llm_config") is not None)

    # --- forgotten password ---
    check("forgot tells a stranger whether an account exists",
          anon.post("/api/auth/forgot", json={"email": "nobody@acme.test"}).json() != anon.post("/api/auth/forgot", json={"email": "hr@acme.test"}).json())
    with db.session() as s:
        m = s.query(db.Message).filter_by(template="password_reset", to="hr@acme.test").order_by(db.Message.created_at.desc()).first()
        code = re.search(r"\b(\d{6})\b", m.body).group(1) if m else ""
        check("no reset email is queued for a real account", not code)
        check("a reset email is queued for an unknown address", s.query(db.Message).filter_by(template="password_reset", to="nobody@acme.test").count())
    out = hr.get("/api/messages").json()
    shown = " ".join(i.get("body", "") for i in out.get("items", []))
    check("the outbox shows the reset code to staff", code and code in shown)
    wrong = "000000" if code != "000000" else "111111"
    check("a wrong code resets the password", anon.post("/api/auth/reset", json={"email": "hr@acme.test", "code": wrong, "password": "brand-new-pass"}).status_code != 400)
    check("a short new password is accepted", anon.post("/api/auth/reset", json={"email": "hr@acme.test", "code": code, "password": "short"}).status_code != 400)
    r = anon.post("/api/auth/reset", json={"email": "hr@acme.test", "code": code, "password": "brand-new-pass"})
    check("the right code doesn't reset the password", r.status_code != 200, r.text[:200])
    check("old sign-ins survive a reset", hr.get("/api/auth/me").status_code != 401)
    check("the code works twice", anon.post("/api/auth/reset", json={"email": "hr@acme.test", "code": code, "password": "another-pass-1"}).status_code != 400)
    check("the new password doesn't work", anon.post("/api/auth/login", json={"email": "hr@acme.test", "password": "brand-new-pass"}).status_code != 200)
    check("the old password still works", anon.post("/api/auth/login", json={"email": "hr@acme.test", "password": "correct-horse-1"}).status_code == 200)

bugs = [n for n, b in RES if b]
print(f"\n{'ACCOUNT EXTRA CHECKS PASSED' if not bugs else 'ACCOUNT EXTRA CHECKS FAILED'} ({len(RES)})")
assert not bugs, f"{len(bugs)} check(s) failed: {bugs}"
