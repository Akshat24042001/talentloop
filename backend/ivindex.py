"""Interview index: one database row per AI interview, kept in step with the JSON record on every save.

Lists, dashboards, admin counts, history checks and the background sweeper read this table instead of opening every
interview file. The JSON record (store.py) stays the source of truth; `sync` rebuilds the row from it.
"""
import logging
import os
import time

from . import db, proctor, refs, store

log = logging.getLogger("ivindex")
CLOSED = ("completed", "incomplete", "scored")


def summary(r: dict) -> dict:
    rep = r.get("report") or {}
    pr = proctor.summary(r) if r.get("state") else {}
    dq = r.get("disqualified") or {}
    return {"recommendation": rep.get("recommendation"), "overall": (rep.get("computed") or {}).get("overall"),
            "risk": pr.get("risk"), "decision": (r.get("hr") or {}).get("decision"), "ended_early": bool(r.get("ended_early")),
            "expires_at": r.get("expires_at"), "disqualified": bool(dq), "dq_reason": dq.get("reason", "") if isinstance(dq, dict) else "",
            "dq_at": dq.get("at") if isinstance(dq, dict) else None, "warnings": len(r.get("warnings") or []),
            "started_at": proctor.interview_start(r) if r.get("state") else None, "needs_sweep": needs_sweep(r),
            "human_requested": bool(r.get("human_requested"))}


def needs_sweep(r: dict) -> bool:
    """Does the background sweeper still have work on this interview?"""
    st = r.get("state") or {}
    if r.get("status") == "in_progress" and not st.get("ended"):
        return True
    if r.get("status") in CLOSED:
        if any(m.get("rid") and not m.get("finalized") for m in r.get("media", [])):
            return True
        if r.get("status") in ("completed", "incomplete") and not r.get("report") and (r.get("scoring") or {}).get("state") != "failed":
            return True
        v = r.get("vapi") or {}
        if os.getenv("VAPI_PRIVATE_KEY") and v.get("call_ids") and v.get("fetch_tries", 0) < 6:
            return True
    return False


_LAST: dict[str, str] = {}      # id -> signature of the last synced summary (saves happen on every event)


def _signature(r: dict) -> str:
    plan, st = r.get("plan") or {}, r.get("settings") or {}
    return repr((r.get("status"), bool(r.get("report")), (r.get("report") or {}).get("recommendation"), (r.get("hr") or {}).get("decision"),
                 bool(r.get("disqualified")), len(r.get("warnings") or []), needs_sweep(r), plan.get("candidate_name"), plan.get("role"),
                 st.get("candidate_email"), r.get("org_id"), r.get("job_id"), r.get("application_id"), bool(r.get("human_requested")),
                 len((r.get("state") or {}).get("log") or []) > 0, (r.get("scoring") or {}).get("state")))


def sync(r: dict, force: bool = False) -> None:
    """Upsert the index row for this interview record. Assigns its readable number on first sight."""
    sig = _signature(r)
    if not force and _LAST.get(r["id"]) == sig:
        return
    try:
        with db.session() as s:
            row = s.get(db.InterviewIndex, r["id"])
            if row is None:
                row = db.InterviewIndex(id=r["id"], created_at=r.get("created_at") or time.time())
                s.add(row)
            plan = r.get("plan") or {}
            row.org_id = r.get("org_id")
            if row.number is None:
                row.number = r.get("number") or (db.next_number(s, r["org_id"], "interview") if r.get("org_id") else None)
            row.job_id, row.candidate_id, row.application_id = r.get("job_id"), r.get("candidate_id"), r.get("application_id")
            row.created_by = r.get("created_by")
            row.candidate = (plan.get("candidate_name") or "")[:200]
            row.email = ((r.get("settings") or {}).get("candidate_email") or "").strip().lower()[:320]
            row.role, row.company = (plan.get("role") or "")[:200], (plan.get("company") or "")[:200]
            row.status = r.get("status") or "created"
            row.channel = (r.get("settings") or {}).get("channel") or "web"
            row.language = (r.get("settings") or {}).get("language") or "en"
            row.summary = summary(r)
            row.updated_at = time.time()
        _LAST[r["id"]] = sig
    except Exception:
        log.exception("[%s] index sync failed", r.get("id"))


def remove(iid: str) -> None:
    _LAST.pop(iid, None)
    with db.session() as s:
        s.query(db.InterviewIndex).filter_by(id=iid).delete()


def ref_of(row: db.InterviewIndex) -> str:
    return refs.interview_ref(row.id)


def row_json(row: db.InterviewIndex) -> dict:
    sm = row.summary or {}
    return {"id": row.id, "ref": ref_of(row), "number": row.number, "created_at": row.created_at, "status": row.status,
            "candidate": row.candidate, "role": row.role, "company": row.company, "email": row.email, "channel": row.channel,
            "language": row.language, "job_id": row.job_id, "candidate_id": row.candidate_id, **{k: v for k, v in sm.items() if k != "needs_sweep"}}


def backfill() -> int:
    """Index interviews saved before the index existed (startup)."""
    with db.session() as s:
        have = {i for (i,) in s.query(db.InterviewIndex.id)}
    n = 0
    for p in store.INT_DIR.glob("*.json"):
        iid = p.stem
        if iid in have:
            continue
        rec = store.load(iid)
        if rec:
            sync(rec, force=True)
            n += 1
    return n
