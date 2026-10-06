"""Sign-up, sign-in, team and invites, company settings, and the platform admin console."""
import os
import time

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from sqlalchemy import func

from . import auth, db, store
from .offload import offload

router = APIRouter()
INVITE_DAYS = 14

DEFAULT_SETTINGS = {
    "about": "", "website": "", "industry": "", "size": "", "country": "", "timezone": "Asia/Kolkata",
    "logo_url": "", "brand_color": "#2848e6", "careers_enabled": True, "careers_headline": "",
    "default_currency": "INR", "eeo_statement": "",
    "match_top_n": 5, "ai_reports_per_run": 25,
    # the AI match report may look at the candidate's own links and public professional pages (GitHub, their site, a web search)
    "public_lookup": True,
    # A candidate's "best-fit jobs" list only shows open jobs they score at least this on (0-100) and are not screened out of
    "best_fit_min_score": 55,
    "match_weights": {"skills": 45, "experience": 20, "relevance": 20, "location": 10, "logistics": 5},
    "interview_defaults": {"max_warnings": 2, "enforce_focus": True, "block_multi_monitor": True, "require_screen_share": False,
                           "duration_min": 15},
    "retention_days": 0,
    # Proposal: mandatory details candidates can't skip (careers form and campus registration)
    "application_fields": {"phone": True, "location": True, "expected_salary": True, "notice_days": True, "total_experience_years": False,
                           "current_company": False, "linkedin": False, "resume": True},
    # HR-approved answers the AI interviewer may give when a candidate asks about the company (nothing else)
    "faq": [],
    # The benefits this company offers (picked per job in the JD editor). Each company builds its own list.
    "benefits": [],
    # Columns for the HROne employee import export: header in HROne's template -> TalentLoop field
    "hrone_columns": [],
    # Delete recordings, snapshots and uploads of closed candidates (rejected, withdrawn, hired) after this many days; 0 = keep
    "recording_retention_days": 0,
    "sender_name": "",
}


def org_settings(org: db.Org) -> dict:
    s = dict(DEFAULT_SETTINGS)
    s.update(org.settings or {})
    s["match_weights"] = {**DEFAULT_SETTINGS["match_weights"], **((org.settings or {}).get("match_weights") or {})}
    s["interview_defaults"] = {**DEFAULT_SETTINGS["interview_defaults"], **((org.settings or {}).get("interview_defaults") or {})}
    s["application_fields"] = {**DEFAULT_SETTINGS["application_fields"], **((org.settings or {}).get("application_fields") or {})}
    return s


def log_activity(s, ctx: auth.Ctx | None, action: str, detail: str = "", org_id: str | None = None,
                 job_id: str | None = None, candidate_id: str | None = None) -> None:
    s.add(db.Activity(org_id=org_id or (ctx.org_id if ctx else None), user_id=ctx.user_id if ctx else None, action=action,
                      detail=detail[:2000], job_id=job_id, candidate_id=candidate_id))


def unique_slug(s, base: str, skip_org: str | None = None) -> str:
    slug, n = auth.slugify(base), 1
    while True:
        cand = slug if n == 1 else f"{slug}-{n}"
        hit = s.query(db.Org).filter_by(slug=cand).first()
        if not hit or hit.id == skip_org:
            return cand
        n += 1


def me_payload(s, ctx: auth.Ctx) -> dict:
    u = ctx.user
    mems = []
    if u:
        for m, o in s.query(db.Membership, db.Org).join(db.Org, db.Org.id == db.Membership.org_id) \
                .filter(db.Membership.user_id == u.id, db.Membership.active.isnot(False)):
            mems.append({"org_id": o.id, "name": o.name, "slug": o.slug, "role": m.role, "role_label": auth.ROLE_LABEL.get(m.role, m.role),
                         "title": m.title or "", "joined_at": m.created_at})
    org = ctx.org
    return {
        "user": {"id": u.id, "email": u.email, "name": u.name} if u else {"id": None, "email": "api-key", "name": "API key"},
        "email_verified": (u.email_verified_at is not None or not auth.verification_required()) if u else True,
        "org": {"id": org.id, "name": org.name, "slug": org.slug, "settings": org_settings(org)} if org else None,
        "role": ctx.role, "role_label": auth.ROLE_LABEL.get(ctx.role or "", ""), "platform_admin": ctx.platform_admin,
        "memberships": mems,
        "can": {"manage_team": ctx.has(auth.MANAGE_TEAM), "manage_jobs": ctx.has(auth.MANAGE_JOBS), "see_all": ctx.has(auth.SEE_ALL) or ctx.has(auth.MANAGE_JOBS)},
    }


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------
@router.post("/api/auth/signup")
@offload
async def signup(req: Request, resp: Response):
    body = await req.json()
    auth.rate_limit(f"signup:{auth.client_ip(req)}", 8, 3600)
    email = auth.norm_email(body.get("email"))
    pw = str(body.get("password") or "")
    auth.validate_password(pw)
    name = str(body.get("name") or "").strip()[:200]
    company = str(body.get("company") or "").strip()[:200]
    if not name or not company:
        raise HTTPException(400, "Your name and your company name are required.")
    from .api_console import platform_settings
    if not platform_settings()["signups_open"] and email not in auth.PLATFORM_ADMINS:
        raise HTTPException(403, "New sign-ups are paused right now. Ask the TalentLoop team for an invite.")
    with db.session() as s:
        old = s.query(db.User).filter_by(email=email).first()
        if old and old.email_verified_at is None and not old.disabled:
            _drop_unconfirmed(s, old)          # someone signed up with this address and never confirmed it: the owner of the inbox wins
        elif old:
            raise HTTPException(409, "An account with this email already exists. Sign in instead.")
        user = db.User(email=email, name=name, password_hash=auth.hash_password(pw), is_platform_admin=email in auth.PLATFORM_ADMINS,
                       email_verified_at=None if auth.verification_required() else time.time())
        settings = {k: str(body.get(k) or "")[:200] for k in ("website", "industry", "size", "country") if body.get(k)}
        org = db.Org(name=company, slug=unique_slug(s, company), settings=settings)
        s.add_all([user, org]); s.flush()
        s.add(db.Membership(user_id=user.id, org_id=org.id, role="owner", title=str(body.get("title") or "")[:120]))
        auth.start_session(s, resp, req, user, org.id)
        log_activity(s, None, "company_created", f"{company} by {email}", org_id=org.id)
        s.flush()
        if user.email_verified_at is None:
            _send_verify_code(s, user, org.id)
        return me_payload(s, auth.Ctx(user=user, org=org, role="owner", platform_admin=user.is_platform_admin))


