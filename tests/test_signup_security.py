"""Sign-up confirmation and JWT:  python -m tests.test_signup_security

Email confirmation ON (as in production). A check passes when the problem does NOT happen."""
import os, re, tempfile, time
os.environ.update({"SKIP_EMAIL_VERIFICATION": "0", "ALLOW_SAMPLE_DATA": "1", "LLM_MOCK": "1", "PUBLIC_URL": "https://x.test", "VAPI_PUBLIC_KEY": "pk",
                   "ADMIN_KEY": "", "DATA_DIR": tempfile.mkdtemp(), "DATABASE_URL": os.getenv("TEST_DATABASE_URL", ""),
                   "PLATFORM_ADMIN_EMAILS": "boss@talentloop.test", "SWEEP_EVERY_SEC": "0", "MESSAGES_EVERY_SEC": "0", "DEV_EMAIL_TO": ""})
import logging; logging.disable(logging.CRITICAL)
import jwt
from fastapi.testclient import TestClient
from backend.main import app
from backend import auth, db
from backend.api_flows import _msg_json

RES = []
def check(name, bug_if, detail=""):
    RES.append((name, bool(bug_if))); print(("FAIL " if bug_if else "ok   ") + "no longer: " + name + (f"  [{detail}]" if detail and bug_if else ""))

def signup(c, email, company="Acme", pw="correct-horse-1"):
    return c.post("/api/auth/signup", json={"email": email, "password": pw, "name": "T", "company": company})

def code_for(email):
    with db.session() as s:
        m = s.query(db.Message).filter_by(template="email_verify", to=email).order_by(db.Message.created_at.desc()).first()
        return (re.search(r"\b(\d{6})\b", m.body).group(1), _msg_json(m)["body"]) if m else ("", "")

C = lambda: TestClient(app)
# --- confirmation ---
a = C(); r = signup(a, "hr@acme.test")
check("sign-up fails", r.status_code != 200, r.text[:200])
check("a new account counts as confirmed", r.json().get("email_verified") is not False)
check("an unconfirmed account can use the workspace", a.get("/api/jobs").status_code != 403)
check("an unconfirmed account can't see who it is", a.get("/api/auth/me").status_code != 200)
code, shown = code_for("hr@acme.test")
check("no confirmation email is queued", not code)
check("the outbox shows the confirmation code", code and code in shown)
wrong = "000000" if code != "000000" else "111111"
check("a wrong code confirms the email", a.post("/api/auth/verify", json={"code": wrong}).status_code != 400)
check("a stranger's session confirms someone else", C().post("/api/auth/verify", json={"code": code}).status_code != 401)
r = a.post("/api/auth/verify", json={"code": code})
check("the right code doesn't confirm", r.status_code != 200 or r.json().get("email_verified") is not True, r.text[:200])
check("a confirmed account still can't use the workspace", a.get("/api/jobs").status_code != 200)
check("a confirmed address can be signed up again", signup(C(), "hr@acme.test").status_code != 409)

# --- the platform admin address can't be taken by signing up first ---
evil = C(); signup(evil, "boss@talentloop.test", "Evil Co")
check("an unconfirmed sign-up with the admin email opens the admin console", evil.get("/api/admin/overview").status_code != 403)
check("an unconfirmed sign-up with the admin email reads analytics", evil.get("/api/admin/analytics").status_code != 403)
real = C(); r = signup(real, "boss@talentloop.test", "TalentLoop HQ")
check("the real owner can't sign up over an unconfirmed squatter", r.status_code != 200, r.text[:200])
check("the squatter's session survives", evil.get("/api/auth/me").status_code != 401)
with db.session() as s:
    check("the squatter's company is left behind", s.query(db.Org).filter_by(name="Evil Co").count())
real.post("/api/auth/verify", json={"code": code_for("boss@talentloop.test")[0]})
check("the confirmed admin can't open the console", real.get("/api/admin/overview").status_code != 200)

# --- password reset and invites confirm the inbox ---
u = C(); signup(u, "lost@acme.test", "Lost Co")
u.post("/api/auth/forgot", json={"email": "lost@acme.test"})
with db.session() as s:
    m = s.query(db.Message).filter_by(template="password_reset", to="lost@acme.test").first()
    rc = re.search(r"\b(\d{6})\b", m.body).group(1)
C().post("/api/auth/reset", json={"email": "lost@acme.test", "code": rc, "password": "brand-new-pass"})
with db.session() as s:
    check("a password reset doesn't count as confirming the email", s.query(db.User).filter_by(email="lost@acme.test").one().email_verified_at is None)
inv = a.post("/api/team/invites", json={"email": "newbie@acme.test", "role": "recruiter"})
link = (inv.json() or {}).get("path") or ""
tok = link.rstrip("/").split("/")[-1] if link else ""
if tok:
    n = C(); n.post(f"/api/invites/{tok}/accept", json={"password": "newbie-pass-1", "name": "N"})
    check("an invited person must confirm their email again", n.get("/api/jobs").status_code != 200)
