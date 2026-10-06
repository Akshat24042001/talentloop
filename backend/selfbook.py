"""Standalone AI interviews (HR's "New AI interview" page): the invitation email, and the candidate picking their own
time on the interview page.

HR chooses one of three openings: "pick" (the candidate books a time before the deadline; the interview opens 10
minutes before it), "now" (any time before the deadline) or "fixed" (HR's time). The invitation never carries the
access code: interviews.email_code sends it separately.
"""
import hashlib
import time

from . import db, interviews, messages, store, tzfmt
from .scheduling import AI_STEP, ics

EARLY_SEC = 10 * 60          # the interview opens this long before the booked time
CUTOFF_SEC = 30 * 60         # the time can't be changed this close to it
CHANGES = 3
DAY_FROM, DAY_TO = 8, 22     # company hours offered to the candidate


def _org(rec: dict):
    with db.session() as s:
        org = s.get(db.Org, rec.get("org_id")) if rec.get("org_id") else None
        if org is not None:
            s.expunge(org)
        return org


def _minutes(rec: dict) -> int:
    return int((rec.get("plan") or {}).get("duration_min") or 15)


def booking(rec: dict) -> dict | None:
    b = rec.get("booking")
    return b if b and not b.get("cancelled_at") else None


def needs_booking(rec: dict) -> bool:
    return (rec.get("settings") or {}).get("opening") == "pick" and booking(rec) is None


def can_change(rec: dict) -> tuple[bool, str]:
    b = booking(rec)
    if not b:
        return True, ""
    if int(rec.get("booking_changes", 0)) >= CHANGES:
        return False, "You've changed the time the maximum number of times."
    if b["starts_at"] - time.time() < CUTOFF_SEC:
        return False, "Your interview is about to start, so the time can't be changed now."
    return True, ""


