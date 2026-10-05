"""Candidate sign-in: "My applications" at /me.

Candidates have no password. They type their email, get a 6-digit code by email, and see every application made with
that email (at any company on TalentLoop): stage, the current step, interview times, and links to take a step, change
or cancel an interview time, or open the status page.

The code is derived (HMAC of email and a 10-minute window), so nothing is stored; a used code is remembered in memory
so it works once. The session is a signed cookie with the email and an expiry. Sign-in emails are hidden from the
company's outbox, so nobody at a company can read a candidate's code.
"""
import base64
import hashlib
import hmac
import os
import re
import time
from collections import OrderedDict

from fastapi import APIRouter, HTTPException, Request, Response

from . import auth, db, flows, messages, refs, tzfmt

router = APIRouter()
COOKIE = "tl_me"
DAYS = 30
WINDOW = 600
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_used: "OrderedDict[str, float]" = OrderedDict()


def _code(email: str, window: int) -> str:
    n = int.from_bytes(hmac.new(refs.key(), f"login|{email}|{window}".encode(), hashlib.sha256).digest()[:6], "big")
    return f"{n % 1_000_000:06d}"


def _sign(email: str, exp: int) -> str:
    raw = f"{email}|{exp}"
    mac = hmac.new(refs.key(), f"me|{raw}".encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(f"{raw}|{mac}".encode()).decode()


def me_email(req: Request) -> str | None:
    tok = req.cookies.get(COOKIE, "")
    try:
        email, exp, mac = base64.urlsafe_b64decode(tok.encode()).decode().rsplit("|", 2)
    except Exception:
        return None
    good = hmac.new(refs.key(), f"me|{email}|{exp}".encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(mac, good) or int(exp) < time.time():
        return None
    return email


def _drives_for(s, email: str) -> list:
    """Campus drives where this email is the placement officer (set on the drive by HR)."""
    return [d for d in s.query(db.Drive).limit(20000) if str((d.settings or {}).get("officer_email") or "").strip().lower() == email]


def _apps_for(s, email: str):
    cands = s.query(db.Candidate).filter(db.Candidate.email == email).all()
    if not cands:
        return []
    return s.query(db.Application).filter(db.Application.candidate_id.in_([c.id for c in cands])).order_by(db.Application.created_at.desc()).all()


@router.post("/api/me/code")
async def send_code(req: Request):
    body = await req.json()
    email = str(body.get("email") or "").strip().lower()[:200]
    if not EMAIL.match(email):
        raise HTTPException(400, "Please enter a valid email.")
    auth.rate_limit(f"me-code:{auth.client_ip(req)}", 10, 3600)
    auth.rate_limit(f"me-code-email:{email}", 4, 3600)
    with db.session() as s:
        apps = [a for a in _apps_for(s, email) if (o := s.get(db.Org, a.org_id)) and not o.disabled]
        org_id = apps[0].org_id if apps else next((d.org_id for d in _drives_for(s, email)), None)
        if org_id:                                       # the reply is the same either way: no account discovery
            code = _code(email, int(time.time() // WINDOW))
            messages.queue(s, org_id, to_email=email, subject="Your TalentLoop sign-in code",
                           body=f"Your TalentLoop sign-in code is {code}.\n\nIt works once, for about 10 minutes. If you didn't ask for it, ignore this email.",
                           template="candidate_login")
    return {"ok": True}


@router.post("/api/me/verify")
async def verify(req: Request, resp: Response):
    body = await req.json()
    email = str(body.get("email") or "").strip().lower()[:200]
    code = re.sub(r"\D", "", str(body.get("code") or ""))
    auth.rate_limit(f"me-verify:{auth.client_ip(req)}", 20, 600)
    auth.rate_limit(f"me-verify-email:{email}", 8, 600)
    w = int(time.time() // WINDOW)
    key = f"{email}|{code}"
    if len(code) != 6 or key in _used or not any(hmac.compare_digest(code, _code(email, x)) for x in (w, w - 1)):
        raise HTTPException(400, "That code isn't right or has expired. Ask for a new one.")
    _used[key] = time.time()
    while len(_used) > 5000:
        _used.popitem(last=False)
    exp = int(time.time() + DAYS * 86400)
    secure = os.getenv("COOKIE_SECURE", "auto")
    https = req.headers.get("x-forwarded-proto", req.url.scheme) == "https"
    resp.set_cookie(COOKIE, _sign(email, exp), max_age=DAYS * 86400, httponly=True, samesite="lax", path="/",
                    secure=https if secure == "auto" else secure == "1")
    return {"ok": True}


@router.post("/api/me/logout")
def logout(resp: Response):
    resp.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/api/me")
def my_applications(req: Request):
    email = me_email(req)
    if not email:
        raise HTTPException(401, "Please sign in.")
    from .api_portal import CAND_STAGE, brand
    out = []
    with db.session() as s:
        for a in _apps_for(s, email):
            job, org = s.get(db.Job, a.job_id), s.get(db.Org, a.org_id)
            if not job or not org or org.disabled:
                continue
            rnd = flows.round_of(job, a.round_id) if a.round_id else None
            rr = flows.get_result(s, a, a.round_id) if a.round_id else None
            step = None
            if rnd and rr and a.stage not in flows.CLOSED_STAGES + flows.FINAL_STAGES:
                kind = rnd["type"]
                link = flows.invite_link(s, rr) if kind not in ("cv_screening", "manager_approval", "application") and rr.status in ("invited", "in_progress", "booked") else None
                b = (rr.data or {}).get("booking" if kind == "human_interview" else "ai_booking")
                b = b if b and not b.get("cancelled_at") else None
                step = {"name": "Hiring manager review" if kind == "manager_approval" else rnd["name"], "type": kind, "status": rr.status,
                        "status_label": flows.STATUS_LABEL.get(rr.status, rr.status), "link": link, "deadline_at": rr.deadline_at,
                        "booking": {"starts_at": b["starts_at"], "ends_at": b["ends_at"], "interviewer": b.get("interviewer", "")} if b else None}
            out.append({"id": refs.app_ref(a.id), "org": brand(org), "job": job.title, "stage": a.stage, "stage_label": CAND_STAGE.get(a.stage, a.stage),
                        "applied_at": a.created_at, "status_link": flows.status_link(a), "step": step, "timezone": tzfmt.org_tz(org)})
        drives = []
        for d in _drives_for(s, email):
            org = s.get(db.Org, d.org_id)
            if not org or org.disabled:
                continue
            from .api_flows import drive_jobs
            drives.append({"college": d.college, "org": brand(org), "roles": [j.title for j in drive_jobs(s, d)],
                           "results_link": f"{flows.base_url()}/results/{d.share_code}", "register_link": f"{flows.base_url()}/drive/{d.code}",
                           "opens_at": d.opens_at, "registered": s.query(db.Application).filter(db.Application.drive_id == d.id).count()})
    return {"email": email, "applications": out, "drives": drives}