else:
    check("invite link not found in response", True, inv.text[:200])

# --- JWT ---
t = C()
check("an unconfirmed account gets a token", t.post("/api/auth/token", json={"email": "lost2@acme.test", "password": "x"}).status_code == 200)
signup(C(), "unconf@acme.test", "Unconf Co")
check("an unconfirmed account gets a token", t.post("/api/auth/token", json={"email": "unconf@acme.test", "password": "correct-horse-1"}).status_code != 403)
check("a wrong password gets a token", t.post("/api/auth/token", json={"email": "hr@acme.test", "password": "nope-nope-1"}).status_code != 401)
r = t.post("/api/auth/token", data={"username": "hr@acme.test", "password": "correct-horse-1"})      # Swagger's form
check("the Swagger sign-in form doesn't work", r.status_code != 200, r.text[:200])
tk = r.json()
H = lambda x: {"Authorization": f"Bearer {x}"}
check("a token isn't a JWT", tk.get("token_type") != "bearer" or tk["access_token"].count(".") != 2)
check("a bearer token can't read the account", t.get("/api/auth/me", headers=H(tk["access_token"])).json().get("user", {}).get("email") != "hr@acme.test")
check("a bearer token can't use the workspace", t.get("/api/jobs", headers=H(tk["access_token"])).status_code != 200)
claims = jwt.decode(tk["access_token"], options={"verify_signature": False})
check("the token has no expiry", "exp" not in claims or claims["exp"] - claims["iat"] > 3600 + 5)
forged = jwt.encode({**claims, "exp": int(time.time()) + 999}, "guessed-secret", algorithm="HS256")
check("a token signed with another key works", t.get("/api/jobs", headers=H(forged)).status_code != 401)
expired = jwt.encode({**claims, "iat": int(time.time()) - 7200, "nbf": int(time.time()) - 7200, "exp": int(time.time()) - 60}, auth._jwt_key(), algorithm="HS256")
check("an expired token works", t.get("/api/jobs", headers=H(expired)).status_code != 401)
none_alg = jwt.encode({**claims}, None, algorithm="none") if hasattr(jwt, "encode") else ""
check("an unsigned (alg=none) token works", t.get("/api/jobs", headers=H(none_alg)).status_code != 401)
with db.session() as s:
    other = s.query(db.User).filter_by(email="boss@talentloop.test").one().id
swapped = jwt.encode({**claims, "sub": other}, auth._jwt_key(), algorithm="HS256")
check("changing the user in a token works", t.get("/api/admin/overview", headers=H(swapped)).status_code != 401)
check("an access token works as a refresh token", t.post("/api/auth/token/refresh", json={"refresh_token": tk["access_token"]}).status_code != 401)
r2 = t.post("/api/auth/token/refresh", json={"refresh_token": tk["refresh_token"]})
check("refreshing doesn't give a working token", r2.status_code != 200 or t.get("/api/jobs", headers=H(r2.json()["access_token"])).status_code != 200)
t.post("/api/auth/logout", headers=H(tk["access_token"]))
check("a token still works after signing out", t.get("/api/jobs", headers=H(r2.json()["access_token"])).status_code != 401)
check("a refresh token still works after signing out", t.post("/api/auth/token/refresh", json={"refresh_token": tk["refresh_token"]}).status_code != 401)
tk2 = t.post("/api/auth/token", json={"email": "hr@acme.test", "password": "correct-horse-1"}).json()
a.post("/api/auth/password", json={"current": "correct-horse-1", "new": "changed-pass-1"})
check("a token survives a password change elsewhere", t.get("/api/jobs", headers=H(tk2["access_token"])).status_code != 401)
check("the browser session that changed the password was signed out", a.get("/api/jobs").status_code != 200)

# --- Swagger ---
spec = C().get("/openapi.json").json()
sch = spec.get("components", {}).get("securitySchemes", {})
check("Swagger has no JWT sign-in", "OAuth2Password" not in sch or sch["OAuth2Password"]["flows"]["password"]["tokenUrl"] != "/api/auth/token" or "BearerJWT" not in sch)
check("Swagger doesn't mark the jobs API as needing a token", not spec["paths"]["/api/jobs"]["get"].get("security"))
check("Swagger asks for a token to get a token", spec["paths"]["/api/auth/token"]["post"].get("security") != [])

bugs = [n for n, b in RES if b]
print(f"\n{'SIGN-UP SECURITY CHECKS PASSED' if not bugs else 'SIGN-UP SECURITY CHECKS FAILED'} ({len(RES)})")
assert not bugs, f"{len(bugs)} check(s) failed: {bugs}"
