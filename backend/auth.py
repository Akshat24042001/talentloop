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
import logging
import hashlib
import hmac
import os
import re
import secrets

from sqlalchemy import and_
import time
from collections import defaultdict, deque
from dataclasses import dataclass

log = logging.getLogger("auth")

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
        wait = max(1, int(q[0] + per_sec - t))
        when = f"{wait} seconds" if wait < 90 else f"{round(wait / 60)} minutes"
        raise HTTPException(429, f"Too many attempts from this connection. Please try again in {when}.")
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
    claims = _bearer_claims(req)
    if claims:
        s.query(db.AuthSession).filter_by(token_hash=claims["sid"]).delete()
    resp.delete_cookie(COOKIE, path="/")


# ---------------------------------------------------------------------------
# JWT for API clients (Swagger "Authorize", scripts, mobile apps). The browser keeps its HttpOnly cookie.
# An access token is short-lived (JWT_ACCESS_MINUTES, default 60) and names a session row, so signing out,
# a password reset, disabling the user or "sign out everywhere" revoke it at once, like a cookie session.
# The refresh token is an opaque random string (only its hash is stored) that lasts SESSION_DAYS.
# ---------------------------------------------------------------------------
JWT_ISSUER = "talentloop"
JWT_ACCESS_MINUTES = float(os.getenv("JWT_ACCESS_MINUTES", "60"))


def _jwt_key() -> bytes:
    env = os.getenv("JWT_SECRET", "").strip()
    if env:
        return hashlib.sha256(env.encode()).digest()
    from . import refs
    return hmac.new(refs.key(), b"jwt-signing-key", hashlib.sha256).digest()


def issue_tokens(s, req: Request, user: db.User, org_id: str | None) -> dict:
    """New session for an API client: a refresh token (opaque) and an access token (JWT)."""
    refresh = secrets.token_urlsafe(32)
    s.add(db.AuthSession(token_hash=token_hash(refresh), user_id=user.id, org_id=org_id, expires_at=time.time() + SESSION_DAYS * 86400,
                         ip=client_ip(req)[:64], ua=("api: " + req.headers.get("user-agent", ""))[:300]))
    user.last_login_at = time.time()
    user.login_count = (user.login_count or 0) + 1
    return {**access_token(user.id, token_hash(refresh)), "refresh_token": refresh}


def access_token(user_id: str, sid: str) -> dict:
    import jwt
    t = int(time.time())
    exp = t + int(JWT_ACCESS_MINUTES * 60)
    tok = jwt.encode({"iss": JWT_ISSUER, "sub": user_id, "sid": sid, "typ": "access", "iat": t, "nbf": t, "exp": exp}, _jwt_key(), algorithm="HS256")
    return {"access_token": tok, "token_type": "bearer", "expires_in": exp - t}


def _bearer_claims(req: Request) -> dict | None:
    h = req.headers.get("authorization") or ""
    if not h.lower().startswith("bearer "):
        return None
    import jwt
    try:
        c = jwt.decode(h[7:].strip(), _jwt_key(), algorithms=["HS256"], issuer=JWT_ISSUER, options={"require": ["exp", "iat", "sub", "sid"]})
    except jwt.PyJWTError:
        raise HTTPException(401, "Your access token is not valid or has expired. Get a new one from /api/auth/token or /api/auth/token/refresh.")
    if c.get("typ") != "access":
        raise HTTPException(401, "Not an access token.")
    return c


# ---------------------------------------------------------------------------
# email confirmation: until confirmed, a signed-in account can only reach these
# ---------------------------------------------------------------------------
VERIFY_OPEN = {"/api/auth/me", "/api/auth/logout", "/api/auth/verify", "/api/auth/verify/resend", "/api/health"}


def verification_required() -> bool:
    from . import appenv
    return not appenv.allowed_in_dev("SKIP_EMAIL_VERIFICATION")


