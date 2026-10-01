"""Candidate and manager messages: email (SMTP) and WhatsApp (Meta WhatsApp Cloud API), with an outbox.

Every message is stored in the `messages` table first (HR can read it on the candidate's profile), then sent in
the background. Without a configured channel the message stays in the outbox as "not_configured" with its link,
so HR can copy it and send it by hand; nothing is lost.

Email: SMTP_HOST, SMTP_PORT (587 = STARTTLS, 465 = SSL), SMTP_USER, SMTP_PASSWORD, SMTP_FROM ("RAC Careers <careers@rac.com>").
WhatsApp: WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_TEMPLATE (an approved template whose body has one variable,
{{1}}, that receives the message text), WHATSAPP_TEMPLATE_LANG (default en), WHATSAPP_API_VERSION (default v21.0).
Meta only allows business-initiated WhatsApp messages through approved templates, hence the single-variable template.
"""
import asyncio
import email.utils
import logging
import os
import re
import smtplib
import ssl
import time
from email.message import EmailMessage

import httpx

from . import db

log = logging.getLogger("messages")

SMTP = {k: (os.getenv(f"SMTP_{k}") or "").strip() for k in ("HOST", "PORT", "USER", "PASSWORD", "FROM")}
WA = {"token": (os.getenv("WHATSAPP_TOKEN") or "").strip(), "phone_id": (os.getenv("WHATSAPP_PHONE_NUMBER_ID") or "").strip(),
      "template": (os.getenv("WHATSAPP_TEMPLATE") or "").strip(), "lang": (os.getenv("WHATSAPP_TEMPLATE_LANG") or "en").strip(),
      "version": (os.getenv("WHATSAPP_API_VERSION") or "v21.0").strip()}


def email_enabled() -> bool:
    return bool(SMTP["HOST"] and SMTP["FROM"])


def whatsapp_enabled() -> bool:
    return bool(WA["token"] and WA["phone_id"] and WA["template"])


def status() -> dict:
    return {"email": email_enabled(), "whatsapp": whatsapp_enabled()}


def norm_phone(phone: str, default_cc: str = "91") -> str:
    """E.164 digits without '+' for WhatsApp: '098765 43210' -> '919876543210'."""
    d = re.sub(r"\D", "", phone or "")
    if d.startswith("00"):
        d = d[2:]
    if len(d) == 11 and d.startswith("0"):
        d = d[1:]
    if len(d) == 10:
        d = default_cc + d
    return d if 10 <= len(d) <= 15 else ""


def queue(s, org_id: str, *, to_email: str = "", to_phone: str = "", subject: str, body: str, template: str,
          candidate_id: str | None = None, application_id: str | None = None, whatsapp_text: str = "") -> list[db.Message]:
    """Store the message for each available channel. The dispatcher sends it after the request finishes."""
    rows = []
    if to_email:
        rows.append(db.Message(org_id=org_id, candidate_id=candidate_id, application_id=application_id, channel="email",
                               to=to_email[:320], subject=subject[:300], body=body, template=template,
                               status="queued" if email_enabled() else "not_configured"))
    phone = norm_phone(to_phone)
    if phone and (whatsapp_enabled() or not to_email):
        rows.append(db.Message(org_id=org_id, candidate_id=candidate_id, application_id=application_id, channel="whatsapp",
                               to=phone, subject=subject[:300], body=whatsapp_text or _wa_text(body), template=template,
                               status="queued" if whatsapp_enabled() else "not_configured"))
    for r in rows:
        s.add(r)
    if rows:
        kick()
    return rows


def _wa_text(body: str) -> str:
    # WhatsApp template variables can't contain newlines or long runs of spaces.
    return re.sub(r"\s+", " ", body).strip()[:900]


def _send_email(m: db.Message, sender_name: str = "") -> None:
    msg = EmailMessage()
    name, addr = email.utils.parseaddr(SMTP["FROM"])
    msg["From"] = email.utils.formataddr((sender_name or name, addr)) if addr else SMTP["FROM"]
    msg["To"] = m.to
    msg["Subject"] = m.subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain=(SMTP["FROM"].split("@")[-1].strip("> ") or "talentloop"))
    msg.set_content(m.body)
    ics = _ics_attachment(m)
    if ics:
        msg.add_attachment(ics.encode(), maintype="text", subtype="calendar", filename="interview.ics", params={"method": "REQUEST"})
    port = int(SMTP["PORT"] or 587)
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(SMTP["HOST"], port, context=ctx, timeout=30) as srv:
            if SMTP["USER"]:
                srv.login(SMTP["USER"], SMTP["PASSWORD"])
            srv.send_message(msg)
    else:
        with smtplib.SMTP(SMTP["HOST"], port, timeout=30) as srv:
            srv.ehlo()
            if srv.has_extn("starttls"):
                srv.starttls(context=ctx)
                srv.ehlo()
            if SMTP["USER"]:
                srv.login(SMTP["USER"], SMTP["PASSWORD"])
            srv.send_message(msg)


def _ics_attachment(m: db.Message) -> str:
    """Calendar invite text stored after a marker in the body by the scheduler (see scheduling.py)."""
    mark = "\n\n--ICS--\n"
    if mark in (m.body or ""):
        body, ics = m.body.split(mark, 1)
        m.body = body
        return ics
    return ""


async def _send_whatsapp(m: db.Message) -> None:
    url = f"https://graph.facebook.com/{WA['version']}/{WA['phone_id']}/messages"
    payload = {"messaging_product": "whatsapp", "to": m.to, "type": "template",
               "template": {"name": WA["template"], "language": {"code": WA["lang"]},
                            "components": [{"type": "body", "parameters": [{"type": "text", "text": m.body}]}]}}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(url, json=payload, headers={"Authorization": f"Bearer {WA['token']}"})
    if r.status_code >= 300:
        raise RuntimeError(f"WhatsApp {r.status_code}: {r.text[:300]}")


_running = False


async def dispatch_once(limit: int = 50) -> int:
    """Send queued messages. Returns how many were sent."""
    with db.session() as s:
        rows = s.query(db.Message).filter(db.Message.status == "queued").order_by(db.Message.created_at).limit(limit).all()
        work = [(r.id, r.channel) for r in rows]
    sent = 0
    for mid, channel in work:
        with db.session() as s:
            m = s.get(db.Message, mid)
            if not m or m.status != "queued":
                continue
            try:
                if channel == "email":
                    org = s.get(db.Org, m.org_id) if m.org_id else None
                    sender = ((org.settings or {}).get("sender_name") or org.name) if org else ""
                    await asyncio.to_thread(_send_email, m, sender)
                else:
                    await _send_whatsapp(m)
                m.status, m.sent_at, m.error = "sent", time.time(), ""
                sent += 1
            except Exception as e:
                m.status, m.error = "failed", f"{type(e).__name__}: {str(e)[:400]}"
                log.warning("message %s (%s to %s) failed: %s", m.id, channel, m.to, e)
    return sent


async def _drain():
    global _running
    if _running:
        return
    _running = True
    try:
        while await dispatch_once():
            pass
    finally:
        _running = False


def kick() -> None:
    """Start sending in the background if an event loop is running (requests); the sweeper retries otherwise."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.call_soon(lambda: asyncio.ensure_future(_drain()))


def retry(s, mid: str, org_id: str) -> db.Message | None:
    m = s.get(db.Message, mid)
    if not m or m.org_id != org_id:
        return None
    enabled = email_enabled() if m.channel == "email" else whatsapp_enabled()
    m.status, m.error = ("queued" if enabled else "not_configured"), ""
    kick()
    return m
