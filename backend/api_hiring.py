"""Jobs, collaborators, candidates, applications, matching, dashboard, and the public careers site."""
import asyncio
import json
import os
import time
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, or_

from . import auth, db, docs_pdf, jd_schema, llm, matching, resumes, skills, store
from .api_accounts import log_activity, org_settings

router = APIRouter()
STAGES = ["applied", "screening", "shortlisted", "interview", "offer", "hired", "rejected", "withdrawn"]
STAGE_LABEL = {"applied": "Applied", "screening": "Screening", "shortlisted": "Shortlisted", "interview": "Interview", "offer": "Offer",
               "hired": "Hired", "rejected": "Rejected", "withdrawn": "Withdrawn"}
JOB_STATUSES = ("draft", "open", "paused", "closed")


def ctx_of(req: Request, s) -> auth.Ctx:
    ctx = auth.current(req, s)
    if ctx.via_key:            # the API key acts on one company, named by the X-Org header (slug or id)
        ref = req.headers.get("x-org", "").strip()
        ctx.org = s.query(db.Org).filter(or_(db.Org.slug == ref, db.Org.id == ref)).first() if ref else None
        if not ctx.org:
            raise HTTPException(400, "With the API key, send an X-Org header (company slug or id).")
    auth.require_org(ctx)
    return ctx


def get_job(s, ctx: auth.Ctx, job_id: str, need: str = "view") -> tuple[db.Job, str]:
    job = s.get(db.Job, job_id)
    perm = auth.job_permission(s, ctx, job) if job and job.org_id == ctx.org_id else None
    if not job or not perm:
        raise HTTPException(404, "Job not found")
    order = {"view": 0, "edit": 1, "manage": 2}
    if order[perm] < order[need]:
        raise HTTPException(403, "You don't have permission to change this job." if need != "view" else "Not allowed")
    return job, perm


def org_of(s, ctx: auth.Ctx, org_id: str | None = None) -> db.Org:
    return s.get(db.Org, org_id or ctx.org_id)


def job_summary(job: db.Job, extra: dict | None = None) -> dict:
    f = job.fields or {}
    return {"id": job.id, "title": job.title, "department": job.department, "status": job.status, "top_n": int(f.get("top_n") or job.top_n),
            "location": jd_schema.location_text(f), "employment_type": f.get("employment_type", ""), "experience": jd_schema.experience_text(f),
            "salary": jd_schema.salary_text(f), "created_at": job.created_at, "updated_at": job.updated_at, "published_at": job.published_at,
            "matched_at": job.matched_at, "priority": f.get("priority", ""), "openings": f.get("openings", 1), **(extra or {})}


def cand_summary(c: db.Candidate) -> dict:
    p, parsed = c.profile or {}, c.parsed or {}
    years = p.get("total_experience_years") if p.get("total_experience_years") not in (None, "") else parsed.get("years")
    return {"id": c.id, "name": c.name or parsed.get("name_guess") or "Unnamed candidate", "email": c.email, "phone": c.phone, "location": c.location,
            "headline": c.headline, "years": years, "skills": (sorted(set(parsed.get("skills") or []) | set(p.get("skills") or [])))[:30],
            "source": c.source, "tags": c.tags or [], "has_resume": bool(c.resume_file), "resume_name": c.resume_name, "created_at": c.created_at,
            "notice_days": p.get("notice_days") if p.get("notice_days") not in (None, "") else parsed.get("notice_days"),
            "expected_salary": p.get("expected_salary"), "current_company": p.get("current_company", "")}


# ---------------------------------------------------------------------------
# meta
# ---------------------------------------------------------------------------
@router.get("/api/meta/job-fields")
def job_fields_meta():
    return {"sections": jd_schema.SECTIONS, "defaults": jd_schema.defaults(), "required": jd_schema.REQUIRED_TO_PUBLISH,
            "skills": skills.all_names(), "stages": [{"id": s, "label": STAGE_LABEL[s]} for s in STAGES]}


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------
@router.get("/api/jobs")
def list_jobs(req: Request, status: str = "", q: str = ""):
    with db.session() as s:
        ctx = ctx_of(req, s)
        qry = s.query(db.Job).filter(db.Job.org_id == ctx.org_id)
        vis = auth.visible_job_ids(s, ctx)
        if vis is not None:
            qry = qry.filter(db.Job.id.in_(vis or [""]))
        if status:
            qry = qry.filter(db.Job.status == status)
        if q:
            qry = qry.filter(or_(db.Job.title.ilike(f"%{q}%"), db.Job.department.ilike(f"%{q}%")))
        jobs = qry.order_by(db.Job.updated_at.desc()).all()
        ids = [j.id for j in jobs]
        apps = dict(s.query(db.Application.job_id, func.count()).filter(db.Application.job_id.in_(ids or [""])).group_by(db.Application.job_id).all())
        new = dict(s.query(db.Application.job_id, func.count()).filter(db.Application.job_id.in_(ids or [""]),
                                                                        db.Application.created_at > time.time() - 7 * 86400).group_by(db.Application.job_id).all())
        ai = dict(s.query(db.Match.job_id, func.count()).filter(db.Match.job_id.in_(ids or [""]), db.Match.ai_report.isnot(None)).group_by(db.Match.job_id).all())
        top = {}
        for m in s.query(db.Match).filter(db.Match.job_id.in_(ids or [""]), db.Match.rank == 1):
            top[m.job_id] = m.score
        perms = {j.id: auth.job_permission(s, ctx, j) for j in jobs}
        return [job_summary(j, {"applications": apps.get(j.id, 0), "new_applications": new.get(j.id, 0), "ai_reports": ai.get(j.id, 0),
                                "best_score": top.get(j.id), "permission": perms[j.id]}) for j in jobs]


@router.post("/api/jobs")
async def create_job(req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "create jobs")
        org = org_of(s, ctx)
        st = org_settings(org)
        fields = {**jd_schema.defaults(), "currency": st.get("default_currency", "INR"), "top_n": st.get("match_top_n", 5)}
        fields.update(jd_schema.clean(body.get("fields") or {}))
        if not fields.get("title"):
            raise HTTPException(400, "A job title is required.")
        status = body.get("status") or "draft"
        if status not in JOB_STATUSES:
            raise HTTPException(400, "Unknown status")
        if status == "open" and (miss := jd_schema.missing_to_publish(fields)):
            raise HTTPException(400, "Fill in before publishing: " + ", ".join(miss))
        job = db.Job(org_id=org.id, title=fields["title"], department=fields.get("department", ""), status=status, fields=fields,
                     top_n=int(fields.get("top_n") or 5), created_by=ctx.user_id, published_at=time.time() if status == "open" else None)
        s.add(job); s.flush()
        log_activity(s, ctx, "job_created", f"{job.title} ({status})", job_id=job.id)
        return job_detail(s, ctx, job)