@dataclass
class Ctx:
    user: db.User | None
    org: db.Org | None
    role: str | None          # role in `org`
    platform_admin: bool
    via_key: bool = False
    sid: str | None = None    # the AuthSession row (token hash) behind this request: cookie or JWT

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


# ---------------------------------------------------------------------------
# "last seen" for platform analytics: at most one small write per session per minute, off the request path
# ---------------------------------------------------------------------------
_SEEN: dict[str, float] = {}
_DAYS: set[tuple[str, str]] = set()
SEEN_POOL = __import__("concurrent.futures", fromlist=["ThreadPoolExecutor"]).ThreadPoolExecutor(max_workers=1, thread_name_prefix="seen")


def local_day(ts: float) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.fromtimestamp(ts, ZoneInfo(os.getenv("REPORT_TZ") or "Asia/Kolkata")).strftime("%Y-%m-%d")


def _touch(tok_hash: str, user_id: str, org_id: str | None) -> None:
    t = time.time()
    if t - _SEEN.get(tok_hash, 0) < 60:
        return
    _SEEN[tok_hash] = t
    if len(_SEEN) > 20000:
        _SEEN.clear()
    day = local_day(t)
    new_day = (user_id, day) not in _DAYS
    _DAYS.add((user_id, day))
    if len(_DAYS) > 50000:
        _DAYS.clear()

    def write():
        try:
            with db.session() as s:
                s.query(db.AuthSession).filter_by(token_hash=tok_hash).update({"last_seen_at": t})
                if new_day and not s.get(db.UserDay, (day, user_id)):
                    s.add(db.UserDay(day=day, user_id=user_id, org_id=org_id))
        except Exception as e:                       # a lost "seen" mark must never break a request
            log.debug("last-seen write skipped: %s", e)
    SEEN_POOL.submit(write)


def current(req: Request, s, required: bool = True) -> Ctx | None:
    """Who is calling. Raises 401 when required and nobody is signed in."""
    if _key_ok(req):
        return Ctx(user=None, org=None, role="owner", platform_admin=True, via_key=True)
    claims = _bearer_claims(req)
    tok = req.cookies.get(COOKIE)
    sid = claims["sid"] if claims else (token_hash(tok) if tok else None)
    if sid:
        # One round trip: session + user + the membership/company the session points at.
        row = s.query(db.AuthSession, db.User, db.Membership, db.Org) \
            .join(db.User, db.User.id == db.AuthSession.user_id) \
            .outerjoin(db.Membership, and_(db.Membership.user_id == db.User.id, db.Membership.org_id == db.AuthSession.org_id)) \
            .outerjoin(db.Org, db.Org.id == db.Membership.org_id) \
            .filter(db.AuthSession.token_hash == sid).first()
        if row:
            sess, user, mem, org = row
            if claims and claims["sub"] != user.id:
                row = None
            elif sess.expires_at > time.time() and not user.disabled:
                if user.email_verified_at is None and verification_required() and req.url.path not in VERIFY_OPEN:
                    if required:
                        raise HTTPException(403, "Confirm your email first: enter the code we emailed you.")
                    return None
                if mem is None or not mem.active:      # session's company gone or access paused: fall back to another
                    alt = s.query(db.Membership, db.Org).join(db.Org, db.Org.id == db.Membership.org_id) \
                        .filter(db.Membership.user_id == user.id, db.Membership.active.isnot(False)).order_by(db.Membership.created_at).first()
                    mem, org = alt if alt else (None, None)
                    sess.org_id = mem.org_id if mem else None
                if org and org.disabled and not user.is_platform_admin:
                    raise HTTPException(403, "This company account is disabled. Contact support.")
                _touch(sess.token_hash, user.id, org.id if org and mem else None)
                return Ctx(user=user, org=org if mem else None, role=mem.role if mem else None, platform_admin=bool(user.is_platform_admin),
                           sid=sess.token_hash)
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
