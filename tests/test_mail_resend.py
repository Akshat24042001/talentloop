"""Email through Resend's HTTPS API (Render's free tier blocks SMTP ports), development redirection to DEV_EMAIL_TO,
the provider's own error in the outbox, and the platform admin's test email. A fake Resend server stands in."""
import os
import tempfile
import threading
import time

os.environ.update({"APP_ENV": "development", "DEV_EMAIL_TO": "dev@inbox.test", "SMTP_HOST": "smtp.resend.com", "SMTP_PORT": "587",
                   "SMTP_USER": "resend", "SMTP_PASSWORD": "re_fake_key", "SMTP_FROM": "TalentLoop <onboarding@resend.dev>",
                   "RESEND_API_URL": "http://127.0.0.1:8798", "SKIP_EMAIL_VERIFICATION": "1", "LLM_MOCK": "1", "DATABASE_URL": "",
                   "DATA_DIR": tempfile.mkdtemp(), "PUBLIC_URL": "https://x.test", "VAPI_PUBLIC_KEY": "pk", "ADMIN_KEY": "",
                   "PLATFORM_ADMIN_EMAILS": "boss@a.test"})
import asyncio  # noqa: E402

import uvicorn  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import db, messages  # noqa: E402
from backend.main import app  # noqa: E402

GOT, MODE, N = [], {"refuse": False}, [0]
fake = FastAPI()


@fake.post("/emails")
async def emails(req: Request):
    assert req.headers["authorization"] == "Bearer re_fake_key"
    body = await req.json()
    if MODE["refuse"]:
        return JSONResponse({"statusCode": 403, "name": "validation_error", "message": "You can only send testing emails to your own email address (owner@x.test)."}, 403)
    GOT.append(body)
    return {"id": "e1"}


def check(name, cond, detail=""):
    N[0] += 1
    assert cond, f"{name}: {detail}"
    print("ok  ", name)


threading.Thread(target=uvicorn.run, args=(fake,), kwargs={"port": 8798, "log_level": "warning"}, daemon=True).start()
time.sleep(1.2)
check("a Resend SMTP setup is sent over the HTTPS API", messages.email_transport() == "resend-api" and messages.email_enabled())

with db.session() as s:
    messages.queue(s, "org1", to_email="real.person@gmail.com", subject="Interview", body="Hello\n\n--ICS--\nBEGIN:VCALENDAR\nEND:VCALENDAR", template="t")
asyncio.run(messages.dispatch_once())
check("development delivers only to DEV_EMAIL_TO", len(GOT) == 1 and GOT[0]["to"] == ["dev@inbox.test"], str(GOT))
check("the real recipient never gets it, and is named in the subject", "real.person@gmail.com" in GOT[0]["subject"] and "real.person@gmail.com" not in GOT[0]["to"])
check("the calendar invite travels as an attachment", GOT[0]["attachments"][0]["filename"] == "interview.ics" and "--ICS--" not in GOT[0]["text"])
with db.session() as s:
    m = s.query(db.Message).one()
    check("the outbox says where it really went", m.status == "sent" and "dev@inbox.test" in m.error, m.error)

MODE["refuse"] = True
with db.session() as s:
    messages.queue(s, "org1", to_email="a@gmail.com", subject="X", body="Y", template="t")
asyncio.run(messages.dispatch_once())
with db.session() as s:
    m = s.query(db.Message).filter_by(subject="X").one()
    check("Resend's refusal is stored word for word, with the fix", m.status == "failed" and "own email address" in m.error and "DEV_EMAIL_TO" in m.error, m.error)

with TestClient(app) as c:
    c.post("/api/auth/signup", json={"email": "boss@a.test", "password": "password-123", "name": "Boss", "company": "A"})
    r = c.post("/api/console/test-email")
    check("the admin's test email shows the provider's answer", r.status_code == 502 and "own email address" in r.json()["detail"], r.text)
    MODE["refuse"] = False
    r = c.post("/api/console/test-email")
    check("a working setup reports where the test went", r.status_code == 200 and r.json()["sent_to"] == "dev@inbox.test", r.text)
    c2 = TestClient(app)
    c2.post("/api/auth/signup", json={"email": "hr@b.test", "password": "password-123", "name": "H", "company": "B"})
    check("company users can't send test emails", c2.post("/api/console/test-email").status_code in (401, 403))
print(f"MAIL CHECKS PASSED ({N[0]})")
