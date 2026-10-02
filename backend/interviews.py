"""Creating AI interview records: one path for HR's "New interview" page and for the AI interview round of a hiring
flow (setup.py), so both get the same settings, index row, application link and readable reference."""
import os
import secrets
import time

from . import db, jd_schema, store
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
           "identity_check": s.get("identity_check", True) is not False}
    af = s.get("available_from")
    out["available_from"] = float(af) if isinstance(af, (int, float)) and af > 0 else None
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
           "scoring": None, "settings": settings, "lines": lines or {}}
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
