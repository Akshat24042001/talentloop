"""Sign-up, sign-in, team and invites, company settings, and the platform admin console."""
import os
import time

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import func

from . import auth, db, store

router = APIRouter()
INVITE_DAYS = 14

DEFAULT_SETTINGS = {
    "about": "", "website": "", "industry": "", "size": "", "country": "", "timezone": "Asia/Kolkata",
    "logo_url": "", "brand_color": "#2848e6", "careers_enabled": True, "careers_headline": "",
    "default_currency": "INR", "eeo_statement": "",
    "match_top_n": 5, "ai_reports_per_run": 25,
    "match_weights": {"skills": 45, "experience": 20, "relevance": 20, "location": 10, "logistics": 5},
    "interview_defaults": {"max_warnings": 2, "enforce_focus": True, "block_multi_monitor": True, "require_screen_share": False,
                           "duration_min": 15},
    "retention_days": 0,
    # Proposal: mandatory details candidates can't skip (careers form and campus registration)
    "application_fields": {"phone": True, "location": True, "expected_salary": True, "notice_days": True, "total_experience_years": False,
                           "current_company": False, "linkedin": False, "resume": True},
    # HR-approved answers the AI interviewer may give when a candidate asks about the company (nothing else)
    "faq": [],
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
            mems.append({"org_id": o.id, "name": o.name, "slug": o.slug, "role": m.role})
    org = ctx.org
    return {
        "user": {"id": u.id, "email": u.email, "name": u.name} if u else {"id": None, "email": "api-key", "name": "API key"},
        "org": {"id": org.id, "name": org.name, "slug": org.slug, "settings": org_settings(org)} if org else None,
        "role": ctx.role, "role_label": auth.ROLE_LABEL.get(ctx.role or "", ""), "platform_admin": ctx.platform_admin,
        "memberships": mems,
        "can": {"manage_team": ctx.has(auth.MANAGE_TEAM), "manage_jobs": ctx.has(auth.MANAGE_JOBS), "see_all": ctx.has(auth.SEE_ALL) or ctx.has(auth.MANAGE_JOBS)},
    }


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------
@router.post("/api/auth/signup")
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
    with db.session() as s:
        if s.query(db.User).filter_by(email=email).first():
            raise HTTPException(409, "An account with this email already exists. Sign in instead.")
        user = db.User(email=email, name=name, password_hash=auth.hash_password(pw), is_platform_admin=email in auth.PLATFORM_ADMINS)
        settings = {k: str(body.get(k) or "")[:200] for k in ("website", "industry", "size", "country") if body.get(k)}
        org = db.Org(name=company, slug=unique_slug(s, company), settings=settings)
        s.add_all([user, org]); s.flush()
        s.add(db.Membership(user_id=user.id, org_id=org.id, role="owner", title=str(body.get("title") or "")[:120]))
        auth.start_session(s, resp, req, user, org.id)
        log_activity(s, None, "company_created", f"{company} by {email}", org_id=org.id)
        s.flush()
        return me_payload(s, auth.Ctx(user=user, org=org, role="owner", platform_admin=user.is_platform_admin))


@router.post("/api/auth/login")
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
async def switch_org(req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = auth.current(req, s)
        if not ctx.user:
            raise HTTPException(400, "Not available for API keys")
        mem = s.query(db.Membership).filter_by(user_id=ctx.user.id, org_id=str(body.get("org_id"))).first()
        if not mem or mem.active is False:
            raise HTTPException(404, "You are not a member of that company")
        sess = s.get(db.AuthSession, auth.token_hash(req.cookies.get(auth.COOKIE, "")))
        sess.org_id = mem.org_id
    return {"ok": True}


@router.post("/api/auth/password")
async def change_password(req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = auth.current(req, s)
        if not ctx.user or not auth.check_password(str(body.get("current") or ""), ctx.user.password_hash):
            raise HTTPException(400, "Your current password is not correct.")
        auth.validate_password(str(body.get("new") or ""))
        ctx.user.password_hash = auth.hash_password(str(body["new"]))
        # sign out everywhere else
        keep = auth.token_hash(req.cookies.get(auth.COOKIE, ""))
        s.query(db.AuthSession).filter(db.AuthSession.user_id == ctx.user.id, db.AuthSession.token_hash != keep).delete()
    return {"ok": True}


@router.patch("/api/auth/profile")
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
    """A fresh link for a pending invite (the old link stops working) with a new 7-day expiry."""
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
@router.get("/api/org")
def get_org(req: Request):
    with db.session() as s:
        ctx = auth.current(req, s)
        auth.require_org(ctx)
        return {"id": ctx.org.id, "name": ctx.org.name, "slug": ctx.org.slug, "settings": org_settings(ctx.org), "created_at": ctx.org.created_at}


@router.patch("/api/org")
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
            if k == "ai_reports_per_run":
                v = max(0, min(500, int(v or 0)))
            if k in ("retention_days", "recording_retention_days"):
                v = max(0, min(3650, int(v or 0)))
            if k == "faq":
                v = [{"q": str(x.get("q") or "").strip()[:300], "a": str(x.get("a") or "").strip()[:1500]} for x in (v or [])
                     if isinstance(x, dict) and str(x.get("q") or "").strip() and str(x.get("a") or "").strip()][:40]
            if k == "hrone_columns":
                v = [{"header": str(x.get("header") or "").strip()[:80], "field": str(x.get("field") or "").strip()[:40]} for x in (v or [])
                     if isinstance(x, dict) and str(x.get("header") or "").strip()][:80]
            if k == "application_fields":
                v = {str(f): bool(r) for f, r in (v or {}).items() if f in DEFAULT_SETTINGS["application_fields"]}
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
                 "login_count": u.login_count or 0, "disabled": u.disabled, "platform_admin": u.is_platform_admin, "memberships": mem.get(u.id, [])}
                for u in s.query(db.User).order_by(db.User.created_at.desc())]


@router.patch("/api/admin/orgs/{org_id}")
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
        if "platform_admin" in body and u.id != ctx.user_id:
            u.is_platform_admin = bool(body["platform_admin"])
    return {"ok": True}


def platform_status() -> dict:
    return {"database": "sqlite" if db.IS_SQLITE else "postgres", "persistent_db": not db.IS_SQLITE or os.getenv("PERSISTENT_DISK") == "1",
            "platform_admins_configured": bool(auth.PLATFORM_ADMINS)}