def slots(rec: dict) -> list[float]:
    """Start times every 30 minutes in company hours, from 30 minutes from now until the link's deadline."""
    tz = tzfmt.org_tz(_org(rec))
    now = time.time()
    t = (int(now + CUTOFF_SEC) // AI_STEP + 1) * AI_STEP
    last = min(float(rec.get("expires_at") or now + 7 * 86400), now + 14 * 86400) - _minutes(rec) * 60
    out = []
    while t <= last and len(out) < 600:
        lt = tzfmt.local(t, tz)
        h = lt.hour + lt.minute / 60
        if DAY_FROM <= h and h + _minutes(rec) / 60 <= DAY_TO:
            out.append(float(t))
        t += AI_STEP
    return out


def view(rec: dict) -> dict:
    ok, why = can_change(rec)
    return {"opening": (rec.get("settings") or {}).get("opening") or "now", "booking": booking(rec), "can_change": ok, "why": why,
            "changes_left": max(0, CHANGES - int(rec.get("booking_changes", 0))), "timezone": tzfmt.org_tz(_org(rec)),
            "deadline": rec.get("expires_at"), "minutes": _minutes(rec), "slots": slots(rec) if ok else []}


def book(rec: dict, starts_at: float) -> dict:
    """Book or move the candidate's time (the caller holds the record lock and saves it)."""
    if (rec.get("settings") or {}).get("opening") != "pick":
        raise ValueError("This interview doesn't need a time to be booked.")
    if rec.get("status") != "created":
        raise ValueError("This interview has already started.")
    ok, why = can_change(rec)
    if not ok:
        raise ValueError(why)
    starts_at = float(starts_at)
    if starts_at not in set(slots(rec)):
        raise ValueError("That time isn't available any more. Please pick another.")
    old = booking(rec)
    if old:
        rec["booking_changes"] = int(rec.get("booking_changes", 0)) + 1
    seq = int(rec.get("ics_seq", 0)) + (1 if old else 0)
    rec["ics_seq"] = seq
    rec["booking"] = {"starts_at": starts_at, "ends_at": starts_at + _minutes(rec) * 60, "booked_at": time.time(), "seq": seq}
    rec.setdefault("booking_history", []).append({"at": time.time(), "starts_at": starts_at, "action": "rescheduled" if old else "booked"})
    rec["settings"]["available_from"] = starts_at - EARLY_SEC
    rec["expires_at"] = max(float(rec.get("expires_at") or 0), starts_at + _minutes(rec) * 60 + 2 * 3600)
    _confirm(rec, old)
    return rec["booking"]


def _send(rec: dict, subject: str, body: str, template: str, wa: str) -> bool:
    to = ((rec.get("settings") or {}).get("candidate_email") or "").strip()
    phone = ((rec.get("settings") or {}).get("candidate_phone") or "").strip()
    if not (to or phone) or not rec.get("org_id"):
        return False
    with db.session() as s:
        messages.queue(s, rec["org_id"], to_email=to, to_phone=phone, subject=subject, body=body, template=template,
                       candidate_id=rec.get("candidate_id"), application_id=rec.get("application_id"), whatsapp_text=wa)
    return True


def _names(rec: dict) -> tuple[str, str, str]:
    p = rec.get("plan") or {}
    return ((p.get("candidate_name") or "there").split() or ["there"])[0], p.get("role") or "the role", p.get("company") or "our company"


TIPS = ("Use Chrome or Edge on a laptop, in a quiet room on your own. The interview checks your camera, the room and "
        "your ears before it starts, so keep earphones out of reach.")


def invite(rec: dict) -> bool:
    """The invitation HR's "New AI interview" page sends (the access code follows in its own email)."""
    first, role, company = _names(rec)
    org = _org(rec)
    tz = tzfmt.org_tz(org)
    link = interviews.cand_url(rec["id"])
    st = rec.get("settings") or {}
    deadline = tzfmt.when(float(rec["expires_at"]), tz)
    opening = st.get("opening") or "now"
    if opening == "pick":
        what = f"Please open the link and pick a time that suits you, before {deadline}. You'll get a confirmation with a calendar invite."
    elif opening == "fixed" and st.get("available_from"):
        what = f"It opens at {tzfmt.when(float(st['available_from']), tz)} and stays open until {deadline}."
    else:
        what = f"Take it whenever you're ready, before {deadline}."
    body = (f"Hi {first},\n\n{company} invites you to a first-round interview for {role}: a voice conversation with an AI "
            f"interviewer in your browser, about {_minutes(rec)} minutes.\n\n{what}\n\nInterview link: {link}\n\n"
            f"The page asks for an access code. It comes in a separate email, so a forwarded link opens nothing.\n\n{TIPS}\n\n"
            f"Regards,\n{company} Hiring Team")
    sent = _send(rec, f"Interview invitation: {role} at {company}", body, "ai_interview_invite",
                 f"Hi {first}, {company} invites you to an AI interview for {role}. {what} Link: {link} (the access code comes separately)")
    if sent:
        interviews.email_code(rec)
    return sent


def _confirm(rec: dict, old: dict | None) -> None:
    first, role, company = _names(rec)
    tz = tzfmt.org_tz(_org(rec))
    b = rec["booking"]
    link = interviews.cand_url(rec["id"])
    when = tzfmt.when(b["starts_at"], tz)
    head = f"Your AI interview for {role} at {company} is {'moved to' if old else 'booked for'} {when} (about {_minutes(rec)} minutes)."
    left = CHANGES - int(rec.get("booking_changes", 0))
    body = (f"Hi {first},\n\n{head}\n" + (f"Previously: {tzfmt.when(old['starts_at'], tz)}\n" if old else "") +
            f"\nInterview link: {link}\nThe link opens 10 minutes before your time. Enter the access code from the separate email.\n"
            + (f"You can change the time {left} more time(s), up to 30 minutes before, from the same link.\n" if left > 0 else "")
            + f"\n{TIPS}\n\nRegards,\n{company} Hiring Team")
    uid = hashlib.sha256(("ics|" + rec["id"]).encode()).hexdigest()[:24]       # never the interview id
    cal = ics(uid, b["starts_at"], b["ends_at"], f"AI interview: {role} at {company}", f"{head}\nInterview link: {link}", link, seq=b["seq"])
    _send(rec, f"AI interview {'rescheduled' if old else 'booked'}: {when} | {role}", f"{body}\n\n--ICS--\n{cal}", "ai_interview_booked",
          f"Hi {first}, {head} Link: {link}")


def save_booking(iid: str, starts_at: float) -> dict:
    rec = store.load(iid)
    b = book(rec, starts_at)
    store.save(rec)
    return b
