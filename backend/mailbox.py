"""Import resumes from a mailbox over IMAP (for example careers@yourcompany.com).

Every unread email in IMAP_FOLDER with a resume attached (PDF, DOCX or TXT) becomes a candidate in the company
IMAP_ORG_SLUG, de-duplicated by email. If the subject names an open job (its title or its reference, like
"backend-engineer-1"), the candidate also applies to that job and enters its hiring flow. Processed emails are
marked as read, so use a mailbox dedicated to applications.

Settings: IMAP_HOST, IMAP_USER, IMAP_PASSWORD, IMAP_ORG_SLUG, optional IMAP_PORT (993), IMAP_FOLDER (INBOX) and
IMAP_EVERY_SEC (300).
"""
import email
import email.policy
import email.utils
import imaplib
import logging
import os
from pathlib import Path

from . import db, flows, refs, resumes

log = logging.getLogger("mailbox")


def _env(k: str, d: str = "") -> str:
    return (os.getenv(k) or d).strip()


def enabled() -> bool:
    return all(_env(k) for k in ("IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD", "IMAP_ORG_SLUG"))


def every_sec() -> float:
    return float(_env("IMAP_EVERY_SEC", "300") or 300)


def _attachments(msg) -> list[tuple[str, bytes]]:
    out = []
    for part in msg.walk():
        name = part.get_filename()
        if not name or Path(name).suffix.lower() not in resumes.RESUME_TYPES:
            continue
        raw = part.get_payload(decode=True) or b""
        if 0 < len(raw) <= resumes.MAX_RESUME_BYTES and not (name.lower().endswith(".pdf") and not raw.startswith(b"%PDF")):
            out.append((Path(name).name[:150], raw))
    return out


def _job_for(s, org_id: str, subject: str) -> db.Job | None:
    subj = (subject or "").lower()
    if not subj:
        return None
    jobs = s.query(db.Job).filter(db.Job.org_id == org_id, db.Job.status == "open").all()
    for j in jobs:                                     # the job's reference wins, then the longest matching title
        if refs.job_ref(j).lower() in subj:
            return j
    hits = [j for j in jobs if j.title and j.title.lower() in subj]
    return max(hits, key=lambda j: len(j.title)) if hits else None


def import_message(org: db.Org, msg) -> dict | None:
    """One email: the candidate (and application) it produced, or None when it has no resume."""
    from .api_accounts import log_activity
    from .api_hiring import upsert_candidate
    files = _attachments(msg)
    if not files:
        return None
    fname, raw = files[0]
    text = resumes.extract_text(raw, fname)
    parsed = resumes.parse(text)
    sender_name, sender = email.utils.parseaddr(str(msg.get("From") or ""))
    emails = parsed.get("emails") or []          # the resume's own address first; the sender may be a job board
    profile = {"name": parsed.get("name_guess") or sender_name or "", "email": emails[0] if emails else sender}
    if not profile["email"]:
        return None
    with db.session() as s:
        cand, created = upsert_candidate(s, org.id, text=text, parsed=parsed, profile=profile, source="email", raw=raw, filename=fname)
        job = _job_for(s, org.id, str(msg.get("Subject") or ""))
        applied = False
        if job and not s.query(db.Application).filter_by(job_id=job.id, candidate_id=cand.id).first():
            app = db.Application(org_id=org.id, job_id=job.id, candidate_id=cand.id, stage="applied", source="email",
                                 cover_letter=_body_text(msg)[:5000])
            s.add(app)
            s.flush()
            flows.on_applied(s, app, job)
            s.query(db.Job).filter_by(id=job.id).update({db.Job.matched_at: None})
            applied = True
        log_activity(s, None, "mailbox_import", f"{cand.name or cand.email} from email" + (f", applied to {job.title}" if applied else ""),
                     org_id=org.id, job_id=job.id if applied else None, candidate_id=cand.id)
        return {"candidate_id": cand.id, "created": created, "job_id": job.id if applied else None}


def _body_text(msg) -> str:
    part = msg.get_body(preferencelist=("plain",)) if hasattr(msg, "get_body") else None
    try:
        return (part.get_content() if part else "").strip()
    except Exception:
        return ""


def import_once(limit: int = 25) -> dict:
    """Blocking (run in a thread). Reads up to `limit` unread emails."""
    out = {"emails": 0, "candidates": 0, "applications": 0, "skipped": 0}
    if not enabled():
        return out
    with db.session() as s:
        org = s.query(db.Org).filter(db.Org.slug == _env("IMAP_ORG_SLUG")).first()
        if not org:
            log.warning("IMAP_ORG_SLUG %r matches no company", _env("IMAP_ORG_SLUG"))
            return out
        s.expunge(org)
    imap = imaplib.IMAP4_SSL(_env("IMAP_HOST"), int(_env("IMAP_PORT", "993") or 993), timeout=60)
    try:
        imap.login(_env("IMAP_USER"), _env("IMAP_PASSWORD"))
        imap.select(_env("IMAP_FOLDER", "INBOX"))
        typ, data = imap.search(None, "UNSEEN")
        ids = (data[0].split() if typ == "OK" and data and data[0] else [])[:limit]
        for num in ids:
            typ, parts = imap.fetch(num, "(BODY.PEEK[])")
            raw = next((p[1] for p in parts or [] if isinstance(p, tuple)), None)
            if typ != "OK" or not raw:
                continue
            out["emails"] += 1
            try:
                res = import_message(org, email.message_from_bytes(raw, policy=email.policy.default))
            except Exception:
                log.exception("could not import email %s", num)
                res = None
            if res:
                out["candidates"] += 1
                out["applications"] += bool(res["job_id"])
            else:
                out["skipped"] += 1
            imap.store(num, "+FLAGS", "\\Seen")
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    if out["emails"]:
        log.info("mailbox import: %s", out)
    return out