@router.post("/api/auth/login")
@offload
async def login(req: Request, resp: Response):
    body = await req.json()
    email = (str(body.get("email") or "")).strip().lower()
    auth.rate_limit(f"login:{auth.client_ip(req)}", 20, 600)
    auth.rate_limit(f"login:{email}", 10, 600)
    with db.session() as s:
        user = s.query(db.User).filter_by(email=email).first()
        if not user or not auth.check_password(str(body.get("password") or ""), user.password_hash):
            raise HTTPException(401, "Wrong email or password.")
        if user.disabled:
            raise HTTPException(403, "This account is disabled. Contact support.")
        if email in auth.PLATFORM_ADMINS and not user.is_platform_admin:
            user.is_platform_admin = True
        mem = s.query(db.Membership).filter(db.Membership.user_id == user.id, db.Membership.active.isnot(False)) \
            .order_by(db.Membership.created_at).first()
        if not mem and not user.is_platform_admin and s.query(db.Membership).filter_by(user_id=user.id).first():
            raise HTTPException(403, "Your access has been paused by your company admin.")
        auth.start_session(s, resp, req, user, mem.org_id if mem else None)
        s.flush()
        return me_payload(s, auth.current(req, s, required=False) or auth.Ctx(user=user, org=s.get(db.Org, mem.org_id) if mem else None,
                                                                            role=mem.role if mem else None, platform_admin=user.is_platform_admin))


@router.post("/api/auth/logout")
def logout(req: Request, resp: Response):
    with db.session() as s:
        auth.end_session(s, req, resp)
    return {"ok": True}


@router.get("/api/auth/me")
def me(req: Request):
    with db.session() as s:
        ctx = auth.current(req, s)
        return me_payload(s, ctx)


