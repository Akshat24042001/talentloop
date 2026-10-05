"""Platform console:  python -m tests.test_console

Only platform admins reach /api/console; every change works and lands in the audit log; company deletion removes all
of the company's data and nothing of other companies. A check passes when the problem does NOT happen."""
import os, tempfile
os.environ.update({"ALLOW_SAMPLE_DATA": "1", "LLM_MOCK": "1", "PUBLIC_URL": "https://x.test", "VAPI_PUBLIC_KEY": "pk", "ADMIN_KEY": "",
                   "DATA_DIR": tempfile.mkdtemp(), "DATABASE_URL": os.getenv("TEST_DATABASE_URL", ""), "PLATFORM_ADMIN_EMAILS": "boss@talentloop.test",
                   "SWEEP_EVERY_SEC": "0", "MESSAGES_EVERY_SEC": "0"})
import logging; logging.disable(logging.CRITICAL)
from fastapi.testclient import TestClient
from backend.main import app
from backend import db

RES = []
def check(name, bug_if, detail=""):
    RES.append((name, bool(bug_if))); print(("FAIL " if bug_if else "ok   ") + "no longer: " + name + (f"  [{detail}]" if detail and bug_if else ""))

def signup(c, email, company):
    return c.post("/api/auth/signup", json={"email": email, "password": "correct-horse-1", "name": email.split("@")[0], "company": company})

boss, acme, beta, anon = TestClient(app), TestClient(app), TestClient(app), TestClient(app)
signup(boss, "boss@talentloop.test", "HQ"); signup(acme, "owner@acme.test", "Acme"); signup(beta, "owner@beta.test", "Beta")
acme.post("/api/demo/seed"); beta.post("/api/demo/seed")
orgs = {o["name"]: o["id"] for o in boss.get("/api/admin/orgs").json()}
A, Bq = orgs["Acme"], orgs["Beta"]
users = {u["email"]: u["id"] for u in boss.get("/api/admin/users").json()}

# --- who can reach it ---
paths = ["/api/console/settings", f"/api/console/orgs/{A}", "/api/console/candidates", "/api/console/jobs", "/api/console/interviews",
         "/api/console/activity", "/api/console/messages", "/api/console/search?q=ac", f"/api/console/users/{users['owner@acme.test']}"]
for p in paths:
    check(f"a company owner can read {p}", acme.get(p).status_code != 403)
    check(f"a signed-out visitor can read {p}", anon.get(p).status_code not in (401, 403))
check("a company owner can delete another company", acme.request("DELETE", f"/api/console/orgs/{Bq}", json={"confirm": "Beta"}).status_code != 403)
check("a company owner can change platform settings", acme.put("/api/console/settings", json={"signups_open": False}).status_code != 403)

# --- seeing across companies ---
cands = boss.get("/api/console/candidates?sample=").json()
check("the console doesn't list candidates of every company", {i["company"] for i in cands["items"]} != {"Acme", "Beta"}, str({i["company"] for i in cands["items"]}))
check("filtering by company leaks other companies", any(i["org_id"] != A for i in boss.get(f"/api/console/candidates?org={A}").json()["items"]))
check("candidates aren't paged", len(cands["items"]) > 50 or cands["total"] != 80, str(cands["total"]))
cid = boss.get(f"/api/console/candidates?org={A}").json()["items"][0]["id"]
cd = boss.get(f"/api/console/candidates/{cid}").json()
check("a candidate's full profile isn't shown", not cd.get("resume_text") or cd.get("company") != "Acme")
jid = boss.get(f"/api/console/jobs?org={A}").json()["items"][0]["id"]
jd = boss.get(f"/api/console/jobs/{jid}").json()
check("a job's description isn't shown", not jd.get("fields") or jd.get("company") != "Acme")
check("search across companies finds nothing", not boss.get("/api/console/search?q=beta").json()["orgs"])

