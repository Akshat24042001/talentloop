"""Creating AI interview records: one path for HR's "New interview" page and for the AI interview round of a hiring
flow (setup.py), so both get the same settings, index row, application link and readable reference."""
import hashlib
import hmac
import os
import secrets
import time

from . import db, jd_schema, refs, store
from .api_accounts import org_settings

RECONNECT_WINDOW_SEC = int(os.getenv("RECONNECT_WINDOW_SEC", "90"))


def _intish(v, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def settings_from(s: dict | None) -> dict:
    s = s or {}
    out = {"candidate_email": str(s.get("candidate_email") or "")[:200],
           "candidate_phone": str(s.get("candidate_phone") or "")[:40],
           "require_screen_share": bool(s.get("require_screen_share")),
           "reconnect_window_sec": max(10, min(900, int(s.get("reconnect_window_sec") or RECONNECT_WINDOW_SEC))),
           "face_detection": s.get("face_detection", True) is not False,
           "snapshots": s.get("snapshots", True) is not False,
           "enforce_focus": s.get("enforce_focus", True) is not False,
           "block_multi_monitor": s.get("block_multi_monitor", True) is not False,
           "max_warnings": max(0, min(5, _intish(s.get("max_warnings"), 2))),
           "hr_note": str(s.get("hr_note") or "")[:500],
           "language": str(s.get("language") or "en")[:10],
           "channel": "phone" if s.get("channel") == "phone" else "web",
           "practice_question": s.get("practice_question", True) is not False,
           "liveness_check": s.get("liveness_check", True) is not False,
           "identity_check": s.get("identity_check", True) is not False,
           # someone else in the room, phones, earphones (see main.vision_check and the interview page)
           "room_scan": s.get("room_scan", True) is not False,
           "ear_check": s.get("ear_check", True) is not False,
           "strict_room": s.get("strict_room", True) is not False,
           "vision_check_sec": 0 if _intish(s.get("vision_check_sec"), 120) <= 0 else max(45, min(900, _intish(s.get("vision_check_sec"), 120)))}
    af = s.get("available_from")
    out["available_from"] = float(af) if isinstance(af, (int, float)) and af > 0 else None
    # when it opens: "pick" = the candidate books a time (selfbook.py), "fixed" = available_from, "now" = straight away
    out["opening"] = s.get("opening") if s.get("opening") in ("pick", "fixed", "now") else ("fixed" if out["available_from"] else "now")
    if out["opening"] == "pick":
        out["available_from"] = None
    return out


def create_record(*, org_id: str | None, created_by: str | None, job_id: str | None, candidate_id: str | None,
                  application_id: str | None, round_result_id: str | None = None, plan: dict, inputs: dict, settings: dict,
                  expires_hours: float = 72, lines: dict | None = None) -> dict:
    iid = secrets.token_urlsafe(9).replace("-", "x").replace("_", "y")
    now = time.time()
    starts = settings.get("available_from") or now
    rec = {"id": iid, "created_at": now, "org_id": org_id, "created_by": created_by, "job_id": job_id,
           "candidate_id": candidate_id, "application_id": application_id, "round_result_id": round_result_id,
           "expires_at": starts + max(0.5, float(expires_hours or 72)) * 3600,
           "status": "created", "plan": plan, "inputs": inputs, "state": None, "snapshots": [],
           "events": [], "media": [], "images": [], "sessions": [], "vapi": {}, "report": None, "hr": {},
           "scoring": None, "settings": settings, "lines": lines or {}, "access": new_access()}
    if settings.get("practice_question", True):
        from . import brain
        brain.add_practice(plan, rec)
    if org_id:
        with db.session() as s:          # FAQ answers and disclosure come from the company (HR-approved)
            org = s.get(db.Org, org_id)
            st = org_settings(org) if org else {}
            rec["company_faq"] = [f for f in st.get("faq", []) if f.get("q") and f.get("a")][:30]
    store.save(rec)
    if application_id:
        with db.session() as s:
            app_ = s.get(db.Application, application_id)
            if app_ and app_.org_id == org_id:
                app_.interview_id = iid
                if app_.stage in ("applied", "screening", "shortlisted"):
                    app_.stage = "interview"
    return rec


def jd_text(job: db.Job, org: db.Org) -> str:
    """The job description as plain text for an interview plan."""
    jd = jd_schema.compose(job.fields or {}, org.name, org_settings(org), public=False)
    parts = [jd["title"], " | ".join(jd["facts"])]
    for sec in jd["sections"]:
        parts.append(sec["title"] + "\n" + (sec.get("body") or "") + "\n" + "\n".join("- " + x for x in sec.get("items") or []))
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------------------------------------------------
# Candidate access: the link carries an encrypted key (never the interview id), and a 6-digit access code, emailed
# separately, unlocks it in each browser. A leaked link alone opens nothing.
# ---------------------------------------------------------------------------------------------------------------------
CODE_TRIES, CODE_WINDOW_SEC = 5, 15 * 60


def new_access() -> dict:
    return {"code": f"{secrets.randbelow(10 ** 6):06d}", "fails": [], "unlocks": [], "issued_at": time.time()}


def cand_key(iid: str) -> str:
    return refs.encode("ivc", iid)


def iid_of_key(key: str) -> str | None:
    return refs.decode("ivc", key)


def cand_path(iid: str) -> str:
    return f"/interview.html?k={cand_key(iid)}"


def cand_url(iid: str) -> str:
    from .flows import base_url
    return base_url() + cand_path(iid)


def pass_value(iid: str, code: str) -> str:
    """What the browser keeps after the code was entered: tied to this interview and this code (a new code logs out)."""
    return hmac.new(refs.key(), f"ivpass|{iid}|{code}".encode(), hashlib.sha256).hexdigest()[:40]


def cookie_name(iid: str) -> str:
    return "ivp_" + hashlib.sha256(iid.encode()).hexdigest()[:12]


def code_of(rec: dict) -> str:
    return ((rec.get("access") or {}).get("code")) or ""


def _contact(rec: dict) -> tuple[str, str, str]:
    st = rec.get("settings") or {}
    return (st.get("candidate_email") or "").strip(), (st.get("candidate_phone") or "").strip(), (rec.get("plan") or {}).get("candidate_name") or ""


def email_code(rec: dict) -> bool:
    """The access code on its own (never in the same email as the link), so a forwarded or leaked link opens nothing."""
    from . import messages
    to, phone, name = _contact(rec)
    if not (to or phone) or not rec.get("org_id"):
        return False
    p = rec.get("plan") or {}
    first = (name or "there").split()[0]
    body = (f"Hi {first},\n\nYour access code for the {p.get('role') or 'AI'} interview at {p.get('company') or 'our company'} is:\n\n"
            f"    {code_of(rec)}\n\nThe interview page asks for it before anything opens. Keep it to yourself: with the link alone nobody "
            f"can open your interview. If you didn't expect this email, you can ignore it.\n\nRegards,\n{p.get('company') or ''} Hiring Team")
    with db.session() as s:
        messages.queue(s, rec["org_id"], to_email=to, to_phone=phone, subject=f"Your interview access code | {p.get('company') or ''}".strip(" |"),
                       body=body, template="interview_access_code", candidate_id=rec.get("candidate_id"), application_id=rec.get("application_id"),
                       whatsapp_text=f"Hi {first}, your access code for the {p.get('role') or ''} interview at {p.get('company') or ''} is {code_of(rec)}.")
    return True
