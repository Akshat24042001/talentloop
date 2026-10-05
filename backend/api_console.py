"""Platform console: everything a platform admin (PLATFORM_ADMIN_EMAILS) needs to run TalentLoop across all companies,
without touching the database. Every endpoint here checks the platform-admin flag; every change is written to the
audit log of the company it touches, naming the admin who did it."""
import json
import time

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, or_

from . import auth, db, store
from .api_accounts import _admin, _owners_left, log_activity, unique_slug

router = APIRouter()
PAGE = 50


def _page(q, page: int, size: int = PAGE):
    page = max(1, int(page or 1))
    return q.count(), q.offset((page - 1) * size).limit(size).all()


def _like(text: str) -> str:
    return f"%{text.strip().lower().replace('%', '').replace('_', '')}%"


def _who(ctx) -> str:
    return f"platform admin {ctx.user.email}" if ctx.user else "platform API key"


def _orgs(s) -> dict[str, str]:
    return dict(s.query(db.Org.id, db.Org.name).all())


def jd_location(f: dict) -> str:
    from . import jd_schema
    try:
        return jd_schema.location_text(f)
    except Exception:
        return ""


def _audit(s, ctx, org_id: str | None, what: str, **ids) -> None:
    log_activity(s, ctx, "platform_admin", f"{what} (by {_who(ctx)})"[:2000], org_id=org_id, **ids)


# ---------------------------------------------------------------------------
# platform settings: sign-ups on/off and a banner shown to every signed-in user
# ---------------------------------------------------------------------------
PLATFORM_DEFAULTS = {"signups_open": True, "banner": "", "banner_tone": "info"}


def platform_settings() -> dict:
    with db.session() as s:
        row = s.get(db.AppSecret, "platform_settings")
        try:
            saved = json.loads(row.value) if row and row.value else {}
        except ValueError:
            saved = {}
    return {**PLATFORM_DEFAULTS, **{k: v for k, v in saved.items() if k in PLATFORM_DEFAULTS}}


@router.get("/api/console/settings")
def console_settings(req: Request):
    with db.session() as s:
        _admin(req, s)
    return platform_settings()


@router.put("/api/console/settings")
async def console_settings_save(req: Request):
    body = await req.json()
    cur = platform_settings()
    new = {"signups_open": bool(body.get("signups_open", cur["signups_open"])), "banner": str(body.get("banner", cur["banner"]) or "").strip()[:300],
           "banner_tone": body.get("banner_tone") if body.get("banner_tone") in ("info", "warning", "danger") else cur["banner_tone"]}
    with db.session() as s:
        ctx = _admin(req, s)
        row = s.get(db.AppSecret, "platform_settings")
        if row:
            row.value = json.dumps(new)
        else:
            s.add(db.AppSecret(name="platform_settings", value=json.dumps(new)))
        changes = [k for k in new if new[k] != cur[k]]
        if changes:
            _audit(s, ctx, None, "Platform settings changed: " + ", ".join(f"{k} = {new[k]!r}" for k in changes))
    return new


# ---------------------------------------------------------------------------
# companies
# ---------------------------------------------------------------------------
@router.get("/api/console/orgs/{org_id}")
def console_org(org_id: str, req: Request):
    from .api_accounts import org_settings
    with db.session() as s:
        _admin(req, s)
        o = s.get(db.Org, org_id)
        if not o:
            raise HTTPException(404, "Company not found")
        members = [{"id": m.id, "user_id": u.id, "name": u.name, "email": u.email, "role": m.role, "role_label": auth.ROLE_LABEL.get(m.role, m.role),
                    "title": m.title, "active": m.active is not False, "joined_at": m.created_at, "last_login_at": u.last_login_at,
                    "disabled": u.disabled, "email_verified": u.email_verified_at is not None}
                   for m, u in s.query(db.Membership, db.User).join(db.User, db.User.id == db.Membership.user_id)
                   .filter(db.Membership.org_id == org_id).order_by(db.Membership.created_at)]
        invites = [{"id": i.id, "email": i.email, "role_label": auth.ROLE_LABEL.get(i.role, i.role), "created_at": i.created_at, "expires_at": i.expires_at}
                   for i in s.query(db.Invite).filter(db.Invite.org_id == org_id, db.Invite.accepted_at.is_(None), db.Invite.expires_at > time.time())]
        count = lambda m: s.query(m).filter(m.org_id == org_id).count()  # noqa: E731
        stages = dict(s.query(db.Application.stage, func.count()).filter(db.Application.org_id == org_id).group_by(db.Application.stage).all())
        st = org_settings(o)
        return {"id": o.id, "name": o.name, "slug": o.slug, "disabled": o.disabled, "created_at": o.created_at,
                "settings": {k: st.get(k, "") for k in ("about", "website", "industry", "size", "country", "timezone", "logo_url", "careers_enabled")},
                "members": members, "invites": invites,
                "counts": {"jobs": count(db.Job), "open_jobs": s.query(db.Job).filter_by(org_id=org_id, status="open").count(),
                           "candidates": count(db.Candidate), "sample_candidates": s.query(db.Candidate).filter_by(org_id=org_id, source="demo").count(),
                           "applications": count(db.Application), "interviews": count(db.InterviewIndex), "messages": count(db.Message),
                           "ai_calls": count(db.AIUsage), "ai_calls_30d": s.query(db.AIUsage).filter(db.AIUsage.org_id == org_id, db.AIUsage.at > time.time() - 30 * 86400).count()},
                "stages": stages,
                "last_activity": s.query(func.max(db.Activity.at)).filter(db.Activity.org_id == org_id).scalar()}


