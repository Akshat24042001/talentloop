"""Phone-first AI interviews: the AI interviewer calls the candidate's phone through Vapi (outbound call), using the
same interview brain as the browser interview. For frontline roles where candidates don't sit at a webcam.

Needs VAPI_PRIVATE_KEY (server-side key, never sent to browsers) and VAPI_PHONE_NUMBER_ID (a phone number imported
into or bought in Vapi, which the call is placed from). Vapi API: POST https://api.vapi.ai/call with a transient
`assistant`, `phoneNumberId` and `customer.number` (E.164).

Phone interviews have no camera, so there's no face or screen proctoring; the report says so, and integrity rests on
the conversation itself (follow-ups that test real experience) and the human round that follows.
"""
import logging
import os
import time

import httpx

from . import brain, messages, store
from .vapi_config import build_assistant, public_url

log = logging.getLogger("phone")


class PhoneError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def enabled() -> bool:
    return bool((os.getenv("VAPI_PRIVATE_KEY") or "").strip() and (os.getenv("VAPI_PHONE_NUMBER_ID") or "").strip()
                and public_url().startswith("https://"))


async def call_candidate(iid: str, number: str) -> str:
    """Start the interview as a phone call. Returns the Vapi call id."""
    e164 = messages.norm_phone(number)
    if not e164:
        raise PhoneError("That phone number doesn't look valid.")
    from . import interviews
    rec0 = store.load(iid)
    if rec0:                                          # the questions must be in the language the call speaks
        try:
            await interviews.ensure_language(iid, (rec0.get("settings") or {}).get("language") or "en")
        except interviews.LanguageError as e:
            if e.status != 409:
                raise PhoneError(str(e), e.status)
    async with store.lock(iid):
        rec = store.load(iid)
        if not rec:
            raise PhoneError("Interview not found", 404)
        if rec.get("status") in ("completed", "incomplete", "scored", "cancelled") or rec.get("disqualified"):
            raise PhoneError("This interview is already finished.", 409)
        if rec.get("expires_at") and time.time() > rec["expires_at"]:
            raise PhoneError("This interview link has expired.", 410)
        last = (rec.get("vapi") or {}).get("last_phone_call_at", 0)
        if time.time() - last < 120:
            raise PhoneError("We just called you. Please wait two minutes before asking again.", 429)
        try:
            first = brain.start_session(rec)
        except ValueError as e:
            raise PhoneError(str(e), 409)
        lang = (rec.get("settings") or {}).get("language") or "en"
        assistant = build_assistant(iid, rec["plan"], first, rec["state"]["token"], language=lang, phone=True)
        rec.setdefault("settings", {})["channel"] = "phone"
        rec["status"] = "in_progress"
        rec.setdefault("sessions", []).append({"n": rec["state"]["session"], "at": time.time(), "ip": "phone", "ua": f"phone call to ...{e164[-4:]}"})
        rec.setdefault("events", []).append({"type": "phone_call", "ts": None, "server_ts": time.time(), "detail": f"calling ...{e164[-4:]}", "source": "server"})
        rec.setdefault("vapi", {})["last_phone_call_at"] = time.time()
        store.save(rec)
    payload = {"assistant": assistant, "phoneNumberId": os.getenv("VAPI_PHONE_NUMBER_ID", "").strip(), "customer": {"number": "+" + e164}}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("https://api.vapi.ai/call", json=payload, headers={"Authorization": f"Bearer {os.getenv('VAPI_PRIVATE_KEY', '').strip()}"})
    if r.status_code >= 300:
        log.warning("[%s] Vapi call failed %s: %s", iid, r.status_code, r.text[:400])
        raise PhoneError("We couldn't place the call. Please take the interview in your browser, or try again later.", 502)
    call_id = (r.json() or {}).get("id", "")
    async with store.lock(iid):
        rec = store.load(iid)
        v = rec.setdefault("vapi", {})
        if call_id and call_id not in v.get("call_ids", []):
            v.setdefault("call_ids", []).append(call_id)
        store.save(rec)
    log.info("[%s] phone interview call %s placed", iid, call_id)
    return call_id