# --- changes, each audited ---
r = boss.patch(f"/api/console/jobs/{jid}", json={"status": "paused"})
check("a platform admin can't pause a company's job", r.status_code != 200 or r.json()["status"] != "paused")
check("a bad job status is accepted", boss.patch(f"/api/console/jobs/{jid}", json={"status": "deleted"}).status_code != 400)
r = boss.patch(f"/api/console/orgs/{A}", json={"name": "Acme Inc", "industry": "Retail", "careers_enabled": False})
check("a platform admin can't edit a company", r.status_code != 200 or r.json()["name"] != "Acme Inc" or r.json()["settings"]["careers_enabled"])
check("an empty company name is accepted", boss.patch(f"/api/console/orgs/{A}", json={"name": "  "}).status_code != 400)
mem = boss.get(f"/api/console/orgs/{A}").json()["members"][0]
check("the only owner can be demoted", boss.patch(f"/api/console/memberships/{mem['id']}", json={"role": "viewer"}).status_code != 400)
check("the only owner can be removed", boss.delete(f"/api/console/memberships/{mem['id']}").status_code != 400)
r = boss.patch(f"/api/console/orgs/{A}", json={"disabled": True})
check("a disabled company can still use the app", acme.get("/api/jobs").status_code != 403)
boss.patch(f"/api/console/orgs/{A}", json={"disabled": False})
uid = users["owner@acme.test"]
boss.post(f"/api/console/users/{uid}/signout")
check("signing someone out leaves them signed in", acme.get("/api/auth/me").status_code != 401)
check("a platform admin can disable themselves", boss.patch(f"/api/console/users/{users['boss@talentloop.test']}", json={"disabled": True}).status_code != 400)
check("an env-listed admin can be stripped of admin rights here", boss.patch(f"/api/console/users/{users['boss@talentloop.test']}", json={"platform_admin": False}).status_code != 400)
r = boss.patch(f"/api/console/users/{uid}", json={"email": "owner@beta.test"})
check("an email already in use can be taken", r.status_code != 409)
boss.post(f"/api/console/users/{uid}/reset-password")
with db.session() as s:
    check("no reset code is emailed", not s.query(db.Message).filter_by(template="password_reset", to="owner@acme.test").count())
act = boss.get("/api/console/activity?action=platform_admin").json()["items"]
details = " ".join(a["detail"] for a in act)
for needle in ("paused", "Acme Inc", "signed out", "Password reset", "disabled"):
    check(f"an admin change isn't in the audit log ({needle})", needle not in details, details[:300])
check("audit entries don't name the admin", any("boss@talentloop.test" not in a["detail"] for a in act))

# --- platform settings ---
boss.put("/api/console/settings", json={"signups_open": False, "banner": "Maintenance tonight", "banner_tone": "warning"})
check("sign-up still works while paused", signup(TestClient(app), "new@gamma.test", "Gamma").status_code != 403)
check("the banner isn't shown to users", acme.get("/api/health").json().get("banner") != "Maintenance tonight")
boss.put("/api/console/settings", json={"signups_open": True, "banner": ""})
check("sign-up stays closed after reopening", signup(TestClient(app), "new@gamma.test", "Gamma").status_code != 200)

# --- delete a company: all of it, and nothing else ---
check("a wrong confirmation deletes the company", boss.request("DELETE", f"/api/console/orgs/{A}", json={"confirm": "Acme"}).status_code != 400)
before_beta = boss.get(f"/api/console/candidates?org={Bq}").json()["total"]
r = boss.request("DELETE", f"/api/console/orgs/{A}", json={"confirm": "Acme Inc"})
check("deleting a company fails", r.status_code != 200, r.text[:200])
with db.session() as s:
    left = {t.name: s.execute(t.select().where(t.c.org_id == A)).first() is not None for t in db.Base.metadata.sorted_tables if "org_id" in t.c}
check("rows of the deleted company remain", any(left.values()), str([k for k, v in left.items() if v]))
check("the deleted company still exists", s.get(db.Org, A) is not None if False else boss.get(f"/api/console/orgs/{A}").status_code != 404)
check("deleting one company touched another", boss.get(f"/api/console/candidates?org={Bq}").json()["total"] != before_beta)
check("the deletion isn't in the platform audit log", not any("deleted" in a["detail"] for a in boss.get("/api/console/activity?action=platform_admin").json()["items"]))

bugs = [n for n, b in RES if b]
print(f"\n{'CONSOLE CHECKS PASSED' if not bugs else 'CONSOLE CHECKS FAILED'} ({len(RES)})")
assert not bugs, f"{len(bugs)} check(s) failed: {bugs}"
