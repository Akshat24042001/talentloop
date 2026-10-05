"""Lost database connections (Postgres only):  TEST_DATABASE_URL=postgresql+psycopg://... python -m tests.test_pg_resilience

The app no longer pings the database on every request (a round trip each). These checks make sure that when the
database or its pooler drops every connection, pages still load instead of failing. Needs a Postgres the test user
may run pg_terminate_backend on."""
import os, sys, tempfile
url = os.getenv("TEST_DATABASE_URL", "")
if not url.startswith("postgres"):
    print("SKIPPED: set TEST_DATABASE_URL to a Postgres database"); sys.exit(0)
os.environ.update({"DATA_DIR": tempfile.mkdtemp(), "DATABASE_URL": url, "LLM_MOCK": "1", "ADMIN_KEY": "", "SWEEP_EVERY_SEC": "0", "MESSAGES_EVERY_SEC": "0"})
import logging; logging.disable(logging.CRITICAL)
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from backend.main import app
from backend import db

RES = []
def check(name, bug_if, detail=""):
    RES.append((name, bool(bug_if))); print(("FAIL " if bug_if else "ok   ") + "no longer: " + name + (f"  [{detail}]" if detail and bug_if else ""))

admin = create_engine(url.replace("postgresql://", "postgresql+psycopg://", 1) if url.startswith("postgresql://") else url, isolation_level="AUTOCOMMIT")
def drop_all():
    with admin.connect() as c:
        c.execute(text("select pg_terminate_backend(pid) from pg_stat_activity where datname = current_database() and pid <> pg_backend_pid()"))

c = TestClient(app, raise_server_exceptions=False)
c.post("/api/auth/signup", json={"email": "r@res.test", "password": "correct-horse-1", "name": "R", "company": "Res"})
check("the app doesn't work at all", c.get("/api/jobs").status_code != 200)
drop_all()
check("a page fails right after the database dropped its connections", c.get("/api/jobs").status_code != 200)
drop_all()
check("the next page fails too", c.get("/api/candidates").status_code != 200)
for rec in list(db.engine.pool._pool.queue):
    rec.info["idle_since"] -= 300          # as if the server had been quiet for 5 minutes
drop_all()
check("an idle connection the pooler closed isn't replaced", c.get("/api/auth/me").status_code != 200)
r = c.post("/api/jobs", json={"fields": {"title": "X"}})
check("a write works after reconnecting", r.status_code >= 500, r.text[:200])

bugs = [n for n, b in RES if b]
print(f"\n{'RESILIENCE CHECKS PASSED' if not bugs else 'RESILIENCE CHECKS FAILED'} ({len(RES)})")
assert not bugs, bugs
