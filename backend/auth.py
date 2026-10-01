"""Accounts, sessions and permissions.

Roles inside a company (several people can share a role):
  owner          everything, including deleting the company
  admin          team, settings, all jobs and candidates
  recruiter      HR: create and edit every job, manage candidates, run matching and interviews, assign collaborators
  hiring_manager a department lead (e.g. Sales Manager): sees and edits only the jobs HR assigns to them
  viewer         read-only
Per job, HR adds collaborators as "editor" (can change the JD) or "reviewer" (can see it and its candidates).
Platform admins (PLATFORM_ADMIN_EMAILS) see every company in the admin console.
The legacy ADMIN_KEY header still works for API automation and acts as a platform admin.
"""
import base64
import hashlib
import hmac
import os
import re
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import HTTPException, Request, Response

from . import db

ROLES = ("owner", "admin", "recruiter", "hiring_manager", "viewer")
ROLE_LABEL = {"owner": "Owner", "admin": "Admin", "recruiter": "Recruiter (HR)", "hiring_manager": "Hiring manager", "viewer": "Viewer"}
MANAGE_TEAM = {"owner", "admin"}
MANAGE_JOBS = {"owner", "admin", "recruiter"}       # create jobs, edit any job, assign collaborators, run matching
SEE_ALL = {"owner", "admin", "recruiter", "viewer"}  # see every job and candidate in the company
COOKIE = "tl_session"
SESSION_DAYS = float(os.getenv("SESSION_DAYS", "14"))
ADMIN_KEY = os.getenv("ADMIN_KEY", "").strip()
PLATFORM_ADMINS = {e.strip().lower() for e in os.getenv("PLATFORM_ADMIN_EMAILS", "").split(",") if e.strip()}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------------------
# passwords: scrypt from the standard library
# ---------------------------------------------------------------------------
def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()


def check_password(pw: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, h = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(got, base64.b64decode(h))
    except Exception:
        return False


def validate_password(pw: str) -> None:
    if len(pw or "") < 8:
        raise HTTPException(400, "Use a password of at least 8 characters.")


def norm_email(e: str) -> str:
    e = (e or "").strip().lower()
    if not EMAIL_RE.match(e) or len(e) > 320:
        raise HTTPException(400, "Enter a valid email address.")
    return e


def token_hash(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()


# ---------------------------------------------------------------------------
# rate limiting (in memory; one server process)
# ---------------------------------------------------------------------------
_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(key: str, limit: int, per_sec: float) -> None:
    q, t = _hits[key], time.time()
    while q and t - q[0] > per_sec:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "Too many attempts. Please wait a minute and try again.")
    q.append(t)


def client_ip(req: Request) -> str:
    fwd = req.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else (req.client.host if req.client else "")) or "?"


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------
def start_session(s, resp: Response, req: Request, user: db.User, org_id: str | None) -> None:
    tok = secrets.token_urlsafe(32)
    s.add(db.AuthSession(token_hash=token_hash(tok), user_id=user.id, org_id=org_id, expires_at=time.time() + SESSION_DAYS * 86400,
                         ip=client_ip(req)[:64], ua=req.headers.get("user-agent", "")[:300]))
    user.last_login_at = time.time()
    user.login_count = (user.login_count or 0) + 1
    secure = os.getenv("COOKIE_SECURE", "auto")
    is_https = req.headers.get("x-forwarded-proto", req.url.scheme) == "https"
    resp.set_cookie(COOKIE, tok, max_age=int(SESSION_DAYS * 86400), httponly=True, samesite="lax", path="/",
                    secure=is_https if secure == "auto" else secure == "1")


def end_session(s, req: Request, resp: Response) -> None:
    tok = req.cookies.get(COOKIE)
    if tok:
        s.query(db.AuthSession).filter_by(token_hash=token_hash(tok)).delete()
    resp.delete_cookie(COOKIE, path="/")


@dataclass
class Ctx:
    user: db.User | None
    org: db.Org | None
    role: str | None          # role in `org`
    platform_admin: bool
    via_key: bool = False

    @property
    def user_id(self) -> str | None:
        return self.user.id if self.user else None

    @property
    def org_id(self) -> str | None:
        return self.org.id if self.org else None

    def has(self, roles: set[str]) -> bool:
        return self.via_key or (self.role in roles)


def _key_ok(req: Request) -> bool:
    if not ADMIN_KEY:
        return False
    key = req.headers.get("x-admin-key") or req.query_params.get("key") or ""
    return bool(key) and secrets.compare_digest(key.encode(), ADMIN_KEY.encode())


def current(req: Request, s, required: bool = True) -> Ctx | None:
    """Who is calling. Raises 401 when required and nobody is signed in."""
    if _key_ok(req):
        return Ctx(user=None, org=None, role="owner", platform_admin=True, via_key=True)
    tok = req.cookies.get(COOKIE)
    if tok:
        sess = s.get(db.AuthSession, token_hash(tok))
        if sess and sess.expires_at > time.time():
            user = s.get(db.User, sess.user_id)
            if user and not user.disabled:
                org = role = None
                mem = None
                if sess.org_id:
                    mem = s.query(db.Membership).filter_by(user_id=user.id, org_id=sess.org_id).first()
                if not mem:
                    mem = s.query(db.Membership).filter_by(user_id=user.id).order_by(db.Membership.created_at).first()
                    if mem:
                        sess.org_id = mem.org_id
                if mem:
                    org = s.get(db.Org, mem.org_id)
                    role = mem.role
                    if org and org.disabled and not user.is_platform_admin:
                        raise HTTPException(403, "This company account is disabled. Contact support.")
                return Ctx(user=user, org=org, role=role, platform_admin=bool(user.is_platform_admin))
    if required:
        raise HTTPException(401, "Please sign in.")
    return None


def require(ctx: Ctx, roles: set[str], what: str = "do this") -> None:
    if not ctx.has(roles):
        raise HTTPException(403, f"Your role can't {what}.")


def require_org(ctx: Ctx) -> str:
    if not ctx.org_id:
        raise HTTPException(400, "Join or create a company workspace first.")
    return ctx.org_id


# ---------------------------------------------------------------------------
# per-job access
# ---------------------------------------------------------------------------
def job_permission(s, ctx: Ctx, job: db.Job) -> str | None:
    """'manage' (HR and above), 'edit' (JD editor), 'view' (reviewer or viewer) or None."""
    if ctx.via_key:
        return "manage"
    if job.org_id != ctx.org_id:
        return None
    if ctx.role in MANAGE_JOBS:
        return "manage"
    collab = s.query(db.JobCollaborator).filter_by(job_id=job.id, user_id=ctx.user_id).first()
    if collab:
        return "edit" if collab.permission == "editor" else "view"
    if ctx.role in SEE_ALL:
        return "view"
    return None


def visible_job_ids(s, ctx: Ctx) -> list[str] | None:
    """None = every job in the company; otherwise the jobs this person was assigned to."""
    if ctx.via_key or ctx.role in SEE_ALL:
        return None
    return [c.job_id for c in s.query(db.JobCollaborator).filter_by(user_id=ctx.user_id)]


def slugify(s: str, n: int = 60) -> str:
    x = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:n].strip("-")
    return x or "company"
