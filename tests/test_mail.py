"""Mail safety:  python -m tests.test_mail

A fake SMTP server records every recipient, in the headers and in the SMTP envelope. Test mode must deliver only to
MAIL_TEST_TO; live mode must skip sample and dummy addresses; off mode and unknown modes must never deliver to anyone
else. WhatsApp must never go out outside live mode. A check passes when the problem does NOT happen."""
import asyncio, os, tempfile
os.environ.update({"ALLOW_SAMPLE_DATA": "1", "LLM_MOCK": "1", "PUBLIC_URL": "https://x.test", "VAPI_PUBLIC_KEY": "pk", "ADMIN_KEY": "",
                   "DATA_DIR": tempfile.mkdtemp(), "DATABASE_URL": os.getenv("TEST_DATABASE_URL", ""), "PLATFORM_ADMIN_EMAILS": "", "SWEEP_EVERY_SEC": "0",
                   "SMTP_HOST": "smtp.fake", "SMTP_PORT": "587", "SMTP_USER": "resend", "SMTP_PASSWORD": "x", "SMTP_FROM": "TalentLoop <onboarding@resend.dev>",
                   "WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_NUMBER_ID": "1", "WHATSAPP_TEMPLATE": "tpl",
                   "MAIL_MODE": "", "MAIL_TEST_TO": "me@mine.test.example"})
import logging; logging.disable(logging.CRITICAL)
import importlib
from backend import db, messages
db.migrate()

RES = []
def check(name, bug_if, detail=""):
    RES.append((name, bool(bug_if), detail)); print(("FAIL " if bug_if else "ok   ") + "no longer: " + name + (f"  [{detail}]" if detail and bug_if else ""))

SENT = []          # (header To, envelope recipients, subject, body)
class FakeSMTP:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def ehlo(self): pass
    def has_extn(self, x): return False
    def starttls(self, **k): pass
    def login(self, u, p): pass
    def send_message(self, msg, from_addr=None, to_addrs=None):
        SENT.append((msg["To"], list(to_addrs or []), msg["Subject"], msg.get_content()))
messages.smtplib.SMTP = FakeSMTP
messages.smtplib.SMTP_SSL = FakeSMTP
WA = []
async def fake_wa(m): WA.append(m.to)
messages._send_whatsapp = fake_wa

with db.session() as s:
    org = db.Org(name="Acme", slug="acme-mail"); s.add(org); s.flush()
    real = db.Candidate(org_id=org.id, name="Real Person", email="real.person@gmail.com", phone="9876543210", source="careers")
    sample = db.Candidate(org_id=org.id, name="Sample", email="sample@gmail.com", phone="9876500000", source="demo", tags=["sample"])
    s.add_all([real, sample]); s.flush()
    ORG, REAL, SAMPLE = org.id, real.id, sample.id

def send(to, cand=None, phone=""):
    with db.session() as s:
        messages.queue(s, ORG, to_email=to, to_phone=phone, subject="Interview confirmed", body="Hello", template="t", candidate_id=cand)
    asyncio.run(messages.dispatch_once(500))

def statuses():
    with db.session() as s:
        return [(m.channel, m.to, m.status, m.error) for m in s.query(db.Message).order_by(db.Message.created_at)]

# default (MAIL_MODE unset) is test mode
check("an unset MAIL_MODE isn't test mode", messages.MAIL_MODE != "test", messages.MAIL_MODE)
messages.MAIL_TEST_TO = "me@mine.test"          # dummy-looking on purpose: test mode must still deliver only here
SENT.clear(); send("real.person@gmail.com", REAL, "9876543210")
check("test mode emails the real recipient", any("real.person@gmail.com" in (h or "") or "real.person@gmail.com" in env for h, env, _, _ in SENT), str(SENT))
check("test mode doesn't deliver to the test address", [x[1] for x in SENT] != [["me@mine.test"]], str(SENT))
check("the test email doesn't say who it was for", not SENT or "real.person@gmail.com" not in SENT[0][2] or "TEST" not in SENT[0][3])
check("test mode sends WhatsApp", WA, str(WA))
check("the outbox loses the real recipient in test mode", statuses()[0][1] != "real.person@gmail.com", str(statuses()[:2]))

messages.MAIL_TEST_TO = ""
SENT.clear(); send("real.person@gmail.com", REAL)
check("test mode without a test address sends anyway", SENT, str(SENT))
check("test mode without a test address isn't reported as held", statuses()[-1][2] != "held", str(statuses()[-1]))

messages.MAIL_MODE = "off"; messages.MAIL_TEST_TO = "me@mine.test"
SENT.clear(); send("real.person@gmail.com", REAL)
check("off mode sends email", SENT, str(SENT))

messages.MAIL_MODE = "live"
SENT.clear(); WA.clear()
send("real.person@gmail.com", REAL, "9876543210")
check("live mode doesn't email the real recipient", [x[1] for x in SENT] != [["real.person@gmail.com"]], str(SENT))
check("live mode doesn't send WhatsApp", WA != ["919876543210"], str(WA))
check("a live email is marked as a test", SENT and SENT[0][2].startswith("[TEST"))
SENT.clear(); WA.clear()
send("sample@gmail.com", SAMPLE, "9876500000")
check("live mode emails a sample candidate", SENT, str(SENT))
check("live mode sends WhatsApp to a sample candidate", WA, str(WA))
for dummy in ("anyone@example.com", "x@college.test", "a@b.invalid", "z@foo.example", "staff@localhost"):
    SENT.clear(); send(dummy)
    check(f"live mode emails a dummy address ({dummy})", SENT, str(SENT))
SENT.clear(); send("manager@company.in")
check("live mode doesn't email a real staff address", [x[1] for x in SENT] != [["manager@company.in"]], str(SENT))

# a mistyped mode is treated as test
os.environ["MAIL_MODE"] = "LIVEE"; importlib.reload(messages)
check("a mistyped MAIL_MODE sends live", messages.MAIL_MODE != "test", messages.MAIL_MODE)
os.environ["MAIL_MODE"] = "Live "; importlib.reload(messages)
check("'Live ' with spaces and capitals isn't understood", messages.MAIL_MODE != "live")

bugs = [n for n, b, _ in RES if b]
print(f"\n{'MAIL CHECKS PASSED' if not bugs else 'MAIL CHECKS FAILED'} ({len(RES)})")
assert not bugs, f"{len(bugs)} mail check(s) failed: {bugs}"
