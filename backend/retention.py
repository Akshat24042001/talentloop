"""Retention: delete recordings and photos once they are no longer needed (Settings > Hiring and Matching & AI).

- recording_retention_days: N days after a candidate's application is closed (rejected, withdrawn or hired), delete
  their video introductions, role-task recordings, practical task uploads, test snapshots, interviewer recordings,
  the AI interview's recordings and snapshots, and the registration photo (unless another application is open).
  Scores, transcripts, written feedback and decisions are kept.
- retention_days: delete whole AI interview records (with their recordings) N days after they were created.
"""
import logging
import time

from . import db, store
from .api_accounts import log_activity, org_settings

log = logging.getLogger("retention")
CLOSED = ("rejected", "withdrawn", "hired")


def _strip_round(rr: db.RoundResult) -> int:
    """Delete one round's files and remove their keys. Returns how many files were deleted."""
    d, g = dict(rr.data or {}), dict(rr.integrity or {})
    keys = [d.get("file"), (d.get("feedback") or {}).get("recording_file"), g.get("start_photo")] + [x.get("file") for x in g.get("snapshots") or []]
    keys = [k for k in keys if k]
    for k in keys:
        store.delete_files(k)
    d.pop("file", None)
    if d.get("feedback"):
        d["feedback"] = {**d["feedback"], "recording_file": ""}
    g.pop("start_photo", None)
    if g.get("snapshots"):
        g["snapshots"] = []
    d["media_deleted_at"] = time.time()
    rr.data, rr.integrity = d, g
    return len(keys)


def _strip_interview(iid: str) -> bool:
    rec = store.load(iid)
    if not rec or rec.get("media_deleted_at") or not (rec.get("media") or rec.get("images")):
        return False
    store.delete_media(iid)
    rec["media"], rec["images"], rec["media_deleted_at"] = [], [], time.time()
    store.save(rec)
    return True


def sweep(limit: int = 200) -> dict:
    """One pass over every company with a retention setting. Bounded per pass; the sweeper repeats it."""
    now, out = time.time(), {"rounds": 0, "files": 0, "interviews": 0, "photos": 0, "interviews_deleted": 0}
    with db.session() as s:
        orgs = [(o.id, org_settings(o)) for o in s.query(db.Org)]
    for org_id, st in orgs:
        days = float(st.get("recording_retention_days") or 0)
        if days > 0:
            cutoff = now - days * 86400
            with db.session() as s:
                apps = s.query(db.Application).filter(db.Application.org_id == org_id, db.Application.stage.in_(CLOSED),
                                                      db.Application.decided_at.isnot(None), db.Application.decided_at < cutoff).limit(2000).all()
                done = 0
                for a in apps:
                    rrs = [r for r in s.query(db.RoundResult).filter(db.RoundResult.application_id == a.id) if not (r.data or {}).get("media_deleted_at")]
                    for rr in rrs:
                        out["files"] += _strip_round(rr)
                        out["rounds"] += 1
                    if a.interview_id and _strip_interview(a.interview_id):
                        out["interviews"] += 1
                    c = s.get(db.Candidate, a.candidate_id)
                    if c and c.photo_file and not s.query(db.Application).filter(db.Application.candidate_id == c.id,
                                                                                 db.Application.stage.notin_(CLOSED)).count():
                        store.delete_files(c.photo_file)
                        c.photo_file = ""
                        out["photos"] += 1
                    done += bool(rrs)
                    if out["rounds"] >= limit:
                        break
                if done:
                    log_activity(s, None, "retention_sweep", f"Recordings and photos of {done} closed application(s) deleted after {days:g} days",
                                 org_id=org_id)
        idays = float(st.get("retention_days") or 0)
        if idays > 0:
            with db.session() as s:
                old = [i for (i,) in s.query(db.InterviewIndex.id).filter(db.InterviewIndex.org_id == org_id,
                                                                          db.InterviewIndex.created_at < now - idays * 86400).limit(limit)]
            for iid in old:
                store.delete(iid)
                out["interviews_deleted"] += 1
            if old:
                with db.session() as s:
                    log_activity(s, None, "retention_sweep", f"{len(old)} AI interview(s) deleted after {idays:g} days", org_id=org_id)
    if any(out.values()):
        log.info("retention: %s", out)
    return out