@router.post("/api/auth/switch-org")
@offload
async def switch_org(req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = auth.current(req, s)
        if not ctx.user:
            raise HTTPException(400, "Not available for API keys")
        mem = s.query(db.Membership).filter_by(user_id=ctx.user.id, org_id=str(body.get("org_id"))).first()
        if not mem or mem.active is False:
            raise HTTPException(404, "You are not a member of that company")
        sess = s.get(db.AuthSession, ctx.sid) if ctx.sid else None
        if not sess:
            raise HTTPException(400, "No session to switch")
        sess.org_id = mem.org_id
    return {"ok": True}


@router.post("/api/auth/password")
@offload
async def change_password(req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = auth.current(req, s)
        if not ctx.user or not auth.check_password(str(body.get("current") or ""), ctx.user.password_hash):
            raise HTTPException(400, "Your current password is not correct.")
        auth.validate_password(str(body.get("new") or ""))
        ctx.user.password_hash = auth.hash_password(str(body["new"]))
        # sign out everywhere else
        keep = ctx.sid or ""
        s.query(db.AuthSession).filter(db.AuthSession.user_id == ctx.user.id, db.AuthSession.token_hash != keep).delete()
    return {"ok": True}


@router.patch("/api/auth/profile")
@offload
async def update_profile(req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = auth.current(req, s)
        if not ctx.user:
            raise HTTPException(400, "Not available for API keys")
        if body.get("name"):
            ctx.user.name = str(body["name"]).strip()[:200]
        return me_payload(s, ctx)


# ---------------------------------------------------------------------------
# invites
# ---------------------------------------------------------------------------
@router.get("/api/invites/{token}")
def invite_info(token: str):
    with db.session() as s:
        inv = s.query(db.Invite).filter_by(token_hash=auth.token_hash(token)).first()
        if not inv or inv.accepted_at or inv.expires_at < time.time():
            raise HTTPException(404, "This invite link is not valid or has expired. Ask your admin for a new one.")
        org = s.get(db.Org, inv.org_id)
        exists = bool(s.query(db.User).filter_by(email=inv.email).first())
        return {"org": org.name, "email": inv.email, "role": inv.role, "role_label": auth.ROLE_LABEL.get(inv.role, inv.role),
                "title": inv.title, "has_account": exists}


@router.post("/api/invites/{token}/accept")
@offload
async def accept_invite(token: str, req: Request, resp: Response):
    body = await req.json()
    auth.rate_limit(f"invite:{auth.client_ip(req)}", 20, 3600)
    with db.session() as s:
        inv = s.query(db.Invite).filter_by(token_hash=auth.token_hash(token)).first()
        if not inv or inv.accepted_at or inv.expires_at < time.time():
            raise HTTPException(404, "This invite link is not valid or has expired.")
        user = s.query(db.User).filter_by(email=inv.email).first()
        if user:
            if not auth.check_password(str(body.get("password") or ""), user.password_hash):
                raise HTTPException(401, "Enter the password of your existing account.")
        else:
            auth.validate_password(str(body.get("password") or ""))
            user = db.User(email=inv.email, name=str(body.get("name") or inv.email.split("@")[0])[:200],
                           password_hash=auth.hash_password(str(body["password"])), is_platform_admin=inv.email in auth.PLATFORM_ADMINS)
            s.add(user); s.flush()
        if user.email_verified_at is None:
            user.email_verified_at = time.time()      # the invite link was emailed to this address
        if not s.query(db.Membership).filter_by(user_id=user.id, org_id=inv.org_id).first():
            s.add(db.Membership(user_id=user.id, org_id=inv.org_id, role=inv.role, title=inv.title))
        inv.accepted_at = time.time()
        auth.start_session(s, resp, req, user, inv.org_id)
        log_activity(s, None, "member_joined", f"{user.email} as {auth.ROLE_LABEL.get(inv.role, inv.role)}", org_id=inv.org_id)
        s.flush()
        org = s.get(db.Org, inv.org_id)
        return me_payload(s, auth.Ctx(user=user, org=org, role=inv.role, platform_admin=user.is_platform_admin))


# ---------------------------------------------------------------------------
# team
# ---------------------------------------------------------------------------
@router.get("/api/team")
def team(req: Request):
    with db.session() as s:
        ctx = auth.current(req, s)
        org_id = auth.require_org(ctx)
        members = [{"id": m.id, "user_id": u.id, "name": u.name, "email": u.email, "role": m.role, "role_label": auth.ROLE_LABEL.get(m.role, m.role),
                    "title": m.title, "last_login_at": u.last_login_at, "joined_at": m.created_at, "you": u.id == ctx.user_id,
                    "active": m.active is not False}
                   for m, u in s.query(db.Membership, db.User).join(db.User, db.User.id == db.Membership.user_id)
                   .filter(db.Membership.org_id == org_id).order_by(db.Membership.created_at)]
        invites = []
        if ctx.has(auth.MANAGE_TEAM):
            invites = [{"id": i.id, "email": i.email, "role": i.role, "role_label": auth.ROLE_LABEL.get(i.role, i.role), "title": i.title,
                        "created_at": i.created_at, "expires_at": i.expires_at, "expired": i.expires_at < time.time()}
                       for i in s.query(db.Invite).filter(db.Invite.org_id == org_id, db.Invite.accepted_at.is_(None))
                       .order_by(db.Invite.created_at.desc())]
        return {"members": members, "invites": invites, "roles": [{"id": r, "label": auth.ROLE_LABEL[r]} for r in auth.ROLES]}


@router.post("/api/team/invites")
@offload
async def create_invite(req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = auth.current(req, s)
        auth.require(ctx, auth.MANAGE_TEAM, "invite people")
        org_id = auth.require_org(ctx)
        email = auth.norm_email(body.get("email"))
        role = str(body.get("role") or "recruiter")
        if role not in auth.ROLES:
            raise HTTPException(400, "Unknown role")
        if role == "owner" and ctx.role != "owner" and not ctx.via_key:
            raise HTTPException(403, "Only an owner can invite another owner.")
        u = s.query(db.User).filter_by(email=email).first()
        if u and s.query(db.Membership).filter_by(user_id=u.id, org_id=org_id).first():
            raise HTTPException(409, "This person is already on your team.")
        tok = auth.secrets.token_urlsafe(24)
        inv = db.Invite(org_id=org_id, email=email, role=role, title=str(body.get("title") or "")[:120], token_hash=auth.token_hash(tok),
                        created_by=ctx.user_id, expires_at=time.time() + INVITE_DAYS * 86400)
        s.add(inv)
        log_activity(s, ctx, "member_invited", f"{email} as {auth.ROLE_LABEL[role]}")
        return {"id": inv.id, "path": f"/invite/{tok}", "email": email, "expires_days": INVITE_DAYS}


@router.post("/api/team/invites/{inv_id}/renew")
def renew_invite(inv_id: str, req: Request):
    """A fresh link for a pending invite (the old link stops working) with a new INVITE_DAYS expiry."""
    with db.session() as s:
        ctx = auth.current(req, s)
        auth.require(ctx, auth.MANAGE_TEAM, "manage invites")
        inv = s.query(db.Invite).filter_by(id=inv_id, org_id=auth.require_org(ctx)).first()
        if not inv or inv.accepted_at:
            raise HTTPException(404, "Invite not found")
        tok = auth.secrets.token_urlsafe(24)
        inv.token_hash, inv.expires_at = auth.token_hash(tok), time.time() + INVITE_DAYS * 86400
        log_activity(s, ctx, "member_invited", f"{inv.email}: new invite link")
        return {"id": inv.id, "path": f"/invite/{tok}", "email": inv.email, "expires_days": INVITE_DAYS}


@router.delete("/api/team/invites/{inv_id}")
def revoke_invite(inv_id: str, req: Request):
    with db.session() as s:
        ctx = auth.current(req, s)
        auth.require(ctx, auth.MANAGE_TEAM, "manage invites")
        s.query(db.Invite).filter_by(id=inv_id, org_id=auth.require_org(ctx)).delete()
    return {"ok": True}


def _owners_left(s, org_id: str, excluding: str) -> int:
    return s.query(db.Membership).filter(db.Membership.org_id == org_id, db.Membership.role == "owner", db.Membership.id != excluding,
                                         db.Membership.active.isnot(False)).count()


@router.patch("/api/team/members/{mid}")
@offload
async def update_member(mid: str, req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = auth.current(req, s)
        auth.require(ctx, auth.MANAGE_TEAM, "change roles")
        m = s.query(db.Membership).filter_by(id=mid, org_id=auth.require_org(ctx)).first()
        if not m:
            raise HTTPException(404, "Member not found")
        role = body.get("role")
        if role:
            if role not in auth.ROLES:
                raise HTTPException(400, "Unknown role")
            if (role == "owner" or m.role == "owner") and ctx.role != "owner" and not ctx.via_key:
                raise HTTPException(403, "Only an owner can change owner roles.")
            if m.role == "owner" and role != "owner" and not _owners_left(s, m.org_id, m.id):
                raise HTTPException(400, "A company needs at least one owner.")
            m.role = role
        if "title" in body:
            m.title = str(body["title"] or "")[:120]
        u = s.get(db.User, m.user_id)
        who = (u.name or u.email) if u else m.user_id
        if "active" in body and bool(body["active"]) != (m.active is not False):
            if m.user_id == ctx.user_id:
                raise HTTPException(400, "You can't pause your own access.")
            if not body["active"] and m.role == "owner" and not _owners_left(s, m.org_id, m.id):
                raise HTTPException(400, "A company needs at least one active owner.")
            m.active = bool(body["active"])
            if not m.active:                       # sign them out of this company now
                s.query(db.AuthSession).filter_by(user_id=m.user_id, org_id=m.org_id).delete()
            log_activity(s, ctx, "member_updated", f"{who}: access {'resumed' if m.active else 'paused'}")
        else:
            log_activity(s, ctx, "member_updated", f"{who}: {auth.ROLE_LABEL.get(m.role, m.role)}" + (f", {m.title}" if m.title else ""))
    return {"ok": True}


@router.delete("/api/team/members/{mid}")
def remove_member(mid: str, req: Request):
    with db.session() as s:
        ctx = auth.current(req, s)
        auth.require(ctx, auth.MANAGE_TEAM, "remove people")
        m = s.query(db.Membership).filter_by(id=mid, org_id=auth.require_org(ctx)).first()
        if not m:
            raise HTTPException(404, "Member not found")
        if m.role == "owner" and not _owners_left(s, m.org_id, m.id):
            raise HTTPException(400, "A company needs at least one owner.")
        s.query(db.JobCollaborator).filter(db.JobCollaborator.user_id == m.user_id,
                                           db.JobCollaborator.job_id.in_(s.query(db.Job.id).filter(db.Job.org_id == m.org_id))).delete(synchronize_session=False)
        if m.user_id == ctx.user_id:
            raise HTTPException(400, "You can't remove yourself. Ask another owner or admin.")
        u = s.get(db.User, m.user_id)
        s.query(db.AuthSession).filter_by(user_id=m.user_id, org_id=m.org_id).delete()
        # their open interview slots can't be booked any more (booked ones stay for HR to reassign)
        s.query(db.Slot).filter(db.Slot.org_id == m.org_id, db.Slot.interviewer_id == m.user_id, db.Slot.booked_by.is_(None)).delete(synchronize_session=False)
        s.delete(m)
        log_activity(s, ctx, "member_removed", (u.name or u.email) if u else m.user_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# company settings
# ---------------------------------------------------------------------------
def clean_benefits(v) -> list[str]:
    out = []
    for x in v or []:
        x = " ".join(str(x).split())[:80]
        if x and x.lower() not in {y.lower() for y in out}:
            out.append(x)
    return out[:60]


@router.post("/api/org/benefits")
@offload
async def org_benefits(req: Request):
    """HR adds a benefit to the company's list (from the JD editor) or removes one. Jobs keep what they already list."""
    body = await req.json()
    with db.session() as s:
        ctx = auth.current(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "change the company's benefits")
        org = s.get(db.Org, auth.require_org(ctx))
        cur = list((org.settings or {}).get("benefits") or [])
        add, remove = " ".join(str(body.get("add") or "").split())[:80], str(body.get("remove") or "").strip().lower()
        if add:
            cur.append(add)
        if remove:
            cur = [x for x in cur if x.lower() != remove]
        cur = clean_benefits(cur)
        org.settings = {**(org.settings or {}), "benefits": cur}
        log_activity(s, ctx, "settings_updated", f"Benefits: {'added ' + add if add else 'removed ' + remove}")
        return {"benefits": cur}


@router.get("/api/org")
def get_org(req: Request):
    with db.session() as s:
        ctx = auth.current(req, s)
        auth.require_org(ctx)
        samples = s.query(db.Candidate.id).filter_by(org_id=ctx.org.id, source="demo").first() is not None \
            or any((f or {}).get("_sample") for (f,) in s.query(db.Job.fields).filter_by(org_id=ctx.org.id))
        return {"id": ctx.org.id, "name": ctx.org.name, "slug": ctx.org.slug, "settings": org_settings(ctx.org), "created_at": ctx.org.created_at,
                "has_sample_data": samples}


@router.patch("/api/org")
@offload
async def update_org(req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = auth.current(req, s)
        auth.require(ctx, auth.MANAGE_TEAM, "change company settings")
        org = s.get(db.Org, auth.require_org(ctx))
        if body.get("name"):
            org.name = str(body["name"]).strip()[:200]
        if body.get("slug"):
            org.slug = unique_slug(s, str(body["slug"]), skip_org=org.id)
        incoming = body.get("settings") or {}
        cur = dict(org.settings or {})
        for k, v in incoming.items():
            if k not in DEFAULT_SETTINGS:
                continue
            if k == "match_top_n":
                v = max(1, min(50, int(v or 5)))
            if k == "best_fit_min_score":
                v = max(0, min(100, int(v or 0)))
            if k == "public_lookup":
                v = bool(v)
            if k == "ai_reports_per_run":
                v = max(0, min(500, int(v or 0)))
            if k in ("retention_days", "recording_retention_days"):
                v = max(0, min(3650, int(v or 0)))
            if k == "faq":
                v = [{"q": str(x.get("q") or "").strip()[:300], "a": str(x.get("a") or "").strip()[:1500]} for x in (v or [])
                     if isinstance(x, dict) and str(x.get("q") or "").strip() and str(x.get("a") or "").strip()][:40]
            if k == "benefits":
                v = clean_benefits(v)
            if k == "hrone_columns":
                v = [{"header": str(x.get("header") or "").strip()[:80], "field": str(x.get("field") or "").strip()[:40]} for x in (v or [])
                     if isinstance(x, dict) and str(x.get("header") or "").strip()][:80]
            if k == "application_fields":
                v = {str(f): bool(r) for f, r in (v or {}).items() if f in DEFAULT_SETTINGS["application_fields"]}
            if k == "timezone":
                from zoneinfo import ZoneInfo
                try:
                    ZoneInfo(str(v))
                except Exception:
                    raise HTTPException(400, "Unknown time zone. Pick one from the list.") from None
            cur[k] = v
        org.settings = cur
        log_activity(s, ctx, "settings_updated", ", ".join(sorted(incoming))[:300])
        return {"id": org.id, "name": org.name, "slug": org.slug, "settings": org_settings(org)}


# ---------------------------------------------------------------------------
# platform admin console
# ---------------------------------------------------------------------------
def _admin(req: Request, s) -> auth.Ctx:
    ctx = auth.current(req, s)
    if not ctx.platform_admin:
        raise HTTPException(403, "Platform admins only.")
    return ctx


def _interview_counts() -> dict[str | None, int]:
    with db.session() as s:
        return dict(s.query(db.InterviewIndex.org_id, func.count()).group_by(db.InterviewIndex.org_id).all())


@router.get("/api/admin/overview")
def admin_overview(req: Request):
    with db.session() as s:
        _admin(req, s)
        t = time.time()
        day = lambda ts: int((t - ts) // 86400)  # noqa: E731
        signups = [0] * 30
        for (ts,) in s.query(db.User.created_at).filter(db.User.created_at > t - 30 * 86400):
            signups[29 - day(ts)] += 1
        ints = _interview_counts()
        return {
            "orgs": s.query(db.Org).count(), "users": s.query(db.User).count(),
            "active_users_7d": s.query(db.User).filter(db.User.last_login_at > t - 7 * 86400).count(),
            "jobs": s.query(db.Job).count(), "open_jobs": s.query(db.Job).filter_by(status="open").count(),
            "candidates": s.query(db.Candidate).count(), "applications": s.query(db.Application).count(),
            "interviews": sum(ints.values()), "ai_calls": s.query(db.AIUsage).count(),
            "ai_calls_30d": s.query(db.AIUsage).filter(db.AIUsage.at > t - 30 * 86400).count(),
            "signups_30d": signups,
            "storage": {"s3": store.S3_ENABLED, "database": "sqlite" if db.IS_SQLITE else "postgres"},
        }


_analytics_cache: dict[int, tuple[float, dict]] = {}


@router.get("/api/admin/analytics")
def admin_analytics(req: Request, days: int = 30):
    """Platform-wide numbers and daily series for the platform admin. Days are in REPORT_TZ (default India time).
    About 26 queries, so the result is reused for 60 seconds (the page refreshes every minute anyway)."""
    days = days if days in (7, 30, 90) else 30
    with db.session() as s:
        _admin(req, s)
    hit = _analytics_cache.get(days)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    out = _analytics(days)
    _analytics_cache[days] = (time.time(), out)
    return out


def _analytics(days: int) -> dict:
    from datetime import date, timedelta
    with db.session() as s:
        t = time.time()
        today = date.fromisoformat(auth.local_day(t))
        labels = [(today - timedelta(days=days - 1 - i)).isoformat() for i in range(days)]
        idx = {d: i for i, d in enumerate(labels)}
        since = t - (days + 1) * 86400

        def series(col, *where):
            out = [0] * days
            for (ts,) in s.query(col).filter(col > since, *where):
                i = idx.get(auth.local_day(ts))
                if i is not None:
                    out[i] += 1
            return out
        active = [0] * days
        for d, n in s.query(db.UserDay.day, func.count()).filter(db.UserDay.day >= labels[0]).group_by(db.UserDay.day):
            if d in idx:
                active[idx[d]] = n
        active_orgs = [0] * days
        for d, n in s.query(db.UserDay.day, func.count(func.distinct(db.UserDay.org_id))).filter(db.UserDay.day >= labels[0], db.UserDay.org_id.isnot(None)).group_by(db.UserDay.day):
            if d in idx:
                active_orgs[idx[d]] = n

        def distinct_users(n_days):
            first = (today - timedelta(days=n_days - 1)).isoformat()
            return s.query(func.count(func.distinct(db.UserDay.user_id))).filter(db.UserDay.day >= first).scalar() or 0
        online = s.query(db.AuthSession, db.User).join(db.User, db.User.id == db.AuthSession.user_id) \
            .filter(db.AuthSession.last_seen_at > t - 300, db.AuthSession.expires_at > t).order_by(db.AuthSession.last_seen_at.desc()).all()
        org_names = dict(s.query(db.Org.id, db.Org.name).all())
        seen, people = set(), []
        for sess, u in online:
            if u.id in seen:
                continue
            seen.add(u.id)
            people.append({"id": u.id, "name": u.name, "email": u.email, "company": org_names.get(sess.org_id or "", ""), "last_seen_at": sess.last_seen_at,
                           "platform_admin": u.is_platform_admin})
        sample = db.Candidate.source == "demo"
        top = s.query(db.Candidate.org_id, func.count()).filter(db.Candidate.created_at > t - days * 86400, ~sample) \
            .group_by(db.Candidate.org_id).order_by(func.count().desc()).limit(8).all()
        busiest = s.query(db.UserDay.org_id, func.count()).filter(db.UserDay.day >= labels[0], db.UserDay.org_id.isnot(None)) \
            .group_by(db.UserDay.org_id).order_by(func.count().desc()).limit(8).all()
        stages = dict(s.query(db.Application.stage, func.count()).group_by(db.Application.stage).all())
        return {
            "days": labels, "tz": os.getenv("REPORT_TZ") or "Asia/Kolkata",
            "online_now": len(people), "online": people[:50],
            "active": {"today": active[-1], "d7": distinct_users(7), "d30": distinct_users(30)},
            "totals": {"companies": s.query(db.Org).count(), "companies_disabled": s.query(db.Org).filter_by(disabled=True).count(),
                       "users": s.query(db.User).count(), "resumes": s.query(db.Candidate).filter(~sample).count(),
                       "sample_resumes": s.query(db.Candidate).filter(sample).count(), "applications": s.query(db.Application).count(),
                       "jobs_open": s.query(db.Job).filter_by(status="open").count(), "interviews": s.query(db.InterviewIndex).count(),
                       "ai_calls": s.query(db.AIUsage).count()},
            "series": {"active_users": active, "active_companies": active_orgs, "signups": series(db.User.created_at),
                       "companies": series(db.Org.created_at), "resumes": series(db.Candidate.created_at, ~sample),
                       "applications": series(db.Application.created_at), "interviews": series(db.InterviewIndex.created_at),
                       "ai_calls": series(db.AIUsage.at)},
            "top_resumes": [{"company": org_names.get(o, "(deleted)"), "n": n} for o, n in top],
            "top_active": [{"company": org_names.get(o, "(deleted)"), "n": n} for o, n in busiest],
            "stages": stages,
            "tracking_since": s.query(func.min(db.UserDay.day)).scalar(),
        }


@router.get("/api/admin/orgs")
def admin_orgs(req: Request):
    with db.session() as s:
        _admin(req, s)
        def counts(model, col="org_id"):
            return dict(s.query(getattr(model, col), func.count()).group_by(getattr(model, col)).all())
        members, jobs, cands, apps, ai = counts(db.Membership), counts(db.Job), counts(db.Candidate), counts(db.Application), counts(db.AIUsage)
        open_jobs = dict(s.query(db.Job.org_id, func.count()).filter(db.Job.status == "open").group_by(db.Job.org_id).all())
        last = dict(s.query(db.Activity.org_id, func.max(db.Activity.at)).group_by(db.Activity.org_id).all())
        owners = {}
        for m, u in s.query(db.Membership, db.User).join(db.User, db.User.id == db.Membership.user_id).filter(db.Membership.role == "owner"):
            owners.setdefault(m.org_id, u.email)
        ints = _interview_counts()
        return [{"id": o.id, "name": o.name, "slug": o.slug, "created_at": o.created_at, "disabled": o.disabled, "owner": owners.get(o.id, ""),
                 "members": members.get(o.id, 0), "jobs": jobs.get(o.id, 0), "open_jobs": open_jobs.get(o.id, 0),
                 "candidates": cands.get(o.id, 0), "applications": apps.get(o.id, 0), "interviews": ints.get(o.id, 0),
                 "ai_calls": ai.get(o.id, 0), "last_activity": last.get(o.id)}
                for o in s.query(db.Org).order_by(db.Org.created_at.desc())]


@router.get("/api/admin/users")
def admin_users(req: Request):
    with db.session() as s:
        _admin(req, s)
        orgs = {o.id: o.name for o in s.query(db.Org)}
        mem: dict[str, list] = {}
        for m in s.query(db.Membership):
            mem.setdefault(m.user_id, []).append({"org": orgs.get(m.org_id, ""), "org_id": m.org_id, "role": m.role,
                                                  "role_label": auth.ROLE_LABEL.get(m.role, m.role)})
        return [{"id": u.id, "email": u.email, "name": u.name, "created_at": u.created_at, "last_login_at": u.last_login_at,
                 "login_count": u.login_count or 0, "disabled": u.disabled, "platform_admin": u.is_platform_admin, "memberships": mem.get(u.id, []),
                 "email_verified": u.email_verified_at is not None}
                for u in s.query(db.User).order_by(db.User.created_at.desc())]


@router.patch("/api/admin/orgs/{org_id}")
@offload
async def admin_update_org(org_id: str, req: Request):
    body = await req.json()
    with db.session() as s:
        _admin(req, s)
        o = s.get(db.Org, org_id)
        if not o:
            raise HTTPException(404, "Company not found")
        if "disabled" in body:
            o.disabled = bool(body["disabled"])
    return {"ok": True}


@router.patch("/api/admin/users/{user_id}")
@offload
async def admin_update_user(user_id: str, req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = _admin(req, s)
        u = s.get(db.User, user_id)
        if not u:
            raise HTTPException(404, "User not found")
        if "disabled" in body:
            if u.id == ctx.user_id:
                raise HTTPException(400, "You can't disable yourself.")
            u.disabled = bool(body["disabled"])
            if u.disabled:
                s.query(db.AuthSession).filter_by(user_id=u.id).delete()
        if body.get("email_verified") is True and u.email_verified_at is None:
            u.email_verified_at = time.time()
            log_activity(s, ctx, "settings_updated", f"Email of {u.email} marked as confirmed by a platform admin"[:300])
        if "platform_admin" in body and u.id != ctx.user_id:
            u.is_platform_admin = bool(body["platform_admin"])
    return {"ok": True}


def platform_status() -> dict:
    return {"database": "sqlite" if db.IS_SQLITE else "postgres", "persistent_db": not db.IS_SQLITE or os.getenv("PERSISTENT_DISK") == "1",
            "platform_admins_configured": bool(auth.PLATFORM_ADMINS)}


# ---------------------------------------------------------------------------
# company logo upload (careers page, candidate pages, emails)
# ---------------------------------------------------------------------------
@router.post("/api/org/logo")
async def upload_logo(req: Request, file: UploadFile = File(...)):
    """PNG, JPG or WebP up to 2 MB. Re-encoded to PNG (at most 512 px) so only a clean image is ever served; SVG is
    refused because an SVG can carry scripts."""
    raw = await file.read()
    if len(raw) > 2 * 1024 * 1024:
        raise HTTPException(413, "The logo must be under 2 MB.")
    import hashlib
    import io
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(raw))
        if im.format not in ("PNG", "JPEG", "WEBP"):
            raise ValueError
        im.thumbnail((512, 512))
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA")
        out = io.BytesIO()
        im.save(out, "PNG", optimize=True)
    except Exception:
        raise HTTPException(400, "Upload a PNG, JPG or WebP image.") from None
    data = out.getvalue()
    h = hashlib.sha1(data).hexdigest()[:12]
    with db.session() as s:
        ctx = auth.current(req, s)
        auth.require(ctx, auth.MANAGE_TEAM, "change company settings")
        org = s.get(db.Org, auth.require_org(ctx))
        store.put_file(f"{org.id}/branding/logo-{h}.png", data, "image/png")
        url = f"/api/public/logo/{org.id}/{h}.png"
        org.settings = {**(org.settings or {}), "logo_url": url}
        log_activity(s, ctx, "settings_updated", "logo uploaded")
    return {"logo_url": url}


@router.get("/api/public/logo/{org_id}/{name}")
def public_logo(org_id: str, name: str):
    import re
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", org_id) or not re.fullmatch(r"[0-9a-f]{12}\.png", name):
        raise HTTPException(404, "Not found")
    p = store.get_file(f"{org_id}/branding/logo-{name}")
    if not p:
        raise HTTPException(404, "Not found")
    from fastapi.responses import FileResponse
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "public, max-age=31536000, immutable",
                                                             "Content-Security-Policy": "default-src 'none'", "X-Content-Type-Options": "nosniff"})


# ---------------------------------------------------------------------------
# forgotten password: a 6-digit code by email (works once: it is tied to the current password)
# ---------------------------------------------------------------------------
def _reset_code(user: db.User, window: int) -> str:
    import hashlib
    import hmac
    from . import refs
    n = int.from_bytes(hmac.new(refs.key(), f"reset|{user.email}|{user.password_hash}|{window}".encode(), hashlib.sha256).digest()[:6], "big")
    return f"{n % 1_000_000:06d}"


@router.post("/api/auth/forgot")
@offload
async def forgot_password(req: Request):
    body = await req.json()
    email = str(body.get("email") or "").strip().lower()
    auth.rate_limit(f"forgot:{auth.client_ip(req)}", 10, 3600)
    auth.rate_limit(f"forgot:{email}", 4, 3600)
    from . import messages
    with db.session() as s:
        user = s.query(db.User).filter_by(email=email).first()
        if user and not user.disabled:                # same reply either way: no account discovery
            mem = s.query(db.Membership).filter_by(user_id=user.id).first()
            code = _reset_code(user, int(time.time() // 900))
            messages.queue(s, mem.org_id if mem else "", to_email=email, subject="Reset your TalentLoop password",
                           body=f"Your password reset code is {code}.\n\nIt works once, for about 15 minutes. If you didn't ask for it, ignore this email: "
                                "your password stays the same.", template="password_reset")
    return {"ok": True}


@router.post("/api/auth/reset")
@offload
async def reset_password(req: Request):
    body = await req.json()
    email = str(body.get("email") or "").strip().lower()
    code = "".join(ch for ch in str(body.get("code") or "") if ch.isdigit())
    pw = str(body.get("password") or "")
    auth.rate_limit(f"reset:{auth.client_ip(req)}", 20, 600)
    auth.rate_limit(f"reset:{email}", 8, 600)
    if len(pw) < 8:
        raise HTTPException(400, "Use at least 8 characters.")
    import hmac
    with db.session() as s:
        user = s.query(db.User).filter_by(email=email).first()
        w = int(time.time() // 900)
        if not user or len(code) != 6 or not any(hmac.compare_digest(code, _reset_code(user, x)) for x in (w, w - 1)):
            raise HTTPException(400, "That code isn't right or has expired. Ask for a new one.")
        user.password_hash = auth.hash_password(pw)
        if user.email_verified_at is None:
            user.email_verified_at = time.time()      # the code came to this inbox
        s.query(db.AuthSession).filter_by(user_id=user.id).delete()    # signed out everywhere
    return {"ok": True}


# ---------------------------------------------------------------------------
# email confirmation at sign-up: a 6-digit code (or the link in the same email), valid for 15-30 minutes
# ---------------------------------------------------------------------------
def _verify_code(user: db.User, window: int) -> str:
    import hashlib
    import hmac
    from . import refs
    n = int.from_bytes(hmac.new(refs.key(), f"verify|{user.id}|{user.email}|{window}".encode(), hashlib.sha256).digest()[:6], "big")
    return f"{n % 1_000_000:06d}"


def _send_verify_code(s, user: db.User, org_id: str | None) -> None:
    from . import messages
    from .flows import base_url as app_base
    code = _verify_code(user, int(time.time() // 900))
    link = f"{app_base()}/app?verify={code}" if app_base() else ""
    messages.queue(s, org_id or "", to_email=user.email, subject="Your TalentLoop confirmation code",   # never the code itself: subjects show in the outbox
                   body=f"Hi {user.name or 'there'},\n\nConfirm your email to start using TalentLoop. Your code is {code}."
                        + (f"\n\nOr open this link in the browser where you signed up:\n{link}" if link else "")
                        + "\n\nThe code works for about 15 minutes. If you didn't sign up, ignore this email: nothing happens without the code.",
                   template="email_verify")


def _drop_unconfirmed(s, user: db.User) -> None:
    """Remove an account that never confirmed its email, and any company only it belonged to (it could not have used it)."""
    for m in s.query(db.Membership).filter_by(user_id=user.id).all():
        others = s.query(db.Membership).filter(db.Membership.org_id == m.org_id, db.Membership.user_id != user.id).count()
        org_id = m.org_id
        s.delete(m)
        if not others:
            s.flush()
            for model in (db.Activity, db.Message):
                s.query(model).filter(model.org_id == org_id).delete(synchronize_session=False)
            s.query(db.Org).filter_by(id=org_id).delete(synchronize_session=False)
    s.query(db.AuthSession).filter_by(user_id=user.id).delete()
    s.query(db.UserDay).filter_by(user_id=user.id).delete()
    s.delete(user)
    s.flush()


@router.post("/api/auth/verify")
@offload
async def verify_email(req: Request):
    body = await req.json()
    import hmac
    with db.session() as s:
        ctx = auth.current(req, s)
        if not ctx.user:
            raise HTTPException(400, "Not available for API keys")
        user = ctx.user
        if user.email_verified_at is not None:
            return me_payload(s, ctx)
        auth.rate_limit(f"verify:{user.id}", 8, 900)
        code = "".join(ch for ch in str(body.get("code") or "") if ch.isdigit())
        w = int(time.time() // 900)
        if len(code) != 6 or not any(hmac.compare_digest(code, _verify_code(user, x)) for x in (w, w - 1)):
            raise HTTPException(400, "That code isn't right or has expired. Check the latest email, or send a new code.")
        user.email_verified_at = time.time()
        log_activity(s, ctx, "email_confirmed", user.email[:300]) if ctx.org else None
        return me_payload(s, ctx)


@router.post("/api/auth/verify/resend")
def resend_verify(req: Request):
    with db.session() as s:
        ctx = auth.current(req, s)
        if not ctx.user or ctx.user.email_verified_at is not None:
            return {"ok": True}
        auth.rate_limit(f"verify-send:{ctx.user.id}", 1, 45)
        auth.rate_limit(f"verify-send-h:{ctx.user.id}", 6, 3600)
        _send_verify_code(s, ctx.user, ctx.org_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# JWT for API clients and Swagger ("Authorize" on /docs)
# ---------------------------------------------------------------------------
async def _token_body(req: Request) -> dict:
    if (req.headers.get("content-type") or "").startswith("application/json"):
        return await req.json()
    return dict(await req.form())


@router.post("/api/auth/token", summary="Get a JWT access token",
             description="Email and password in, a JWT access token (send it as `Authorization: Bearer <token>`) and a refresh token out. "
                         "Accepts the OAuth2 password form that Swagger's Authorize button sends (`username` = your email), or JSON "
                         "`{\"email\", \"password\"}`. The account must have confirmed its email.")
@offload
async def token(req: Request):
    body = await _token_body(req)
    email = str(body.get("email") or body.get("username") or "").strip().lower()
    auth.rate_limit(f"login:{auth.client_ip(req)}", 20, 600)
    auth.rate_limit(f"login:{email}", 10, 600)
    with db.session() as s:
        user = s.query(db.User).filter_by(email=email).first()
        if not user or not auth.check_password(str(body.get("password") or ""), user.password_hash):
            raise HTTPException(401, "Wrong email or password.")
        if user.disabled:
            raise HTTPException(403, "This account is disabled. Contact support.")
        if user.email_verified_at is None and auth.verification_required():
            raise HTTPException(403, "Confirm your email first: sign in on the website and enter the code we emailed you.")
        if email in auth.PLATFORM_ADMINS and not user.is_platform_admin:
            user.is_platform_admin = True
        mem = s.query(db.Membership).filter(db.Membership.user_id == user.id, db.Membership.active.isnot(False)) \
            .order_by(db.Membership.created_at).first()
        if not mem and not user.is_platform_admin and s.query(db.Membership).filter_by(user_id=user.id).first():
            raise HTTPException(403, "Your access has been paused by your company admin.")
        return auth.issue_tokens(s, req, user, mem.org_id if mem else None)


@router.post("/api/auth/token/refresh", summary="Get a new access token",
             description="Send `{\"refresh_token\"}` from /api/auth/token. Returns a fresh access token while the session is valid. "
                         "Signing out, a password reset or a disabled account end the session and every token made from it.")
async def token_refresh(req: Request):
    body = await _token_body(req)
    rt = str(body.get("refresh_token") or "")
    with db.session() as s:
        sess = s.get(db.AuthSession, auth.token_hash(rt)) if rt else None
        user = s.get(db.User, sess.user_id) if sess else None
        if not sess or sess.expires_at < time.time() or not user or user.disabled:
            raise HTTPException(401, "This refresh token is not valid or has expired. Get a new one from /api/auth/token.")
        return {**auth.access_token(user.id, sess.token_hash), "refresh_token": rt}


# ---------------------------------------------------------------------------
# AI models (platform admin): provider and models per role, switchable without a restart
# ---------------------------------------------------------------------------
_model_cache: dict[str, tuple[float, list]] = {}


def _llm_state() -> dict:
    from . import llm
    from . import research
    return {"research": {"search": research.search_provider() or None, "github_token": bool(os.getenv("GITHUB_TOKEN")), "people_data": bool(os.getenv("PEOPLE_DATA_API_KEY"))},
            "providers": [{"id": k, "label": p["label"], "available": llm.available(k), "env": p["env"], "note": p["note"], "site": p["site"],
                           "base_url": p["base_url"]} for k, p in llm.PROVIDERS.items() if k != "custom" or p["base_url"]],
            "config": llm.CONFIG, "source": llm.SOURCE, "suggest": llm.SUGGEST, "note": llm.MODEL_CHECK.get("note", ""), "mock": llm.MOCK,
            "backup": {"on": llm.backups_on(), "targets": [{"provider": llm.PROVIDERS[p]["label"], "model": m} for p, m in llm._backup_targets(llm.FAST_MODEL)],
                       "last": llm.LAST_BACKUP or None, "blocked": {llm.PROVIDERS[k]["label"]: v[1] for k, v in llm._BLOCKED.items() if v[0] > time.time()}}}


@router.get("/api/platform/llm")
def llm_settings(req: Request):
    with db.session() as s:
        _admin(req, s)
    return _llm_state()


@router.get("/api/platform/llm/models")
async def llm_models(req: Request, provider: str):
    from . import llm
    with db.session() as s:
        _admin(req, s)
    if provider not in llm.PROVIDERS:
        raise HTTPException(404, "Unknown provider")
    hit = _model_cache.get(provider)
    if hit and time.time() - hit[0] < 600:
        return {"models": hit[1]}
    try:
        models = await llm.list_models(provider)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    except Exception as e:
        raise HTTPException(502, f"Couldn't list {llm.PROVIDERS[provider]['label']} models: {type(e).__name__}") from None
    _model_cache[provider] = (time.time(), models)
    return {"models": models}


@router.put("/api/platform/llm")
async def llm_save(req: Request):
    from . import llm
    body = await req.json()
    with db.session() as s:
        ctx = _admin(req, s)
    for role in ("fast", "smart", "vision"):
        r = body.get(role) or {}
        pid, models = r.get("provider"), [m for m in r.get("models") or [] if str(m).strip()]
        if pid not in llm.PROVIDERS:
            raise HTTPException(400, f"Pick a provider for {role}.")
        if role != "vision" and not models:
            raise HTTPException(400, f"Pick at least one model for {role}.")
        if models and not llm.available(pid):
            raise HTTPException(400, f"{llm.PROVIDERS[pid]['label']} isn't available: set {llm.PROVIDERS[pid]['env']} on the server first.")
    llm.save(body)
    with db.session() as s:
        log_activity(s, ctx, "settings_updated", "AI models: " + "; ".join(f"{r} {llm.CONFIG[r]['provider']}:{','.join(llm.CONFIG[r]['models'])}" for r in ("fast", "smart", "vision"))[:300])
    return _llm_state()


@router.delete("/api/platform/llm")
def llm_reset(req: Request):
    from . import llm
    with db.session() as s:
        _admin(req, s)
    llm.reset()
    return _llm_state()


@router.post("/api/platform/llm/test")
async def llm_test(req: Request):
    from . import llm
    body = await req.json()
    with db.session() as s:
        _admin(req, s)
    role = body.get("role")
    if role not in ("fast", "smart", "vision"):
        raise HTTPException(400, "Unknown role")
    if llm.MOCK:
        return {"ok": True, "model": "mock", "seconds": 0, "reply": {"mock": True}}
    return await llm.test_role(role)