@router.patch("/api/console/orgs/{org_id}")
async def console_org_update(org_id: str, req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = _admin(req, s)
        o = s.get(db.Org, org_id)
        if not o:
            raise HTTPException(404, "Company not found")
        done = []
        if "name" in body:
            name = str(body["name"] or "").strip()[:200]
            if not name:
                raise HTTPException(400, "A company needs a name.")
            if name != o.name:
                done.append(f"name '{o.name}' -> '{name}'")
                o.name = name
        if body.get("slug"):
            slug = unique_slug(s, str(body["slug"]), skip_org=o.id)
            if slug != o.slug:
                done.append(f"careers address /{o.slug} -> /{slug}")
                o.slug = slug
        if "disabled" in body and bool(body["disabled"]) != o.disabled:
            o.disabled = bool(body["disabled"])
            done.append("company disabled: its people can't sign in" if o.disabled else "company enabled")
        st = dict(o.settings or {})
        for k in ("about", "website", "industry", "size", "country", "timezone", "logo_url"):
            if k in body and str(body[k] or "")[:2000] != str(st.get(k, "") or ""):
                st[k] = str(body[k] or "")[:2000]
                done.append(f"{k} changed")
        if "careers_enabled" in body and bool(body["careers_enabled"]) != bool(st.get("careers_enabled", True)):
            st["careers_enabled"] = bool(body["careers_enabled"])
            done.append("careers page " + ("on" if st["careers_enabled"] else "off"))
        o.settings = st
        if done:
            _audit(s, ctx, o.id, "Company updated: " + "; ".join(done))
    return console_org(org_id, req)


def _erase_org(org_id: str) -> dict:
    """Delete a company and everything in it: database rows in every table with an org_id, its files and interview
    records. People's accounts stay (they may belong to other companies)."""
    from .api_hiring import erase_candidate
    with db.session() as s:
        cands = [c for (c,) in s.query(db.Candidate.id).filter(db.Candidate.org_id == org_id)]
        ivs = [i for (i,) in s.query(db.InterviewIndex.id).filter(db.InterviewIndex.org_id == org_id)]
    for cid in cands:
        erase_candidate(org_id, cid, "platform admin")
    for iid in ivs:
        try:
            store.delete(iid)
        except Exception:
            pass
    store.delete_files(org_id)
    with db.session() as s:
        for table in reversed(db.Base.metadata.sorted_tables):
            if table.name != "orgs" and "org_id" in table.c:
                s.execute(table.delete().where(table.c.org_id == org_id))
        s.query(db.AuthSession).filter(db.AuthSession.org_id == org_id).update({db.AuthSession.org_id: None}, synchronize_session=False)
        s.query(db.Org).filter_by(id=org_id).delete()
    return {"candidates": len(cands), "interviews": len(ivs)}


@router.delete("/api/console/orgs/{org_id}")
async def console_org_delete(org_id: str, req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = _admin(req, s)
        o = s.get(db.Org, org_id)
        if not o:
            raise HTTPException(404, "Company not found")
        if str(body.get("confirm") or "").strip() != o.name:
            raise HTTPException(400, "Type the company's exact name to delete it.")
        name, who = o.name, _who(ctx)
    out = _erase_org(org_id)
    with db.session() as s:
        _audit(s, ctx, None, f"Company '{name}' deleted with {out['candidates']} candidates and {out['interviews']} interviews")
    return {"ok": True, **out, "by": who}


@router.patch("/api/console/memberships/{mid}")
async def console_membership(mid: str, req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = _admin(req, s)
        m = s.get(db.Membership, mid)
        if not m:
            raise HTTPException(404, "Member not found")
        u = s.get(db.User, m.user_id)
        if "role" in body:
            role = str(body["role"])
            if role not in auth.ROLES:
                raise HTTPException(400, "Unknown role")
            if m.role == "owner" and role != "owner" and not _owners_left(s, m.org_id, m.id):
                raise HTTPException(400, "A company needs at least one owner. Make someone else owner first.")
            if role != m.role:
                _audit(s, ctx, m.org_id, f"{u.email}: role {auth.ROLE_LABEL[m.role]} -> {auth.ROLE_LABEL[role]}")
                m.role = role
        if "active" in body and bool(body["active"]) != (m.active is not False):
            if not body["active"] and m.role == "owner" and not _owners_left(s, m.org_id, m.id):
                raise HTTPException(400, "A company needs at least one active owner.")
            m.active = bool(body["active"])
            if not m.active:
                s.query(db.AuthSession).filter(db.AuthSession.user_id == m.user_id, db.AuthSession.org_id == m.org_id).delete()
            _audit(s, ctx, m.org_id, f"{u.email}: access {'restored' if m.active else 'paused'}")
    return {"ok": True}


@router.delete("/api/console/memberships/{mid}")
def console_membership_remove(mid: str, req: Request):
    with db.session() as s:
        ctx = _admin(req, s)
        m = s.get(db.Membership, mid)
        if not m:
            raise HTTPException(404, "Member not found")
        if m.role == "owner" and not _owners_left(s, m.org_id, m.id):
            raise HTTPException(400, "A company needs at least one owner. Make someone else owner first.")
        u = s.get(db.User, m.user_id)
        s.query(db.AuthSession).filter(db.AuthSession.user_id == m.user_id, db.AuthSession.org_id == m.org_id).delete()
        _audit(s, ctx, m.org_id, f"{u.email} removed from the company")
        s.delete(m)
    return {"ok": True}


# ---------------------------------------------------------------------------
# people (accounts)
# ---------------------------------------------------------------------------
@router.get("/api/console/users/{uid}")
def console_user(uid: str, req: Request):
    with db.session() as s:
        _admin(req, s)
        u = s.get(db.User, uid)
        if not u:
            raise HTTPException(404, "Account not found")
        names = _orgs(s)
        t = time.time()
        sess = [{"id": x.token_hash[:12], "company": names.get(x.org_id or "", ""), "ip": x.ip, "device": x.ua, "created_at": x.created_at,
                 "last_seen_at": x.last_seen_at, "online": bool(x.last_seen_at and x.last_seen_at > t - 300)}
                for x in s.query(db.AuthSession).filter(db.AuthSession.user_id == uid, db.AuthSession.expires_at > t)
                .order_by(db.AuthSession.created_at.desc())]
        sole = {o.id for o in _sole_owned(s, uid)}
        mems = [{"id": m.id, "org_id": m.org_id, "company": names.get(m.org_id, ""), "role": m.role, "role_label": auth.ROLE_LABEL.get(m.role, m.role),
                 "title": m.title, "active": m.active is not False, "joined_at": m.created_at, "only_owner": m.org_id in sole}
                for m in s.query(db.Membership).filter_by(user_id=uid).order_by(db.Membership.created_at)]
        days = s.query(func.count()).select_from(db.UserDay).filter(db.UserDay.user_id == uid).scalar() or 0
        recent = [{"at": a.at, "action": a.action, "detail": a.detail, "company": names.get(a.org_id or "", "")}
                  for a in s.query(db.Activity).filter(db.Activity.user_id == uid).order_by(db.Activity.at.desc()).limit(30)]
        return {"id": u.id, "email": u.email, "name": u.name, "created_at": u.created_at, "last_login_at": u.last_login_at,
                "login_count": u.login_count or 0, "disabled": u.disabled, "platform_admin": u.is_platform_admin,
                "admin_from_env": u.email in auth.PLATFORM_ADMINS, "email_verified": u.email_verified_at is not None,
                "email_verified_at": u.email_verified_at, "memberships": mems, "sessions": sess, "active_days": days, "recent": recent}


@router.patch("/api/console/users/{uid}")
async def console_user_update(uid: str, req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = _admin(req, s)
        u = s.get(db.User, uid)
        if not u:
            raise HTTPException(404, "Account not found")
        done = []
        if "name" in body and str(body["name"] or "").strip() and str(body["name"]).strip()[:200] != u.name:
            u.name = str(body["name"]).strip()[:200]
            done.append("name changed")
        if body.get("email") and auth.norm_email(body["email"]) != u.email:
            new = auth.norm_email(body["email"])
            if s.query(db.User).filter_by(email=new).first():
                raise HTTPException(409, "Another account already uses that email.")
            done.append(f"email {u.email} -> {new} (must be confirmed again)")
            u.email, u.email_verified_at = new, None
        if "disabled" in body and bool(body["disabled"]) != u.disabled:
            if u.id == ctx.user_id:
                raise HTTPException(400, "You can't disable your own account.")
            u.disabled = bool(body["disabled"])
            if u.disabled:
                s.query(db.AuthSession).filter_by(user_id=u.id).delete()
            done.append("account disabled and signed out" if u.disabled else "account enabled")
        if body.get("email_verified") is True and u.email_verified_at is None:
            u.email_verified_at = time.time()
            done.append("email marked as confirmed")
        if "platform_admin" in body and bool(body["platform_admin"]) != u.is_platform_admin:
            if u.id == ctx.user_id:
                raise HTTPException(400, "You can't change your own platform admin access.")
            if not body["platform_admin"] and u.email in auth.PLATFORM_ADMINS:
                raise HTTPException(400, "This email is in PLATFORM_ADMIN_EMAILS on the server. Remove it there first, or it comes back at the next sign-in.")
            if body["platform_admin"] and u.email_verified_at is None:
                raise HTTPException(400, "Confirm this person's email before making them a platform admin.")
            u.is_platform_admin = bool(body["platform_admin"])
            done.append("made platform admin" if u.is_platform_admin else "platform admin removed")
        if done:
            for (org_id,) in s.query(db.Membership.org_id).filter_by(user_id=u.id).all() or [(None,)]:
                _audit(s, ctx, org_id, f"Account {u.email}: " + "; ".join(done))
    return console_user(uid, req)


@router.post("/api/console/users/{uid}/signout")
def console_user_signout(uid: str, req: Request):
    with db.session() as s:
        ctx = _admin(req, s)
        u = s.get(db.User, uid)
        if not u:
            raise HTTPException(404, "Account not found")
        n = s.query(db.AuthSession).filter_by(user_id=uid).delete()
        _audit(s, ctx, None, f"{u.email} signed out of {n} session(s)")
    return {"ok": True, "sessions": n}


@router.post("/api/console/users/{uid}/reset-password")
def console_user_reset(uid: str, req: Request):
    """Email the person a password reset code (the admin never sees or sets the password)."""
    from . import messages
    from .api_accounts import _reset_code
    with db.session() as s:
        ctx = _admin(req, s)
        u = s.get(db.User, uid)
        if not u:
            raise HTTPException(404, "Account not found")
        mem = s.query(db.Membership).filter_by(user_id=u.id).first()
        code = _reset_code(u, int(time.time() // 900))
        messages.queue(s, mem.org_id if mem else "", to_email=u.email, subject="Reset your TalentLoop password",
                       body=f"A TalentLoop administrator started a password reset for you. Your code is {code}.\n\nOpen the sign-in page, "
                            "choose \"Forgot your password?\" and enter this code. It works once, for about 15 minutes.", template="password_reset")
        _audit(s, ctx, mem.org_id if mem else None, f"Password reset code emailed to {u.email}")
    return {"ok": True}


# ---------------------------------------------------------------------------
# data across companies: candidates, jobs, interviews, activity, messages
# ---------------------------------------------------------------------------
@router.get("/api/console/candidates")
def console_candidates(req: Request, q: str = "", org: str = "", sample: str = "", page: int = 1):
    with db.session() as s:
        _admin(req, s)
        qq = s.query(db.Candidate)
        if org:
            qq = qq.filter(db.Candidate.org_id == org)
        if sample == "hide":
            qq = qq.filter(db.Candidate.source != "demo")
        elif sample == "only":
            qq = qq.filter(db.Candidate.source == "demo")
        if q.strip():
            like = _like(q)
            qq = qq.filter(or_(func.lower(db.Candidate.name).like(like), func.lower(db.Candidate.email).like(like), db.Candidate.phone.like(like),
                               func.lower(db.Candidate.current_company).like(like), func.lower(db.Candidate.skills_text).like(like)))
        total, rows = _page(qq.order_by(db.Candidate.created_at.desc()), page)
        names = _orgs(s)
        apps = dict(s.query(db.Application.candidate_id, func.count()).filter(db.Application.candidate_id.in_([c.id for c in rows] or [""]))
                    .group_by(db.Application.candidate_id).all())
        return {"total": total, "page": page, "size": PAGE, "items": [
            {"id": c.id, "name": c.name, "email": c.email, "phone": c.phone, "company": names.get(c.org_id, ""), "org_id": c.org_id,
             "headline": c.headline, "current_company": c.current_company, "years": c.years, "location": c.location, "source": c.source,
             "sample": c.source == "demo", "applications": apps.get(c.id, 0), "created_at": c.created_at} for c in rows]}


@router.get("/api/console/candidates/{cid}")
def console_candidate(cid: str, req: Request):
    with db.session() as s:
        _admin(req, s)
        c = s.get(db.Candidate, cid)
        if not c:
            raise HTTPException(404, "Candidate not found")
        names = _orgs(s)
        apps = [{"id": a.id, "job": j.title, "job_id": j.id, "stage": a.stage, "rating": a.rating, "source": a.source, "created_at": a.created_at,
                 "notes": a.notes, "interview_id": a.interview_id}
                for a, j in s.query(db.Application, db.Job).join(db.Job, db.Job.id == db.Application.job_id).filter(db.Application.candidate_id == cid)]
        msgs = [{"subject": m.subject, "status": m.status, "channel": m.channel, "created_at": m.created_at}
                for m in s.query(db.Message).filter(db.Message.candidate_id == cid).order_by(db.Message.created_at.desc()).limit(20)]
        return {"id": c.id, "name": c.name, "email": c.email, "phone": c.phone, "location": c.location, "headline": c.headline,
                "company": names.get(c.org_id, ""), "org_id": c.org_id, "source": c.source, "tags": c.tags or [], "sample": c.source == "demo",
                "current_company": c.current_company, "college": c.college, "years": c.years, "notice_days": c.notice_days,
                "expected_salary": c.expected_salary, "skills": c.skills_text, "profile": c.profile or {}, "parsed": c.parsed or {},
                "resume_name": c.resume_name, "has_resume_file": bool(c.resume_file), "resume_text": (c.resume_text or "")[:20000],
                "created_at": c.created_at, "updated_at": c.updated_at, "applications": apps, "messages": msgs}


@router.delete("/api/console/candidates/{cid}")
def console_candidate_delete(cid: str, req: Request):
    from .api_hiring import erase_candidate
    with db.session() as s:
        ctx = _admin(req, s)
        c = s.get(db.Candidate, cid)
        if not c:
            raise HTTPException(404, "Candidate not found")
        org_id, who = c.org_id, _who(ctx)
    return erase_candidate(org_id, cid, who)


@router.get("/api/console/candidates/{cid}/resume")
async def console_candidate_resume(cid: str, req: Request):
    import asyncio
    from fastapi.responses import FileResponse
    with db.session() as s:
        _admin(req, s)
        c = s.get(db.Candidate, cid)
        if not c or not c.resume_file:
            raise HTTPException(404, "No resume file")
        key, name = c.resume_file, c.resume_name
    p = await asyncio.to_thread(store.get_file, key)
    if not p:
        raise HTTPException(404, "Resume file not found in storage")
    return FileResponse(p, filename=name or "resume", content_disposition_type="inline", headers={"Cache-Control": "private, no-store"})


@router.get("/api/console/jobs")
def console_jobs(req: Request, q: str = "", org: str = "", status: str = "", page: int = 1):
    with db.session() as s:
        _admin(req, s)
        qq = s.query(db.Job)
        if org:
            qq = qq.filter(db.Job.org_id == org)
        if status:
            qq = qq.filter(db.Job.status == status)
        if q.strip():
            like = _like(q)
            qq = qq.filter(or_(func.lower(db.Job.title).like(like), func.lower(db.Job.department).like(like)))
        total, rows = _page(qq.order_by(db.Job.created_at.desc()), page)
        names = _orgs(s)
        apps = dict(s.query(db.Application.job_id, func.count()).filter(db.Application.job_id.in_([j.id for j in rows] or [""])).group_by(db.Application.job_id).all())
        return {"total": total, "page": page, "size": PAGE, "items": [
            {"id": j.id, "title": j.title, "department": j.department, "status": j.status, "company": names.get(j.org_id, ""), "org_id": j.org_id,
             "location": jd_location(j.fields or {}), "applications": apps.get(j.id, 0), "created_at": j.created_at, "published_at": j.published_at}
            for j in rows]}


@router.get("/api/console/jobs/{jid}")
def console_job(jid: str, req: Request):
    with db.session() as s:
        _admin(req, s)
        j = s.get(db.Job, jid)
        if not j:
            raise HTTPException(404, "Job not found")
        stages = dict(s.query(db.Application.stage, func.count()).filter(db.Application.job_id == jid).group_by(db.Application.stage).all())
        apps = [{"candidate_id": c.id, "name": c.name, "email": c.email, "stage": a.stage, "created_at": a.created_at}
                for a, c in s.query(db.Application, db.Candidate).join(db.Candidate, db.Candidate.id == db.Application.candidate_id)
                .filter(db.Application.job_id == jid).order_by(db.Application.created_at.desc()).limit(200)]
        creator = s.get(db.User, j.created_by) if j.created_by else None
        return {"id": j.id, "title": j.title, "department": j.department, "status": j.status, "company": _orgs(s).get(j.org_id, ""), "org_id": j.org_id,
                "fields": j.fields or {}, "rounds": [{"name": r.get("name"), "type": r.get("type")} for r in (j.flow or []) if isinstance(r, dict)],
                "created_by": creator.email if creator else "", "created_at": j.created_at, "published_at": j.published_at,
                "stages": stages, "applications": apps, "edit_fields": job_edit_fields(), "location": jd_location(j.fields or {})}


@router.patch("/api/console/jobs/{jid}")
async def console_job_update(jid: str, req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = _admin(req, s)
        j = s.get(db.Job, jid)
        if not j:
            raise HTTPException(404, "Job not found")
        st = body.get("status")
        if st not in ("open", "paused", "closed", "draft"):
            raise HTTPException(400, "Status must be open, paused, closed or draft.")
        if st != j.status:
            _audit(s, ctx, j.org_id, f"Job '{j.title}': {j.status} -> {st}", job_id=j.id)
            j.status = st
            if st == "open" and not j.published_at:
                j.published_at = time.time()
    return console_job(jid, req)


@router.get("/api/console/interviews")
def console_interviews(req: Request, q: str = "", org: str = "", status: str = "", page: int = 1):
    with db.session() as s:
        _admin(req, s)
        qq = s.query(db.InterviewIndex)
        if org:
            qq = qq.filter(db.InterviewIndex.org_id == org)
        if status:
            qq = qq.filter(db.InterviewIndex.status == status)
        if q.strip():
            like = _like(q)
            qq = qq.filter(or_(func.lower(db.InterviewIndex.candidate).like(like), func.lower(db.InterviewIndex.email).like(like),
                               func.lower(db.InterviewIndex.role).like(like)))
        total, rows = _page(qq.order_by(db.InterviewIndex.created_at.desc()), page)
        names = _orgs(s)
        return {"total": total, "page": page, "size": PAGE, "items": [
            {"id": i.id, "candidate": i.candidate, "email": i.email, "role": i.role, "status": i.status, "channel": i.channel,
             "company": names.get(i.org_id or "", ""), "org_id": i.org_id, "candidate_id": i.candidate_id,
             "recommendation": (i.summary or {}).get("recommendation"), "overall": (i.summary or {}).get("overall"), "created_at": i.created_at}
            for i in rows]}


@router.get("/api/console/activity")
def console_activity(req: Request, q: str = "", org: str = "", action: str = "", user: str = "", page: int = 1):
    with db.session() as s:
        _admin(req, s)
        qq = s.query(db.Activity)
        if org:
            qq = qq.filter(db.Activity.org_id == org)
        if action:
            qq = qq.filter(db.Activity.action == action)
        if user:
            qq = qq.filter(db.Activity.user_id == user)
        if q.strip():
            qq = qq.filter(func.lower(db.Activity.detail).like(_like(q)))
        total, rows = _page(qq.order_by(db.Activity.at.desc()), page)
        names = _orgs(s)
        users = dict(s.query(db.User.id, db.User.email).filter(db.User.id.in_({a.user_id for a in rows if a.user_id} or {""})).all())
        actions = [a for (a,) in s.query(db.Activity.action).distinct().order_by(db.Activity.action)]
        return {"total": total, "page": page, "size": PAGE, "actions": actions, "items": [
            {"id": a.id, "at": a.at, "action": a.action, "detail": a.detail, "company": names.get(a.org_id or "", "Platform" if not a.org_id else "(deleted)"),
             "org_id": a.org_id, "user": users.get(a.user_id or "", "system" if not a.user_id else "(deleted)"), "user_id": a.user_id} for a in rows]}


@router.get("/api/console/messages")
def console_messages(req: Request, q: str = "", org: str = "", status: str = "", page: int = 1):
    from .api_flows import _msg_json
    from . import messages
    with db.session() as s:
        _admin(req, s)
        qq = s.query(db.Message)
        if org:
            qq = qq.filter(db.Message.org_id == org)
        if status:
            qq = qq.filter(db.Message.status == status)
        if q.strip():
            like = _like(q)
            qq = qq.filter(or_(func.lower(db.Message.to).like(like), func.lower(db.Message.subject).like(like)))
        total, rows = _page(qq.order_by(db.Message.created_at.desc()), page)
        names = _orgs(s)
        counts = dict(s.query(db.Message.status, func.count()).group_by(db.Message.status).all())
        return {"total": total, "page": page, "size": PAGE, "counts": counts, "channels": messages.status(),
                "items": [{**_msg_json(m), "company": names.get(m.org_id, ""), "org_id": m.org_id} for m in rows]}


@router.post("/api/console/messages/{mid}/retry")
def console_message_retry(mid: str, req: Request):
    from . import messages
    with db.session() as s:
        ctx = _admin(req, s)
        m = s.get(db.Message, mid)
        if not m:
            raise HTTPException(404, "Message not found")
        messages.retry(s, mid, m.org_id)
        _audit(s, ctx, m.org_id, f"Message '{m.subject[:80]}' to {m.to} queued again")
    return {"ok": True}


@router.get("/api/console/search")
def console_search(req: Request, q: str):
    """One box for everything: companies, people, candidates and jobs matching the text."""
    if len(q.strip()) < 2:
        return {"orgs": [], "users": [], "candidates": [], "jobs": []}
    like = _like(q)
    with db.session() as s:
        _admin(req, s)
        names = _orgs(s)
        return {
            "orgs": [{"id": o.id, "name": o.name, "slug": o.slug} for o in s.query(db.Org).filter(or_(func.lower(db.Org.name).like(like), db.Org.slug.like(like))).limit(8)],
            "users": [{"id": u.id, "name": u.name, "email": u.email} for u in s.query(db.User).filter(or_(func.lower(db.User.name).like(like), db.User.email.like(like))).limit(8)],
            "candidates": [{"id": c.id, "name": c.name, "email": c.email, "company": names.get(c.org_id, "")}
                           for c in s.query(db.Candidate).filter(or_(func.lower(db.Candidate.name).like(like), func.lower(db.Candidate.email).like(like))).limit(8)],
            "jobs": [{"id": j.id, "title": j.title, "company": names.get(j.org_id, "")} for j in s.query(db.Job).filter(func.lower(db.Job.title).like(like)).limit(8)],
        }



# ---------------------------------------------------------------------------
# create and invite
# ---------------------------------------------------------------------------
def _invite(s, ctx, org_id: str, email: str, role: str, title: str = "") -> dict:
    from . import messages
    from .api_accounts import INVITE_DAYS
    from .flows import base_url
    if role not in auth.ROLES:
        raise HTTPException(400, "Unknown role")
    u = s.query(db.User).filter_by(email=email).first()
    if u and s.query(db.Membership).filter_by(user_id=u.id, org_id=org_id).first():
        raise HTTPException(409, f"{email} is already in this company.")
    tok = auth.secrets.token_urlsafe(24)
    inv = db.Invite(org_id=org_id, email=email, role=role, title=title[:120], token_hash=auth.token_hash(tok), created_by=ctx.user_id,
                    expires_at=time.time() + INVITE_DAYS * 86400)
    s.add(inv)
    org = s.get(db.Org, org_id)
    link = f"{base_url()}/invite/{tok}"
    messages.queue(s, org_id, to_email=email, subject=f"You're invited to {org.name} on TalentLoop",
                   body=f"You've been invited to join {org.name} on TalentLoop as {auth.ROLE_LABEL[role]}.\n\nAccept here (valid {INVITE_DAYS} days):\n{link}",
                   template="member_invite")
    _audit(s, ctx, org_id, f"{email} invited as {auth.ROLE_LABEL[role]}")
    return {"path": f"/invite/{tok}", "email": email, "expires_days": INVITE_DAYS}


@router.post("/api/console/orgs")
async def console_org_create(req: Request):
    """New company with its first owner invited by email (they set their own password from the link)."""
    body = await req.json()
    name = str(body.get("name") or "").strip()[:200]
    email = auth.norm_email(body.get("owner_email"))
    if not name:
        raise HTTPException(400, "A company needs a name.")
    with db.session() as s:
        ctx = _admin(req, s)
        org = db.Org(name=name, slug=unique_slug(s, str(body.get("slug") or name)),
                     settings={k: str(body.get(k) or "")[:200] for k in ("website", "industry", "size", "country") if body.get(k)})
        s.add(org)
        s.flush()
        _audit(s, ctx, org.id, f"Company '{name}' created")
        inv = _invite(s, ctx, org.id, email, "owner")
        return {"id": org.id, "slug": org.slug, **inv}


@router.post("/api/console/orgs/{org_id}/invites")
async def console_org_invite(org_id: str, req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = _admin(req, s)
        if not s.get(db.Org, org_id):
            raise HTTPException(404, "Company not found")
        return _invite(s, ctx, org_id, auth.norm_email(body.get("email")), str(body.get("role") or "recruiter"), str(body.get("title") or ""))


@router.delete("/api/console/invites/{inv_id}")
def console_invite_revoke(inv_id: str, req: Request):
    with db.session() as s:
        ctx = _admin(req, s)
        inv = s.get(db.Invite, inv_id)
        if not inv:
            raise HTTPException(404, "Invite not found")
        _audit(s, ctx, inv.org_id, f"Invite for {inv.email} revoked")
        s.delete(inv)
    return {"ok": True}


# ---------------------------------------------------------------------------
# edit candidates and jobs
# ---------------------------------------------------------------------------
CAND_FIELDS = {"name": 200, "email": 320, "phone": 40, "location": 200, "headline": 300, "current_company": 200, "college": 200}


@router.patch("/api/console/candidates/{cid}")
async def console_candidate_update(cid: str, req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = _admin(req, s)
        c = s.get(db.Candidate, cid)
        if not c:
            raise HTTPException(404, "Candidate not found")
        done = []
        for k, n in CAND_FIELDS.items():
            if k in body and str(body[k] or "").strip()[:n] != (getattr(c, k) or ""):
                v = str(body[k] or "").strip()[:n]
                if k == "name" and not v:
                    raise HTTPException(400, "A candidate needs a name.")
                setattr(c, k, v.lower() if k == "email" else v)
                done.append(k)
        for k in ("years", "notice_days", "expected_salary"):
            if k in body:
                try:
                    v = None if body[k] in (None, "") else float(body[k])
                except (TypeError, ValueError):
                    raise HTTPException(400, f"{k} must be a number")
                if v != getattr(c, k):
                    setattr(c, k, v)
                    done.append(k)
        if "tags" in body and isinstance(body["tags"], list):
            c.tags = [str(t).strip()[:40] for t in body["tags"] if str(t).strip()][:30]
            done.append("tags")
        if done:
            c.updated_at = time.time()
            _audit(s, ctx, c.org_id, f"Candidate {c.name}: {', '.join(done)} edited", candidate_id=c.id)
    return console_candidate(cid, req)


JOB_EDITABLE = ("title", "department", "employment_type", "workplace_type", "locations", "experience_min", "experience_max", "education",
                "salary_min", "salary_max", "summary", "responsibilities", "must_have_skills", "nice_to_have_skills", "tools", "benefits")


def job_edit_fields() -> list[dict]:
    """The JD fields the console can edit, straight from the job schema (labels, types, allowed options)."""
    from . import jd_schema
    out = []
    for k in JOB_EDITABLE:
        f = jd_schema.FIELDS.get(k)
        if f:
            out.append({"key": k, "label": f["label"], "type": "list" if f["type"] in jd_schema.LIST_TYPES else f["type"],
                        "options": f.get("options") if f["type"] in ("select", "multiselect") else None})
    return out


@router.put("/api/console/jobs/{jid}")
async def console_job_edit(jid: str, req: Request):
    """Edit a job description. Values go through the job schema's own validation; fields not sent are kept."""
    from . import jd_schema
    body = await req.json()
    sent = {k: body[k] for k in JOB_EDITABLE if k in body and jd_schema.FIELDS.get(k)}
    for k, f in ((k, jd_schema.FIELDS[k]) for k in sent):
        if f["type"] in jd_schema.LIST_TYPES and isinstance(sent[k], str):
            sent[k] = sent[k].split("\n")
    clean = jd_schema.clean(sent)
    with db.session() as s:
        ctx = _admin(req, s)
        j = s.get(db.Job, jid)
        if not j:
            raise HTTPException(404, "Job not found")
        f = dict(j.fields or {})
        for k, v in sent.items():
            empty = v in (None, "") or (isinstance(v, list) and not [x for x in v if str(x).strip()])
            if k in clean and not empty:
                f[k] = clean[k]
            elif empty:
                if k == "title":
                    raise HTTPException(400, "A job needs a title.")
                f.pop(k, None)
            else:
                raise HTTPException(400, f"{jd_schema.FIELDS[k]['label']}: '{v}' isn't an allowed value.")
        j.title, j.department = f.get("title") or j.title, f.get("department") or ""
        j.fields, j.updated_at = f, time.time()
        _audit(s, ctx, j.org_id, f"Job description of '{j.title}' edited ({', '.join(sent)})"[:2000], job_id=j.id)
    return console_job(jid, req)


# ---------------------------------------------------------------------------
# AI interview report
# ---------------------------------------------------------------------------
@router.get("/api/console/interviews/{iid}")
def console_interview(iid: str, req: Request):
    from . import exports
    with db.session() as s:
        _admin(req, s)
        row = s.get(db.InterviewIndex, iid)
        company = _orgs(s).get(row.org_id or "", "") if row else ""
    rec = store.load(iid) if row else None
    if not rec:
        raise HTTPException(404, "Interview not found")
    try:
        transcript = exports.transcript_text(rec)
    except Exception:
        transcript = ""
    plan = rec.get("plan") or {}
    return {"id": iid, "company": company, "org_id": row.org_id, "candidate": row.candidate, "email": row.email, "role": row.role,
            "status": rec.get("status"), "created_at": rec.get("created_at"), "summary": row.summary or {}, "report": rec.get("report") or {},
            "questions": len(plan.get("questions") or []), "transcript": transcript[:60000]}


@router.get("/api/console/interviews/{iid}/report.pdf")
async def console_interview_pdf(iid: str, req: Request):
    import asyncio
    from fastapi.responses import Response
    from . import exports
    with db.session() as s:
        _admin(req, s)
    rec = store.load(iid)
    if not rec:
        raise HTTPException(404, "Interview not found")
    pdf = await asyncio.to_thread(exports.report_pdf, rec)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{exports.base_name(rec)}_report.pdf"'})


# ---------------------------------------------------------------------------
# reports: CSV downloads of everything, filtered by company
# ---------------------------------------------------------------------------
@router.get("/api/console/export/{kind}.csv")
def console_export(kind: str, req: Request, org: str = ""):
    import csv
    import io
    from datetime import datetime, timezone
    from fastapi.responses import Response
    day = lambda ts: datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if ts else ""  # noqa: E731
    with db.session() as s:
        ctx = _admin(req, s)
        names = _orgs(s)
        by_org = lambda q, m: q.filter(m.org_id == org) if org else q  # noqa: E731
        if kind == "companies":
            head = ["company", "careers_address", "created", "disabled", "people", "jobs", "candidates", "applications", "interviews", "ai_requests"]
            cnt = lambda m: dict(s.query(m.org_id, func.count()).group_by(m.org_id).all())  # noqa: E731
            mem, jobs, cands, apps, ivs, ai = cnt(db.Membership), cnt(db.Job), cnt(db.Candidate), cnt(db.Application), cnt(db.InterviewIndex), cnt(db.AIUsage)
            rows = [[o.name, o.slug, day(o.created_at), o.disabled, mem.get(o.id, 0), jobs.get(o.id, 0), cands.get(o.id, 0), apps.get(o.id, 0), ivs.get(o.id, 0), ai.get(o.id, 0)]
                    for o in s.query(db.Org).order_by(db.Org.created_at)]
        elif kind == "people":
            head = ["name", "email", "email_confirmed", "disabled", "platform_admin", "companies", "sign_ins", "last_sign_in", "joined"]
            mems: dict[str, list[str]] = {}
            for m in s.query(db.Membership):
                mems.setdefault(m.user_id, []).append(f"{names.get(m.org_id, '')} ({auth.ROLE_LABEL.get(m.role, m.role)})")
            rows = [[u.name, u.email, u.email_verified_at is not None, u.disabled, u.is_platform_admin, "; ".join(mems.get(u.id, [])), u.login_count or 0,
                     day(u.last_login_at), day(u.created_at)] for u in s.query(db.User).order_by(db.User.created_at)]
        elif kind == "candidates":
            head = ["company", "name", "email", "phone", "location", "headline", "current_company", "years", "source", "sample", "added"]
            rows = [[names.get(c.org_id, ""), c.name, c.email, c.phone, c.location, c.headline, c.current_company, c.years, c.source, c.source == "demo", day(c.created_at)]
                    for c in by_org(s.query(db.Candidate), db.Candidate).order_by(db.Candidate.created_at)]
        elif kind == "jobs":
            head = ["company", "title", "department", "status", "location", "applications", "created", "published"]
            apps = dict(s.query(db.Application.job_id, func.count()).group_by(db.Application.job_id).all())
            rows = [[names.get(j.org_id, ""), j.title, j.department, j.status, jd_location(j.fields or {}), apps.get(j.id, 0), day(j.created_at), day(j.published_at)]
                    for j in by_org(s.query(db.Job), db.Job).order_by(db.Job.created_at)]
        elif kind == "applications":
            head = ["company", "job", "candidate", "email", "stage", "source", "applied"]
            q = s.query(db.Application, db.Job, db.Candidate).join(db.Job, db.Job.id == db.Application.job_id).join(db.Candidate, db.Candidate.id == db.Application.candidate_id)
            rows = [[names.get(a.org_id, ""), j.title, c.name, c.email, a.stage, a.source, day(a.created_at)]
                    for a, j, c in by_org(q, db.Application).order_by(db.Application.created_at)]
        elif kind == "interviews":
            head = ["company", "candidate", "email", "role", "status", "channel", "overall", "recommendation", "created"]
            rows = [[names.get(i.org_id or "", ""), i.candidate, i.email, i.role, i.status, i.channel, (i.summary or {}).get("overall"), (i.summary or {}).get("recommendation"), day(i.created_at)]
                    for i in by_org(s.query(db.InterviewIndex), db.InterviewIndex).order_by(db.InterviewIndex.created_at)]
        elif kind == "audit":
            head = ["when", "company", "who", "action", "detail"]
            users = dict(s.query(db.User.id, db.User.email).all())
            rows = [[day(a.at), names.get(a.org_id or "", "Platform" if not a.org_id else ""), users.get(a.user_id or "", "system"), a.action, a.detail]
                    for a in by_org(s.query(db.Activity), db.Activity).order_by(db.Activity.at.desc()).limit(100000)]
        else:
            raise HTTPException(404, "Unknown report")
        _audit(s, ctx, org or None, f"Report downloaded: {kind}{' for ' + names.get(org, '') if org else ' (all companies)'}, {len(rows)} rows")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(head)
    for r in rows:      # a leading = + - @ would run as a formula in Excel: neutralise it
        w.writerow(["'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v for v in r])
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="talentloop-{kind}-{stamp}.csv"', "Cache-Control": "no-store"})


# ---------------------------------------------------------------------------
# delete an account
# ---------------------------------------------------------------------------
def _sole_owned(s, uid: str) -> list[db.Org]:
    """Companies where this person is the only owner: deleting the person deletes these with everything in them."""
    out = []
    for m in s.query(db.Membership).filter_by(user_id=uid, role="owner"):
        if not s.query(db.Membership).filter(db.Membership.org_id == m.org_id, db.Membership.role == "owner", db.Membership.user_id != uid).count():
            o = s.get(db.Org, m.org_id)
            if o:
                out.append(o)
    return out


@router.delete("/api/console/users/{uid}")
async def console_user_delete(uid: str, req: Request):
    """Delete an account and everything that depends on it: its sign-ins, memberships and activity days, and every
    company it is the only owner of (with all their jobs, candidates, files and interviews). Companies with another
    owner stay; the person just leaves them. The audit log keeps entries, without the person's name."""
    body = await req.json()
    with db.session() as s:
        ctx = _admin(req, s)
        u = s.get(db.User, uid)
        if not u:
            raise HTTPException(404, "Account not found")
        if u.id == ctx.user_id:
            raise HTTPException(400, "You can't delete your own account.")
        if str(body.get("confirm") or "").strip().lower() != u.email:
            raise HTTPException(400, "Type the account's email to delete it.")
        if u.email in auth.PLATFORM_ADMINS:
            raise HTTPException(400, "This email is in PLATFORM_ADMIN_EMAILS on the server. Remove it there first.")
        email = u.email
        doomed = [(o.id, o.name) for o in _sole_owned(s, uid)]
        others = [m.org_id for m in s.query(db.Membership).filter_by(user_id=uid) if m.org_id not in {i for i, _ in doomed}]
    erased = []
    for org_id, name in doomed:
        out = _erase_org(org_id)
        erased.append(f"{name} ({out['candidates']} candidates, {out['interviews']} interviews)")
    with db.session() as s:
        u = s.get(db.User, uid)
        s.query(db.AuthSession).filter_by(user_id=uid).delete()
        s.query(db.Membership).filter_by(user_id=uid).delete()
        s.query(db.UserDay).filter_by(user_id=uid).delete()
        s.query(db.Activity).filter_by(user_id=uid).update({db.Activity.user_id: None}, synchronize_session=False)
        for table in db.Base.metadata.sorted_tables:          # "created by" on jobs, interviews, invites ...: keep the row, forget the person
            if "created_by" in table.c:
                s.execute(table.update().where(table.c.created_by == uid).values(created_by=None))
        s.delete(u)
        for org_id in others:
            _audit(s, ctx, org_id, f"Account {email} deleted")
        _audit(s, ctx, None, f"Account {email} deleted" + (f", with the companies only they owned: {'; '.join(erased)}" if erased else ""))
    return {"ok": True, "companies_deleted": [n for _, n in doomed]}