def job_detail(s, ctx: auth.Ctx, job: db.Job) -> dict:
    perm = auth.job_permission(s, ctx, job)
    collabs = [{"id": c.id, "user_id": u.id, "name": u.name, "email": u.email, "permission": c.permission}
               for c, u in s.query(db.JobCollaborator, db.User).join(db.User, db.User.id == db.JobCollaborator.user_id).filter(db.JobCollaborator.job_id == job.id)]
    creator = s.get(db.User, job.created_by) if job.created_by else None
    org = s.get(db.Org, job.org_id)
    return {**job_summary(job), "fields": job.fields or {}, "permission": perm, "collaborators": collabs,
            "created_by": {"name": creator.name, "email": creator.email} if creator else None,
            "missing_to_publish": jd_schema.missing_to_publish(job.fields or {}), "careers_url": f"/careers/{org.slug}/jobs/{job.id}",
            "applications": s.query(db.Application).filter_by(job_id=job.id).count()}


@router.get("/api/jobs/{job_id}")
def get_job_api(job_id: str, req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        job, _ = get_job(s, ctx, job_id)
        return job_detail(s, ctx, job)


@router.patch("/api/jobs/{job_id}")
async def update_job(job_id: str, req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = ctx_of(req, s)
        job, perm = get_job(s, ctx, job_id, "edit")
        old = dict(job.fields or {})
        if "fields" in body:
            new = {**old, **jd_schema.clean(body["fields"] or {})}
            for k, v in (body["fields"] or {}).items():     # explicit clears
                if v in ("", None, []) and k in jd_schema.FIELDS:
                    new.pop(k, None)
            if not new.get("title"):
                raise HTTPException(400, "A job title is required.")
            changed = [jd_schema.FIELDS[k]["label"] for k in jd_schema.FIELDS if old.get(k) != new.get(k)]
            job.fields, job.title, job.department = new, new["title"], new.get("department", "")
            job.top_n = int(new.get("top_n") or job.top_n or 5)
            if changed:
                log_activity(s, ctx, "job_edited", "Changed: " + ", ".join(changed[:15]) + ("…" if len(changed) > 15 else ""), job_id=job.id)
                job.matched_at = None          # matches are recomputed on next view
        if body.get("status") and body["status"] != job.status:
            if perm != "manage":
                raise HTTPException(403, "Only HR can publish, pause or close a job.")
            if body["status"] not in JOB_STATUSES:
                raise HTTPException(400, "Unknown status")
            if body["status"] == "open" and (miss := jd_schema.missing_to_publish(job.fields or {})):
                raise HTTPException(400, "Fill in before publishing: " + ", ".join(miss))
            log_activity(s, ctx, "job_status", f"{job.status} → {body['status']}", job_id=job.id)
            job.status = body["status"]
            if job.status == "open" and not job.published_at:
                job.published_at = time.time()
        job.updated_at = time.time()
        return job_detail(s, ctx, job)


@router.delete("/api/jobs/{job_id}")
def delete_job(job_id: str, req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        job, _ = get_job(s, ctx, job_id, "manage")
        for model in (db.Match, db.Application, db.JobCollaborator):
            s.query(model).filter_by(job_id=job.id).delete()
        log_activity(s, ctx, "job_deleted", job.title)
        s.delete(job)
    return {"ok": True}


@router.post("/api/jobs/{job_id}/duplicate")
def duplicate_job(job_id: str, req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        job, _ = get_job(s, ctx, job_id, "manage")
        f = dict(job.fields or {})
        f["title"] = f"{f.get('title', '')} (copy)"[:120]
        new = db.Job(org_id=job.org_id, title=f["title"], department=job.department, status="draft", fields=f, top_n=job.top_n, created_by=ctx.user_id)
        s.add(new); s.flush()
        log_activity(s, ctx, "job_created", f"{new.title} (copy of {job.title})", job_id=new.id)
        return {"id": new.id}


@router.get("/api/jobs/{job_id}/jd")
def job_jd(job_id: str, req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        job, _ = get_job(s, ctx, job_id)
        org = s.get(db.Org, job.org_id)
        return jd_schema.compose(job.fields or {}, org.name, org_settings(org), public=False)


@router.get("/api/jobs/{job_id}/jd.pdf")
def job_pdf(job_id: str, req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        job, _ = get_job(s, ctx, job_id)
        org = s.get(db.Org, job.org_id)
        jd = jd_schema.compose(job.fields or {}, org.name, org_settings(org), public=False)
    pdf = docs_pdf.jd_pdf(jd)
    name = auth.slugify(f"{jd['title']}-{org.name}", 80)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}.pdf"'})


AI_WRITE_SYSTEM = """You help a recruiter write a clear, inclusive, specific job description. Output ONLY JSON:
{"summary": str (2-3 sentences, no fluff), "responsibilities": [str] (5-7, start with a verb), "first_90_days": [str] (3),
"nice_to_have_skills": [str] (up to 5), "day_in_life": str (2 sentences)}
Use only the facts given; never invent salary, benefits or company facts. Avoid gendered or exclusionary wording."""


@router.post("/api/jobs/{job_id}/ai-write")
async def ai_write(job_id: str, req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        job, _ = get_job(s, ctx, job_id, "edit")
        f = dict(job.fields or {})
        org = s.get(db.Org, job.org_id)
        org_id = org.id
        facts = {k: f.get(k) for k in ("title", "department", "team", "seniority", "employment_type", "must_have_skills", "nice_to_have_skills",
                                       "tools", "experience_min", "experience_max", "industry_experience", "summary", "responsibilities") if f.get(k)}
        facts["company"] = org.name
        facts["about_company"] = org_settings(org).get("about", "")[:600]
    if llm.MOCK:
        t = f.get("title", "this role")
        out = {"summary": f"As our {t}, you'll own important work end to end and help the team ship faster.",
               "responsibilities": [f"Deliver high-quality work as {t}", "Collaborate closely with the team and stakeholders",
                                    "Improve processes and tooling", "Mentor others and share knowledge", "Measure results and iterate"],
               "first_90_days": ["Ship your first meaningful contribution", "Own one area end to end", "Propose one improvement"],
               "nice_to_have_skills": [], "day_in_life": "A mix of focused work, collaboration and review."}
    else:
        user = json.dumps(facts, ensure_ascii=False)
        out = await llm.complete_json(AI_WRITE_SYSTEM, user, llm.SMART_MODEL, temperature=0.4, max_tokens=900)
        with db.session() as s:
            s.add(db.AIUsage(org_id=org_id, kind="jd_write", model=llm.SMART_MODEL, input_chars=len(user), output_chars=len(json.dumps(out))))
    return jd_schema.clean({k: out.get(k) for k in ("summary", "responsibilities", "first_90_days", "nice_to_have_skills", "day_in_life")})


# ---------------------------------------------------------------------------
# collaborators and activity
# ---------------------------------------------------------------------------
@router.post("/api/jobs/{job_id}/collaborators")
async def add_collaborator(job_id: str, req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = ctx_of(req, s)
        job, _ = get_job(s, ctx, job_id, "manage")
        uid = str(body.get("user_id") or "")
        if not s.query(db.Membership).filter_by(user_id=uid, org_id=job.org_id).first():
            raise HTTPException(400, "That person is not on your team.")
        perm = body.get("permission") if body.get("permission") in ("editor", "reviewer") else "editor"
        row = s.query(db.JobCollaborator).filter_by(job_id=job.id, user_id=uid).first()
        if row:
            row.permission = perm
        else:
            s.add(db.JobCollaborator(job_id=job.id, user_id=uid, permission=perm, added_by=ctx.user_id))
        u = s.get(db.User, uid)
        log_activity(s, ctx, "collaborator_added", f"{u.name or u.email} as {perm}", job_id=job.id)
        s.flush()
        return job_detail(s, ctx, job)


@router.delete("/api/jobs/{job_id}/collaborators/{cid}")
def remove_collaborator(job_id: str, cid: str, req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        job, _ = get_job(s, ctx, job_id, "manage")
        row = s.query(db.JobCollaborator).filter_by(id=cid, job_id=job.id).first()
        if row:
            u = s.get(db.User, row.user_id)
            s.delete(row)
            log_activity(s, ctx, "collaborator_removed", u.name or u.email if u else row.user_id, job_id=job.id)
        s.flush()
        return job_detail(s, ctx, job)


def activity_rows(s, q, limit=50) -> list[dict]:
    rows = q.order_by(db.Activity.at.desc()).limit(limit).all()
    users = {u.id: u for u in s.query(db.User).filter(db.User.id.in_({r.user_id for r in rows if r.user_id} or {""}))}
    jobs = {j.id: j.title for j in s.query(db.Job).filter(db.Job.id.in_({r.job_id for r in rows if r.job_id} or {""}))}
    return [{"id": r.id, "action": r.action, "detail": r.detail, "at": r.at, "job_id": r.job_id, "job": jobs.get(r.job_id),
             "candidate_id": r.candidate_id, "user": (users[r.user_id].name or users[r.user_id].email) if r.user_id in users else None} for r in rows]


@router.get("/api/jobs/{job_id}/activity")
def job_activity(job_id: str, req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        job, _ = get_job(s, ctx, job_id)
        return activity_rows(s, s.query(db.Activity).filter(db.Activity.job_id == job.id), 100)


# ---------------------------------------------------------------------------
# candidates
# ---------------------------------------------------------------------------
def visible_candidate_ids(s, ctx: auth.Ctx) -> set[str] | None:
    vis = auth.visible_job_ids(s, ctx)
    if vis is None:
        return None
    ids = {a.candidate_id for a in s.query(db.Application.candidate_id).filter(db.Application.job_id.in_(vis or [""]))}
    ids |= {m.candidate_id for m in s.query(db.Match.candidate_id).filter(db.Match.job_id.in_(vis or [""]))}
    return ids


def get_candidate(s, ctx: auth.Ctx, cid: str) -> db.Candidate:
    c = s.get(db.Candidate, cid)
    if not c or c.org_id != ctx.org_id:
        raise HTTPException(404, "Candidate not found")
    vis = visible_candidate_ids(s, ctx)
    if vis is not None and c.id not in vis:
        raise HTTPException(404, "Candidate not found")
    return c


@router.get("/api/candidates")
def list_candidates(req: Request, q: str = "", skill: str = "", min_years: float | None = None, source: str = "", page: int = 1, limit: int = 50):
    with db.session() as s:
        ctx = ctx_of(req, s)
        qry = s.query(db.Candidate).filter(db.Candidate.org_id == ctx.org_id)
        vis = visible_candidate_ids(s, ctx)
        if vis is not None:
            qry = qry.filter(db.Candidate.id.in_(vis or {""}))
        if source:
            qry = qry.filter(db.Candidate.source == source)
        if q:
            like = f"%{q}%"
            qry = qry.filter(or_(db.Candidate.name.ilike(like), db.Candidate.email.ilike(like), db.Candidate.headline.ilike(like),
                                 db.Candidate.location.ilike(like), db.Candidate.resume_text.ilike(like)))
        rows = qry.order_by(db.Candidate.created_at.desc()).all()
        out = [cand_summary(c) for c in rows]
        if skill:
            want = skills.canonical(skill).lower()
            out = [c for c in out if any(x.lower() == want for x in c["skills"])]
        if min_years is not None:
            out = [c for c in out if c["years"] is not None and float(c["years"]) >= min_years]
        apps = dict(s.query(db.Application.candidate_id, func.count()).filter(db.Application.org_id == ctx.org_id).group_by(db.Application.candidate_id).all())
        total = len(out)
        limit = max(1, min(200, limit))
        page_rows = out[(page - 1) * limit: page * limit]
        for c in page_rows:
            c["applications"] = apps.get(c["id"], 0)
        return {"total": total, "page": page, "limit": limit, "items": page_rows}


def _save_resume(org_id: str, cand_id: str, raw: bytes, filename: str) -> tuple[str, str]:
    ext = Path(filename or "resume.pdf").suffix.lower() or ".pdf"
    key = f"{org_id}/candidates/{cand_id}/resume{ext}"
    store.put_file(key, raw, resumes.RESUME_TYPES.get(ext, "application/octet-stream"))
    return key, Path(filename).name[:200] if filename else f"resume{ext}"


def check_resume(raw: bytes, filename: str) -> None:
    ext = Path(filename or "").suffix.lower()
    if ext not in resumes.RESUME_TYPES:
        raise HTTPException(400, "Upload a PDF, DOCX or TXT resume.")
    if len(raw) > resumes.MAX_RESUME_BYTES:
        raise HTTPException(413, "The resume is larger than 10 MB.")
    if ext == ".pdf" and not raw.startswith(b"%PDF"):
        raise HTTPException(400, "That file is not a valid PDF.")


def upsert_candidate(s, org_id: str, *, text: str, parsed: dict, profile: dict, source: str, raw: bytes | None = None,
                     filename: str = "") -> tuple[db.Candidate, bool]:
    """Create or update a candidate, de-duplicated by email within the company."""
    email = (profile.get("email") or (parsed.get("emails") or [""])[0] or "").strip().lower()
    cand = s.query(db.Candidate).filter_by(org_id=org_id, email=email).first() if email else None
    created = cand is None
    if created:
        cand = db.Candidate(org_id=org_id, source=source)
        s.add(cand); s.flush()
    merged = {**(cand.profile or {}), **{k: v for k, v in profile.items() if v not in (None, "", [])}}
    cand.profile = merged
    cand.name = (profile.get("name") or cand.name or parsed.get("name_guess") or "")[:200]
    cand.email = email or cand.email
    cand.phone = (profile.get("phone") or cand.phone or (parsed.get("phones") or [""])[0])[:60]
    cand.location = (profile.get("location") or cand.location or parsed.get("location") or "")[:200]
    cand.headline = (profile.get("headline") or profile.get("current_title") or cand.headline or "")[:300]
    if text:
        cand.resume_text = text[:200000]
        cand.parsed = parsed
    if raw is not None:
        cand.resume_file, cand.resume_name = _save_resume(org_id, cand.id, raw, filename)
    cand.updated_at = time.time()
    return cand, created


@router.post("/api/candidates/upload")
async def upload_resumes(req: Request, files: list[UploadFile] = File(...)):
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "add candidates")
        org_id = ctx.org_id
    if len(files) > 200:
        raise HTTPException(400, "Upload at most 200 resumes at a time.")
    results = {"created": 0, "updated": 0, "failed": [], "candidates": []}
    for f in files:
        raw = await f.read()
        try:
            check_resume(raw, f.filename or "")
            text = await asyncio.to_thread(resumes.extract_text, raw, f.filename or "")
            if len(text.strip()) < 40:
                raise HTTPException(400, "No readable text (scanned image?)")
            parsed = resumes.parse(text)
            with db.session() as s:
                cand, created = upsert_candidate(s, org_id, text=text, parsed=parsed, profile={}, source="bulk", raw=raw, filename=f.filename or "")
                results["created" if created else "updated"] += 1
                results["candidates"].append(cand_summary(cand))
                log_activity(s, ctx, "candidate_added" if created else "candidate_updated", f"{cand.name or cand.email} (resume upload)",
                             org_id=org_id, candidate_id=cand.id)
        except HTTPException as e:
            results["failed"].append({"file": f.filename, "error": e.detail})
        except Exception as e:
            results["failed"].append({"file": f.filename, "error": f"Could not read the file ({type(e).__name__})"})
    with db.session() as s:
        s.query(db.Job).filter(db.Job.org_id == org_id).update({db.Job.matched_at: None})
    return results


@router.post("/api/candidates")
async def create_candidate(req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "add candidates")
        profile = clean_profile(body)
        if not profile.get("name"):
            raise HTTPException(400, "Name is required.")
        text = resumes.profile_text(profile) + "\n" + str(body.get("resume_text") or "")
        cand, created = upsert_candidate(s, ctx.org_id, text=text, parsed=resumes.parse(text), profile=profile, source="manual")
        log_activity(s, ctx, "candidate_added", cand.name, candidate_id=cand.id)
        s.query(db.Job).filter(db.Job.org_id == ctx.org_id).update({db.Job.matched_at: None})
        return cand_summary(cand)


@router.get("/api/candidates/{cid}")
def candidate_detail(cid: str, req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        c = get_candidate(s, ctx, cid)
        org = s.get(db.Org, c.org_id)
        st = org_settings(org)
        apps = [{"id": a.id, "job_id": j.id, "job": j.title, "stage": a.stage, "stage_label": STAGE_LABEL.get(a.stage, a.stage), "created_at": a.created_at,
                 "rating": a.rating, "knockout_failed": a.knockout_failed, "interview_id": a.interview_id, "answers": a.answers}
                for a, j in s.query(db.Application, db.Job).join(db.Job, db.Job.id == db.Application.job_id).filter(db.Application.candidate_id == c.id)]
        best = matching.jobs_for_candidate(s, c.org_id, c, st["match_weights"], st["match_top_n"], limit=8)
        vis = auth.visible_job_ids(s, ctx)
        if vis is not None:
            best = [b for b in best if b["job_id"] in vis]
        reports = {m.job_id: m.ai_report for m in s.query(db.Match).filter(db.Match.candidate_id == c.id, db.Match.ai_report.isnot(None))}
        for b in best:
            b["ai_report"] = reports.get(b["job_id"])
        return {**cand_summary(c), "profile": c.profile or {}, "parsed": c.parsed or {}, "resume_text": (c.resume_text or "")[:20000],
                "applications": apps, "best_jobs": best,
                "activity": activity_rows(s, s.query(db.Activity).filter(db.Activity.candidate_id == c.id), 30)}


@router.patch("/api/candidates/{cid}")
async def update_candidate(cid: str, req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "edit candidates")
        c = get_candidate(s, ctx, cid)
        if "tags" in body:
            c.tags = [str(t).strip()[:40] for t in (body.get("tags") or []) if str(t).strip()][:20]
        prof = clean_profile(body.get("profile") or {})
        if prof:
            c.profile = {**(c.profile or {}), **prof}
            for k in ("name", "phone", "location"):
                if prof.get(k):
                    setattr(c, k, prof[k])
            if prof.get("headline"):
                c.headline = prof["headline"]
        c.updated_at = time.time()
        return cand_summary(c)


@router.delete("/api/candidates/{cid}")
def delete_candidate(cid: str, req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "delete candidates")
        c = get_candidate(s, ctx, cid)
        s.query(db.Match).filter_by(candidate_id=c.id).delete()
        s.query(db.Application).filter_by(candidate_id=c.id).delete()
        log_activity(s, ctx, "candidate_deleted", c.name or c.email)
        org_id, cand_id = c.org_id, c.id
        s.delete(c)
    store.delete_files(f"{org_id}/candidates/{cand_id}")
    return {"ok": True}


@router.get("/api/candidates/{cid}/resume")
def candidate_resume(cid: str, req: Request, download: int = 0):
    with db.session() as s:
        ctx = ctx_of(req, s)
        c = get_candidate(s, ctx, cid)
        key, name = c.resume_file, c.resume_name
    if not key:
        raise HTTPException(404, "No resume file")
    p = store.get_file(key)
    if not p:
        raise HTTPException(404, "Resume file not found in storage")
    return FileResponse(p, filename=name if download else None, content_disposition_type="attachment" if download else "inline")


@router.get("/api/candidates/{cid}/jobs")
def candidate_jobs(cid: str, req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        c = get_candidate(s, ctx, cid)
        st = org_settings(s.get(db.Org, c.org_id))
        return matching.jobs_for_candidate(s, c.org_id, c, st["match_weights"], st["match_top_n"], limit=20)


# ---------------------------------------------------------------------------
# applications
# ---------------------------------------------------------------------------
def app_row(a: db.Application, c: db.Candidate, m: db.Match | None) -> dict:
    return {"id": a.id, "stage": a.stage, "stage_label": STAGE_LABEL.get(a.stage, a.stage), "created_at": a.created_at, "updated_at": a.updated_at,
            "rating": a.rating, "notes": a.notes, "knockout_failed": a.knockout_failed, "answers": a.answers, "cover_letter": a.cover_letter,
            "interview_id": a.interview_id, "source": a.source, "candidate": cand_summary(c),
            "match": {"score": m.score, "rank": m.rank, "ai_score": m.ai_score, "verdict": (m.ai_report or {}).get("verdict")} if m else None}


@router.get("/api/jobs/{job_id}/applications")
def job_applications(job_id: str, req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        job, _ = get_job(s, ctx, job_id)
        ms = {m.candidate_id: m for m in s.query(db.Match).filter_by(job_id=job.id)}
        rows = s.query(db.Application, db.Candidate).join(db.Candidate, db.Candidate.id == db.Application.candidate_id) \
            .filter(db.Application.job_id == job.id).order_by(db.Application.created_at.desc()).all()
        return {"stages": [{"id": x, "label": STAGE_LABEL[x]} for x in STAGES], "items": [app_row(a, c, ms.get(c.id)) for a, c in rows]}


@router.post("/api/jobs/{job_id}/applications")
async def add_to_job(job_id: str, req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = ctx_of(req, s)
        job, _ = get_job(s, ctx, job_id, "manage")
        c = get_candidate(s, ctx, str(body.get("candidate_id") or ""))
        a = s.query(db.Application).filter_by(job_id=job.id, candidate_id=c.id).first()
        if not a:
            a = db.Application(org_id=job.org_id, job_id=job.id, candidate_id=c.id, stage=body.get("stage") if body.get("stage") in STAGES else "shortlisted",
                               source="sourced")
            s.add(a)
            log_activity(s, ctx, "candidate_added_to_job", f"{c.name} → {job.title}", job_id=job.id, candidate_id=c.id)
        s.flush()
        return app_row(a, c, s.query(db.Match).filter_by(job_id=job.id, candidate_id=c.id).first())


@router.patch("/api/applications/{aid}")
async def update_application(aid: str, req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = ctx_of(req, s)
        a = s.get(db.Application, aid)
        if not a:
            raise HTTPException(404, "Application not found")
        job, perm = get_job(s, ctx, a.job_id)
        if "stage" in body and body["stage"] != a.stage:
            if perm not in ("manage", "edit"):
                raise HTTPException(403, "Reviewers can rate and comment, but not move candidates.")
            if body["stage"] not in STAGES:
                raise HTTPException(400, "Unknown stage")
            c = s.get(db.Candidate, a.candidate_id)
            log_activity(s, ctx, "stage_changed", f"{c.name}: {STAGE_LABEL[a.stage]} → {STAGE_LABEL[body['stage']]}", job_id=job.id, candidate_id=a.candidate_id)
            a.stage = body["stage"]
        if "rating" in body:
            a.rating = max(1, min(5, int(body["rating"]))) if body["rating"] not in (None, "") else None
        if "notes" in body:
            a.notes = str(body["notes"] or "")[:5000]
        a.updated_at = time.time()
        return {"ok": True, "stage": a.stage}


# ---------------------------------------------------------------------------
# matching
# ---------------------------------------------------------------------------
def _stale(s, job: db.Job) -> bool:
    if not job.matched_at:
        return True
    latest = s.query(func.max(db.Candidate.updated_at)).filter(db.Candidate.org_id == job.org_id).scalar() or 0
    return latest > job.matched_at or job.updated_at > job.matched_at


@router.post("/api/match/run")
async def match_run(req: Request):
    body = await req.json() if (await req.body()) else {}
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "run matching")
        st = org_settings(org_of(s, ctx))
        t0 = time.time()
        stats = matching.run(s, ctx.org_id, st["match_weights"], st["match_top_n"], body.get("job_ids") or None)
        stats["ms"] = int((time.time() - t0) * 1000)
        return stats


def match_rows(s, job: db.Job, limit: int) -> list[dict]:
    rows = s.query(db.Match, db.Candidate).join(db.Candidate, db.Candidate.id == db.Match.candidate_id) \
        .filter(db.Match.job_id == job.id, db.Match.rank < 9999).order_by(db.Match.rank).limit(limit).all()
    apps = {a.candidate_id: a for a in s.query(db.Application).filter_by(job_id=job.id)}
    out = []
    for m, c in rows:
        a = apps.get(c.id)
        out.append({"rank": m.rank, "score": m.score, "breakdown": m.breakdown, "knocked_out": m.knocked_out, "ai_score": m.ai_score,
                    "ai_report": m.ai_report, "ai_at": m.ai_at, "candidate": cand_summary(c),
                    "application": {"id": a.id, "stage": a.stage, "stage_label": STAGE_LABEL.get(a.stage)} if a else None})
    return out


@router.get("/api/jobs/{job_id}/matches")
def job_matches(job_id: str, req: Request, limit: int = 30):
    with db.session() as s:
        ctx = ctx_of(req, s)
        job, perm = get_job(s, ctx, job_id)
        st = org_settings(s.get(db.Org, job.org_id))
        if _stale(s, job):
            matching.run(s, job.org_id, st["match_weights"], st["match_top_n"], [job.id])
            s.flush()
        top_n = int((job.fields or {}).get("top_n") or job.top_n)
        rows = match_rows(s, job, max(top_n, min(100, limit)))
        pending = len(matching.pending_reports(s, job.org_id, [job.id]))
        return {"top_n": top_n, "matched_at": job.matched_at, "pool": s.query(db.Candidate).filter_by(org_id=job.org_id).count(),
                "ai_pending": pending, "ai_budget": st["ai_reports_per_run"], "items": rows, "can_run_ai": perm == "manage"}


@router.get("/api/match/overview")
def match_overview(req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        st = org_settings(org_of(s, ctx))
        q = s.query(db.Job).filter(db.Job.org_id == ctx.org_id, db.Job.status.in_(("open", "paused")))
        vis = auth.visible_job_ids(s, ctx)
        if vis is not None:
            q = q.filter(db.Job.id.in_(vis or [""]))
        jobs = q.order_by(db.Job.updated_at.desc()).all()
        stale = [j.id for j in jobs if _stale(s, j)]
        if stale and ctx.has(auth.MANAGE_JOBS | {"hiring_manager", "viewer"}):
            matching.run(s, ctx.org_id, st["match_weights"], st["match_top_n"], stale)
            s.flush()
        out, total_pending = [], 0
        for j in jobs:
            n = int((j.fields or {}).get("top_n") or j.top_n)
            rows = match_rows(s, j, n)
            pend = len(matching.pending_reports(s, ctx.org_id, [j.id]))
            total_pending += pend
            out.append({**job_summary(j), "shortlist": [{"candidate_id": r["candidate"]["id"], "name": r["candidate"]["name"], "score": r["score"],
                                                          "ai_score": r["ai_score"], "verdict": (r["ai_report"] or {}).get("verdict"),
                                                          "knocked_out": r["knocked_out"], "applied": bool(r["application"])} for r in rows],
                        "ai_pending": pend, "scored": s.query(db.Match).filter(db.Match.job_id == j.id, db.Match.rank < 9999).count()})
        return {"jobs": out, "pool": s.query(db.Candidate).filter_by(org_id=ctx.org_id).count(), "ai_pending": total_pending,
                "ai_budget": st["ai_reports_per_run"], "mock": llm.MOCK, "model": llm.FAST_MODEL}


@router.post("/api/match/ai-reports")
async def match_ai(req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "generate AI match reports")
        st = org_settings(org_of(s, ctx))
        job_ids = [str(x) for x in (body.get("job_ids") or [])]
        if not job_ids:
            job_ids = [j.id for j in s.query(db.Job).filter(db.Job.org_id == ctx.org_id, db.Job.status == "open")]
        for j in s.query(db.Job).filter(db.Job.id.in_(job_ids or [""])):
            if j.org_id != ctx.org_id:
                raise HTTPException(404, "Job not found")
            if _stale(s, j):
                matching.run(s, ctx.org_id, st["match_weights"], st["match_top_n"], [j.id])
        org_id = ctx.org_id
    budget = min(int(body.get("max") or st["ai_reports_per_run"]), st["ai_reports_per_run"])
    res = await matching.run_ai(org_id, job_ids, budget)
    if res["generated"]:
        with db.session() as s:
            log_activity(s, ctx, "ai_reports", f"{res['generated']} AI match report{'s' if res['generated'] != 1 else ''}", org_id=org_id)
    return res


# ---------------------------------------------------------------------------
# dashboard
# ---------------------------------------------------------------------------
@router.get("/api/dashboard")
def dashboard(req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        org_id, t = ctx.org_id, time.time()
        vis = auth.visible_job_ids(s, ctx)
        jq = s.query(db.Job).filter(db.Job.org_id == org_id)
        aq = s.query(db.Application).filter(db.Application.org_id == org_id)
        if vis is not None:
            jq = jq.filter(db.Job.id.in_(vis or [""]))
            aq = aq.filter(db.Application.job_id.in_(vis or [""]))
        jobs = jq.all()
        stage_counts = dict(aq.with_entities(db.Application.stage, func.count()).group_by(db.Application.stage).all())
        from . import store as _store
        interviews = [r for r in _store.list_all() if r.get("org_id") == org_id]
        series = [0] * 14
        for (ts,) in aq.with_entities(db.Application.created_at).filter(db.Application.created_at > t - 14 * 86400):
            series[13 - int((t - ts) // 86400)] += 1
        attention = []
        apps_by_job = dict(aq.with_entities(db.Application.job_id, func.count()).group_by(db.Application.job_id).all())
        for j in jobs:
            if j.status == "open" and not apps_by_job.get(j.id):
                attention.append({"job_id": j.id, "title": j.title, "reason": "No applications yet. Share the careers link or add candidates."})
            elif j.status == "draft" and jd_schema.missing_to_publish(j.fields or {}):
                attention.append({"job_id": j.id, "title": j.title, "reason": "Draft: " + ", ".join(jd_schema.missing_to_publish(j.fields or {})[:3]) + " missing"})
        act_q = s.query(db.Activity).filter(db.Activity.org_id == org_id)
        if vis is not None:
            act_q = act_q.filter(db.Activity.job_id.in_(vis or [""]))
        return {
            "jobs": {"open": sum(j.status == "open" for j in jobs), "draft": sum(j.status == "draft" for j in jobs),
                     "paused": sum(j.status == "paused" for j in jobs), "closed": sum(j.status == "closed" for j in jobs)},
            "candidates": s.query(db.Candidate).filter_by(org_id=org_id).count() if vis is None else len(visible_candidate_ids(s, ctx) or []),
            "new_candidates_7d": s.query(db.Candidate).filter(db.Candidate.org_id == org_id, db.Candidate.created_at > t - 7 * 86400).count() if vis is None else None,
            "applications": sum(stage_counts.values()), "applications_7d": sum(series[-7:]), "applications_14d": series,
            "pipeline": [{"id": st, "label": STAGE_LABEL[st], "count": stage_counts.get(st, 0)} for st in STAGES if st != "withdrawn"],
            "interviews": {"total": len(interviews), "completed": sum(r["status"] in ("completed", "scored", "incomplete") for r in interviews),
                           "in_progress": sum(r["status"] == "in_progress" for r in interviews)},
            "ai_reports": s.query(db.Match).filter(db.Match.org_id == org_id, db.Match.ai_report.isnot(None)).count(),
            "attention": attention[:6], "activity": activity_rows(s, act_q, 12),
        }


# ---------------------------------------------------------------------------
# public careers site (no sign-in)
# ---------------------------------------------------------------------------
def public_org(org: db.Org) -> dict:
    st = org_settings(org)
    return {"name": org.name, "slug": org.slug, "about": st.get("about", ""), "website": st.get("website", ""), "logo_url": st.get("logo_url", ""),
            "brand_color": st.get("brand_color", "#2848e6"), "headline": st.get("careers_headline", ""), "industry": st.get("industry", ""),
            "size": st.get("size", ""), "country": st.get("country", "")}


def _public_job_ok(job: db.Job | None) -> bool:
    return bool(job and job.status == "open" and not (job.fields or {}).get("internal_only"))


@router.get("/api/public/orgs/{slug}")
def public_careers(slug: str):
    with db.session() as s:
        org = s.query(db.Org).filter_by(slug=slug).first()
        if not org or org.disabled or not org_settings(org).get("careers_enabled", True):
            raise HTTPException(404, "Careers page not found")
        jobs = [j for j in s.query(db.Job).filter_by(org_id=org.id, status="open").order_by(db.Job.published_at.desc()) if _public_job_ok(j)]
        out = []
        for j in jobs:
            f = j.fields or {}
            out.append({"id": j.id, "title": j.title, "department": j.department, "location": jd_schema.location_text(f),
                        "workplace_type": f.get("workplace_type", ""), "employment_type": f.get("employment_type", ""),
                        "experience": jd_schema.experience_text(f), "salary": jd_schema.salary_text(f) if f.get("show_salary", True) else "",
                        "published_at": j.published_at, "confidential": bool(f.get("confidential"))})
        return {"org": public_org(org), "jobs": out}


@router.get("/api/public/jobs/{job_id}")
def public_job(job_id: str):
    with db.session() as s:
        job = s.get(db.Job, job_id)
        if not _public_job_ok(job):
            raise HTTPException(404, "This job is no longer open.")
        org = s.get(db.Org, job.org_id)
        if org.disabled:
            raise HTTPException(404, "This job is no longer open.")
        jd = jd_schema.compose(job.fields or {}, org.name, org_settings(org), public=True)
        qs = [{k: q.get(k) for k in ("id", "question", "kind", "required")} for q in (job.fields or {}).get("screening_questions") or []]
        return {"id": job.id, "org": public_org(org) if not (job.fields or {}).get("confidential") else {**public_org(org), "name": jd["company"], "about": "", "website": ""},
                "jd": jd, "questions": qs, "published_at": job.published_at, "deadline": (job.fields or {}).get("deadline")}


PROFILE_KEYS = {"name": 200, "email": 320, "phone": 60, "location": 200, "headline": 300, "current_title": 200, "current_company": 200,
                "summary": 3000, "linkedin": 300, "portfolio": 300, "github": 300, "work_authorization": 200, "salary_currency": 10,
                "pronouns": 40, "referral": 200, "how_heard": 120}


def clean_profile(d: dict) -> dict:
    out = {}
    for k, n in PROFILE_KEYS.items():
        if d.get(k) not in (None, ""):
            out[k] = str(d[k]).strip()[:n]
    if out.get("email"):
        out["email"] = out["email"].lower()
    for k in ("total_experience_years", "notice_days", "current_salary", "expected_salary"):
        if d.get(k) not in (None, ""):
            try:
                out[k] = max(0.0, min(1e10, float(d[k])))
            except (TypeError, ValueError):
                pass
    if d.get("willing_to_relocate") not in (None, ""):
        out["willing_to_relocate"] = bool(d["willing_to_relocate"])
    for k in ("skills", "certifications", "languages"):
        if d.get(k):
            items = d[k] if isinstance(d[k], list) else str(d[k]).split(",")
            out[k] = list(dict.fromkeys(str(x).strip()[:80] for x in items if str(x).strip()))[:60]
    if d.get("skills"):
        out["skills"] = [skills.canonical(x) for x in out["skills"]]
    def rows(key, fields, cap=20):
        res = []
        for r in (d.get(key) or [])[:cap]:
            if isinstance(r, dict):
                row = {f: str(r.get(f) or "").strip()[:2000 if f == "description" else 200] for f in fields}
                if any(row.values()):
                    res.append(row)
        return res
    if d.get("experience"):
        out["experience"] = rows("experience", ("title", "company", "location", "start", "end", "description"))
    if d.get("education"):
        out["education"] = rows("education", ("degree", "field", "school", "year", "grade"))
    if d.get("projects"):
        out["projects"] = rows("projects", ("name", "link", "description"), 10)
    return out


def evaluate_knockouts(questions: list[dict], answers: dict) -> tuple[list[str], list[str]]:
    """Returns (missing required answers, screened-out reasons)."""
    missing, failed = [], []
    for q in questions or []:
        a = answers.get(q["id"])
        if q.get("required") and a in (None, ""):
            missing.append(q["question"])
            continue
        if q.get("required_answer") and str(a).lower() != q["required_answer"]:
            failed.append(q["question"])
        if q.get("min_number") is not None:
            try:
                if float(a) < q["min_number"]:
                    failed.append(q["question"])
            except (TypeError, ValueError):
                pass
    return missing, failed


async def _intake(req: Request, org: db.Org, data: str, resume: UploadFile | None, source: str):
    auth.rate_limit(f"apply:{auth.client_ip(req)}", 12, 3600)
    try:
        d = json.loads(data or "{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "Bad form data")
    profile = clean_profile(d)
    if not profile.get("name") or not profile.get("email"):
        raise HTTPException(400, "Your name and email are required.")
    auth.norm_email(profile["email"])
    if not d.get("consent"):
        raise HTTPException(400, "Please agree to the privacy notice to apply.")
    raw, text, fname = None, "", ""
    if resume is not None and resume.filename:
        raw = await resume.read()
        check_resume(raw, resume.filename)
        fname = resume.filename
        text = await asyncio.to_thread(resumes.extract_text, raw, fname)
    built = resumes.profile_text(profile)
    if not raw:
        if not (profile.get("experience") or profile.get("skills") or profile.get("summary")):
            raise HTTPException(400, "Upload your resume, or fill in your experience and skills.")
        raw = await asyncio.to_thread(docs_pdf.resume_pdf, profile)      # resume built in the form becomes a PDF HR can download
        fname = f"{auth.slugify(profile['name'], 40)}-resume.pdf"
    full_text = (text + "\n" + built).strip()
    return profile, raw, fname, full_text, d


@router.post("/api/public/jobs/{job_id}/apply")
async def apply(job_id: str, req: Request, data: str = Form(...), resume: UploadFile | None = File(None)):
    with db.session() as s:
        job = s.get(db.Job, job_id)
        if not _public_job_ok(job):
            raise HTTPException(404, "This job is no longer open.")
        org = s.get(db.Org, job.org_id)
        questions = (job.fields or {}).get("screening_questions") or []
    profile, raw, fname, text, d = await _intake(req, org, data, resume, "careers")
    answers = {str(k): v for k, v in (d.get("answers") or {}).items()}
    missing, failed = evaluate_knockouts(questions, answers)
    if missing:
        raise HTTPException(400, "Please answer: " + "; ".join(missing))
    with db.session() as s:
        cand, created = upsert_candidate(s, org.id, text=text, parsed=resumes.parse(text), profile=profile, source="careers", raw=raw, filename=fname)
        if s.query(db.Application).filter_by(job_id=job_id, candidate_id=cand.id).first():
            raise HTTPException(409, "You have already applied for this job. We'll be in touch.")
        a = db.Application(org_id=org.id, job_id=job_id, candidate_id=cand.id, answers=answers, cover_letter=str(d.get("cover_letter") or "")[:5000],
                           knockout_failed=failed, stage="rejected" if failed else "applied", source=str(d.get("how_heard") or "careers")[:30])
        s.add(a)
        s.query(db.Job).filter_by(id=job_id).update({db.Job.matched_at: None})
        log_activity(s, None, "application_received", f"{cand.name} applied" + (" (screened out by a screening question)" if failed else ""),
                     org_id=org.id, job_id=job_id, candidate_id=cand.id)
        return {"ok": True, "application_id": a.id, "job": job.title}


@router.post("/api/public/orgs/{slug}/talent-pool")
async def talent_pool(slug: str, req: Request, data: str = Form(...), resume: UploadFile | None = File(None)):
    with db.session() as s:
        org = s.query(db.Org).filter_by(slug=slug).first()
        if not org or org.disabled:
            raise HTTPException(404, "Careers page not found")
    profile, raw, fname, text, _ = await _intake(req, org, data, resume, "talent_pool")
    with db.session() as s:
        cand, created = upsert_candidate(s, org.id, text=text, parsed=resumes.parse(text), profile=profile, source="talent_pool", raw=raw, filename=fname)
        s.query(db.Job).filter(db.Job.org_id == org.id).update({db.Job.matched_at: None})
        log_activity(s, None, "talent_pool_joined", cand.name, org_id=org.id, candidate_id=cand.id)
    return {"ok": True}


@router.post("/api/public/parse-resume")
async def public_parse_resume(req: Request, resume: UploadFile = File(...)):
    """Prefill the application form from a resume (free parsing, nothing stored)."""
    auth.rate_limit(f"parse:{auth.client_ip(req)}", 30, 3600)
    raw = await resume.read()
    check_resume(raw, resume.filename or "")
    text = await asyncio.to_thread(resumes.extract_text, raw, resume.filename or "")
    p = resumes.parse(text)
    return {"name": p["name_guess"], "email": (p["emails"] or [""])[0], "phone": (p["phones"] or [""])[0], "skills": p["skills"],
            "total_experience_years": p["years"], "notice_days": p["notice_days"], "links": p["links"]}


# ---------------------------------------------------------------------------
# JD import and sample data
# ---------------------------------------------------------------------------
@router.post("/api/jobs/parse-jd")
async def parse_jd(req: Request, file: UploadFile = File(...)):
    """Prefill the JD form from an existing JD file (free: no AI)."""
    import re
    with db.session() as s:
        auth.require(ctx_of(req, s), auth.MANAGE_JOBS, "create jobs")
    raw = await file.read()
    check_resume(raw, file.filename or "")
    text = await asyncio.to_thread(resumes.extract_text, raw, file.filename or "")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise HTTPException(400, "No readable text in that file.")
    title = next((ln for ln in lines[:5] if 3 <= len(ln) <= 80 and not ln.endswith((".", ":"))), "")
    bullets = [re.sub(r"^[-•*▪●◦\d.)\s]+", "", ln).strip() for ln in lines if re.match(r"^([-•*▪●◦]|\d+[.)])\s+", ln)]
    paras = [ln for ln in lines if len(ln) > 120]
    yrs = re.search(r"(\d{1,2})\s*\+?\s*(?:-|to)?\s*(\d{1,2})?\s*\+?\s*years?", text, re.I)
    found = sorted(skills.extract(text))
    fields = jd_schema.clean({"title": title, "summary": (paras[0] if paras else "")[:900], "responsibilities": bullets[:8],
                              "must_have_skills": found[:6], "nice_to_have_skills": found[6:12], "tools": found[:12],
                              **({"experience_min": int(yrs.group(1))} if yrs else {}), **({"experience_max": int(yrs.group(2))} if yrs and yrs.group(2) else {})})
    return {"fields": fields, "chars": len(text)}


@router.post("/api/demo/seed")
def demo_seed(req: Request):
    from . import demo
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "load sample data")
        if s.query(db.Candidate).filter_by(org_id=ctx.org_id, source="demo").count():
            raise HTTPException(409, "Sample data is already loaded. Remove it first from Settings > Data.")
        out = demo.seed(s, s.get(db.Org, ctx.org_id), ctx.user_id)
        log_activity(s, ctx, "demo_seeded", f"{out['jobs']} sample jobs, {out['candidates']} sample candidates")
        return out


@router.post("/api/demo/clear")
def demo_clear(req: Request):
    from . import demo
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "remove sample data")
        return demo.clear(s, ctx.org_id)
