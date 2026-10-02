"""HR API for hiring flows: the flow builder, templates, the pipeline board, decisions and bulk actions, the
question bank, campus drives, interview slots, messages, accommodations and human-interview requests."""
import io
import secrets
import time

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import func

from . import assessments, auth, db, flows, messages, refs, scheduling, store, worker
from .offload import offload
from .api_accounts import log_activity, org_settings
from .api_hiring import STAGE_LABEL, cand_summary, ctx_of, get_job, LIST_COLS

router = APIRouter()


def _app_and_job(s, ctx, aid: str, need: str = "edit"):
    a = s.get(db.Application, refs.app_id(aid))
    if not a or a.org_id != ctx.org_id:
        raise HTTPException(404, "Application not found")
    job, perm = get_job(s, ctx, a.job_id, need)
    return a, job, perm


def _actor(ctx) -> str:
    return ctx.user_id or "api"


# ---------------------------------------------------------------------------
# meta, flows and templates
# ---------------------------------------------------------------------------
@router.get("/api/flow-meta")
def flow_meta(req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        custom = [{"id": t.id, "name": t.name, "description": t.description, "rounds": len(t.rounds or []), "custom": True}
                  for t in s.query(db.FlowTemplate).filter(db.FlowTemplate.org_id == ctx.org_id).order_by(db.FlowTemplate.name)]
    return {"round_types": [{"type": k, **v} for k, v in flows.ROUND_TYPES.items()], "pass_modes": list(flows.PASS_MODES),
            "statuses": flows.STATUS_LABEL, "default_config": flows.DEFAULT_CONFIG, "default_rule": flows.DEFAULT_RULE,
            "templates": [{"id": k, "name": v[0], "description": v[1], "rounds": len(v[2]()), "custom": False} for k, v in flows.TEMPLATES.items()] + custom,
            "sections": [{"id": k, "label": v} for k, v in assessments.SECTION_LABEL.items()], "messages": messages.status()}


@router.get("/api/jobs/{job_id}/flow")
def get_flow(job_id: str, req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        job, perm = get_job(s, ctx, job_id)
        flow = flows.flow_of(job)
        counts = dict(s.query(db.Application.round_id, func.count()).filter(db.Application.job_id == job.id,
                      db.Application.stage.notin_(("rejected", "withdrawn"))).group_by(db.Application.round_id).all())
        return {"rounds": flow, "counts": counts, "permission": perm, "team": _team(s, ctx)}


def _team(s, ctx) -> list[dict]:
    return [{"id": u.id, "name": u.name, "email": u.email, "role": m.role, "title": m.title}
            for m, u in s.query(db.Membership, db.User).join(db.User, db.User.id == db.Membership.user_id)
            .filter(db.Membership.org_id == ctx.org_id, db.Membership.active.isnot(False))]


@router.put("/api/jobs/{job_id}/flow")
@offload
async def put_flow(job_id: str, req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = ctx_of(req, s)
        job, _ = get_job(s, ctx, job_id, "edit")
        res = flows.apply_flow_change(s, job, body.get("rounds") or [])
        log_activity(s, ctx, "flow_changed", f"{job.title}: {res['rounds']} rounds" + (f", {res['removed']} removed" if res["removed"] else ""), job_id=job.id)
        return {**res, "rounds_list": job.flow}


@router.post("/api/jobs/{job_id}/flow/template")
@offload
async def use_template(job_id: str, req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = ctx_of(req, s)
        job, _ = get_job(s, ctx, job_id, "edit")
        key = str(body.get("template") or "")
        if key in flows.TEMPLATES:
            rounds = flows.template_rounds(key)
        else:
            t = s.get(db.FlowTemplate, key)
            if not t or t.org_id != ctx.org_id:
                raise HTTPException(404, "Template not found")
            rounds = [{**r, "id": db.new_id(6)} for r in t.rounds]
        res = flows.apply_flow_change(s, job, rounds)
        log_activity(s, ctx, "flow_changed", f"{job.title}: template applied", job_id=job.id)
        return {**res, "rounds_list": job.flow}


@router.get("/api/flow-templates")
def list_templates(req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        return [{"id": t.id, "name": t.name, "description": t.description, "rounds": t.rounds, "updated_at": t.updated_at}
                for t in s.query(db.FlowTemplate).filter(db.FlowTemplate.org_id == ctx.org_id).order_by(db.FlowTemplate.name)]


@router.post("/api/flow-templates")
@offload
async def create_template(req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "save flow templates")
        name = str(body.get("name") or "").strip()[:120]
        if not name:
            raise HTTPException(400, "Give the template a name")
        rounds = body.get("rounds")
        if body.get("from_job"):
            job, _ = get_job(s, ctx, str(body["from_job"]))
            rounds = flows.flow_of(job)
        t = db.FlowTemplate(org_id=ctx.org_id, name=name, description=str(body.get("description") or "")[:500],
                            rounds=flows.normalize_flow(rounds or []), created_by=ctx.user_id)
        s.add(t)
        log_activity(s, ctx, "template_saved", name)
        s.flush()
        return {"id": t.id, "name": t.name}


@router.patch("/api/flow-templates/{tid}")
@offload
async def update_template(tid: str, req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "edit flow templates")
        t = s.get(db.FlowTemplate, tid)
        if not t or t.org_id != ctx.org_id:
            raise HTTPException(404, "Template not found")
        if "name" in body and str(body["name"]).strip():
            t.name = str(body["name"]).strip()[:120]
        if "description" in body:
            t.description = str(body["description"] or "")[:500]
        if "rounds" in body:
            t.rounds = flows.normalize_flow(body["rounds"])
        t.updated_at = time.time()
    return {"ok": True}


@router.delete("/api/flow-templates/{tid}")
def delete_template(tid: str, req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "delete flow templates")
        n = s.query(db.FlowTemplate).filter_by(id=tid, org_id=ctx.org_id).delete()
        if not n:
            raise HTTPException(404, "Template not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# pipeline board
# ---------------------------------------------------------------------------
@router.get("/api/jobs/{job_id}/pipeline")
def pipeline(job_id: str, req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        job, perm = get_job(s, ctx, job_id)
        flow = flows.flow_of(job)
        rows = s.query(db.Application, db.Candidate).options(*LIST_COLS).join(db.Candidate, db.Candidate.id == db.Application.candidate_id) \
            .filter(db.Application.job_id == job.id).order_by(db.Application.created_at.desc()).all()
        ids = [a.id for a, _ in rows]
        results: dict[str, dict] = {}
        for rr in s.query(db.RoundResult).filter(db.RoundResult.application_id.in_(ids or [""])):
            results.setdefault(rr.application_id, {})[rr.round_id] = rr
        ms = dict(s.query(db.Match.candidate_id, db.Match.score).filter(db.Match.job_id == job.id))
        drives = {d.id: d.college for d in s.query(db.Drive).filter(db.Drive.job_id == job.id)}
        items = []
        for a, c in rows:
            rrs = results.get(a.id, {})
            cur = rrs.get(a.round_id)
            items.append({"id": a.id, "ref": refs.app_ref(a.id), "stage": a.stage, "stage_label": STAGE_LABEL.get(a.stage, a.stage), "round_id": a.round_id,
                          "round_status": a.round_status, "created_at": a.created_at, "updated_at": a.updated_at, "rating": a.rating,
                          "source": a.source, "college": drives.get(a.drive_id) or c.college, "match_score": ms.get(c.id),
                          "human_requested": bool(a.human_requested_at), "accommodation": (a.accommodation or {}).get("status"),
                          "knockout_failed": a.knockout_failed, "candidate": cand_summary(c),
                          "current": flows.summary_for(cur) if cur else None,
                          "scores": {rid: rr.score for rid, rr in rrs.items() if rr.score is not None},
                          "flags": [rid for rid, rr in rrs.items() if (rr.integrity or {}).get("flagged")]})
        return {"rounds": flow, "items": items, "permission": perm, "statuses": flows.STATUS_LABEL}


def _do(s, ctx, a, job, action: str, round_id: str = "", reason: str = "", notify: bool = True, bulk: bool = False):
    actor = _actor(ctx)
    # Closed applications only change on purpose: moving someone to a round re-opens them.
    if a.stage in flows.CLOSED_STAGES and action in ("pass", "hold", "select", "reject", "start"):
        raise HTTPException(400, f"This application is closed ({STAGE_LABEL.get(a.stage, a.stage)}). Move them to a round to re-open it.")
    if a.stage == "hired" and action != "move":
        raise HTTPException(400, "This candidate is already hired.")
    if a.stage == "offer" and action in ("pass", "hold", "select"):
        raise HTTPException(400, "This candidate is already selected.")
    if a.stage == "offer" and action == "reject" and bulk:
        raise HTTPException(400, "Selected candidates aren't rejected in bulk. Open their application to change the decision.")
    if action in ("pass", "fail", "hold"):
        rr = flows.get_result(s, a, a.round_id) if a.round_id else None
        if not rr:
            if action == "fail":
                flows.reject(s, a, reason, actor, notify=notify)
                return
            raise HTTPException(400, "This candidate isn't in a round yet.")
        flows.decide(s, rr, action, actor, reason, notify=notify)
    elif action == "move":
        try:
            flows.move_to(s, a, job, round_id, actor, notify=notify)
        except ValueError as e:
            raise HTTPException(400, str(e))
    elif action == "select":
        flows.select(s, a, actor, notify=notify)
    elif action == "reject":
        flows.reject(s, a, reason, actor, notify=notify)
    elif action == "start":                     # applications added before the job had a flow
        flows.on_applied(s, a, job, notify=notify)
    else:
        raise HTTPException(400, "Unknown action")


@router.post("/api/applications/{aid}/decide")
@offload
async def decide_application(aid: str, req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = ctx_of(req, s)
        a, job, _ = _app_and_job(s, ctx, aid)
        _do(s, ctx, a, job, str(body.get("action") or body.get("decision") or ""), str(body.get("round_id") or ""),
            str(body.get("reason") or "")[:1000], notify=body.get("notify", True) is not False)
        out = {"ok": True, "stage": a.stage, "round_id": a.round_id, "round_status": a.round_status}
    worker.kick()
    return out


@router.post("/api/applications/bulk")
@offload
async def bulk(req: Request):
    body = await req.json()
    ids = [str(x) for x in (body.get("ids") or [])][:500]
    action = str(body.get("action") or "")
    done, errors = 0, []
    for aid in ids:
        try:
            with db.session() as s:
                ctx = ctx_of(req, s)
                a, job, _ = _app_and_job(s, ctx, aid)
                if action == "message":
                    text = str(body.get("text") or "").strip()
                    if not text:
                        raise HTTPException(400, "Write a message")
                    flows.notify_candidate(s, a, str(body.get("subject") or "An update on your application")[:120], text, "custom",
                                          flows.status_link(a), "Your application")
                    log_activity(s, ctx, "message_sent", text[:120], job_id=job.id, candidate_id=a.candidate_id)
                else:
                    _do(s, ctx, a, job, action, str(body.get("round_id") or ""), str(body.get("reason") or "")[:1000],
                        notify=body.get("notify", True) is not False, bulk=True)
                done += 1
        except HTTPException as e:
            errors.append({"id": aid, "error": e.detail})
    worker.kick()
    return {"done": done, "errors": errors}


@router.post("/api/jobs/{job_id}/rounds/{rid}/top-n")
@offload
async def apply_top_n(job_id: str, rid: str, req: Request):
    """Pass the best N results in a round (by score) and, if asked, reject the rest."""
    body = await req.json() if (await req.body()) else {}
    with db.session() as s:
        ctx = ctx_of(req, s)
        job, _ = get_job(s, ctx, job_id, "manage")
        rnd = flows.round_of(job, rid)
        if not rnd:
            raise HTTPException(404, "Round not found")
        n = int(body.get("n") or (rnd.get("pass_rule") or {}).get("value") or 10)
        rows = s.query(db.RoundResult, db.Application).join(db.Application, db.Application.id == db.RoundResult.application_id) \
            .filter(db.RoundResult.job_id == job.id, db.RoundResult.round_id == rid, db.RoundResult.status == "submitted",
                    db.Application.round_id == rid, db.Application.stage.notin_(flows.CLOSED_STAGES + flows.FINAL_STAGES)) \
            .order_by(db.RoundResult.score.desc().nullslast()).all()
        flagged = [rr for rr, a in rows if (rr.integrity or {}).get("flagged")]
        rows = [(rr, a) for rr, a in rows if not (rr.integrity or {}).get("flagged")]   # flags always wait for a person
        passed = failed = 0
        for i, (rr, a) in enumerate(rows):
            if i < n:
                flows.decide(s, rr, "pass", _actor(ctx), f"Top {n} by score")
                passed += 1
            elif body.get("reject_rest"):
                flows.decide(s, rr, "fail", _actor(ctx), f"Outside the top {n}")
                failed += 1
        log_activity(s, ctx, "top_n_applied", f"{rnd['name']}: top {n} passed" + (f", {failed} not progressed" if failed else ""), job_id=job.id)
    worker.kick()
    return {"passed": passed, "failed": failed, "flagged_waiting": len(flagged)}


@router.get("/api/applications/{aid}")
def application_detail(aid: str, req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        a, job, perm = _app_and_job(s, ctx, aid, "view")
        c = s.get(db.Candidate, a.candidate_id)
        flow = flows.flow_of(job)
        rrs = {rr.round_id: rr for rr in s.query(db.RoundResult).filter_by(application_id=a.id)}
        rounds = []
        for r in flow:
            rr = rrs.get(r["id"])
            item = {"round": r, "result": flows.summary_for(rr) if rr else None, "data": _safe_data(rr) if rr else None}
            rounds.append(item)
        msgs = [_msg_json(m) for m in s.query(db.Message).filter(db.Message.application_id == a.id).order_by(db.Message.created_at.desc()).limit(50)]
        return {"id": a.id, "ref": refs.app_ref(a.id), "stage": a.stage, "stage_label": STAGE_LABEL.get(a.stage, a.stage), "round_id": a.round_id, "round_status": a.round_status,
                "candidate": cand_summary(c), "job": {"id": job.id, "ref": refs.job_ref(job), "title": job.title}, "rounds": rounds,
                "answers": a.answers, "cover_letter": a.cover_letter, "knockout_failed": a.knockout_failed, "rating": a.rating, "notes": a.notes,
                "human_requested_at": a.human_requested_at, "human_request_note": a.human_request_note, "accommodation": a.accommodation,
                "status_link": flows.status_link(a), "messages": msgs, "permission": perm}


def _safe_data(rr: db.RoundResult) -> dict:
    """Round data for HR, without secrets (link tokens) and with the test paper reduced to the result."""
    d = {k: v for k, v in (rr.data or {}).items() if k not in ("t", "mt", "paper", "answers")}
    if d.get("interview_id"):
        d["interview_ref"] = refs.interview_ref(d["interview_id"])
    return d


def _msg_json(m: db.Message) -> dict:
    return {"id": m.id, "channel": m.channel, "to": m.to, "subject": m.subject, "body": m.body, "template": m.template, "status": m.status,
            "error": m.error, "created_at": m.created_at, "sent_at": m.sent_at}


# ---------------------------------------------------------------------------
# round result actions (HR)
# ---------------------------------------------------------------------------
def _rr(s, ctx, rrid: str, need: str = "edit") -> tuple[db.RoundResult, db.Application, db.Job]:
    rr = s.get(db.RoundResult, rrid)
    if not rr or rr.org_id != ctx.org_id:
        raise HTTPException(404, "Not found")
    a, job, _ = _app_and_job(s, ctx, rr.application_id, need)
    return rr, a, job


@router.post("/api/round-results/{rrid}/resend")
def resend(rrid: str, req: Request):
    """Send the candidate their link again (a fresh link; the old one stops working) and extend the deadline."""
    with db.session() as s:
        ctx = ctx_of(req, s)
        rr, a, job = _rr(s, ctx, rrid)
        rnd = flows.round_of(job, rr.round_id) or {"name": rr.round_type, "deadline_days": 3}
        if rr.round_type == "manager_approval":
            links = flows.request_manager_approval(s, a, job, rnd, rr)
            return {"link": links[0]}
        link = flows.invite_link(s, rr, renew=True)
        if rr.status in ("expired", "pending"):
            rr.status = "invited"
            a.round_status = "invited" if a.round_id == rr.round_id else a.round_status
        if rnd.get("deadline_days"):
            rr.deadline_at = time.time() + rnd["deadline_days"] * 86400
        flows.notify_candidate(s, a, "Your next step", f"Here is your link for the {rnd['name']} again.", "resend", link, "Start here")
        log_activity(s, ctx, "link_resent", f"{rnd['name']}", job_id=job.id, candidate_id=a.candidate_id)
        return {"link": link}


@router.post("/api/round-results/{rrid}/reset")
def reset_attempt(rrid: str, req: Request):
    """Let the candidate take a test or recording again (HR's call, for example after a technical problem)."""
    with db.session() as s:
        ctx = ctx_of(req, s)
        rr, a, job = _rr(s, ctx, rrid)
        rnd = flows.round_of(job, rr.round_id)
        if not rnd:
            raise HTTPException(400, "This round no longer exists in the flow")
        old = {"previous_attempt": {k: v for k, v in (rr.data or {}).items() if k not in ("t", "mt")}, "previous_score": rr.score}
        rr2 = flows.move_to(s, a, job, rnd["id"], _actor(ctx))
        rr2.data = {**(rr2.data or {}), **old}
        log_activity(s, ctx, "attempt_reset", rnd["name"], job_id=job.id, candidate_id=a.candidate_id)
        return {"ok": True, "link": flows.invite_link(s, rr2)}


@router.post("/api/round-results/{rrid}/score")
@offload
async def override_score(rrid: str, req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = ctx_of(req, s)
        rr, a, job = _rr(s, ctx, rrid)
        try:
            sc = max(0.0, min(100.0, float(body.get("score"))))
        except (TypeError, ValueError):
            raise HTTPException(400, "Score must be 0-100")
        old = rr.score
        rr.score = sc
        rr.data = {**(rr.data or {}), "score_overridden": {"from": old, "by": ctx.user_id, "at": time.time(), "note": str(body.get("note") or "")[:500]}}
        log_activity(s, ctx, "score_changed", f"{rr.round_type}: {old} -> {sc}", job_id=job.id, candidate_id=a.candidate_id)
    return {"ok": True}


@router.get("/api/round-results/{rrid}/prep-kit")
async def get_prep_kit(rrid: str, req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        rr, a, job = _rr(s, ctx, rrid, "view")
    return await scheduling.prep_kit(rrid)


@router.post("/api/round-results/{rrid}/feedback")
async def hr_feedback(rrid: str, req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = ctx_of(req, s)
        rr, a, job = _rr(s, ctx, rrid, "edit")      # feedback includes a Select/Reject decision
        if rr.round_type != "human_interview":
            raise HTTPException(400, "Feedback belongs to an interview round.")
        who = (ctx.user.name or ctx.user.email) if ctx.user else "API"
    summary = await scheduling.summarise_notes(str(body.get("notes") or ""))
    with db.session() as s:
        ctx = ctx_of(req, s)
        rr, a, job = _rr(s, ctx, rrid, "edit")
        dec = str(body.get("decision") or "hold")
        if dec not in ("pass", "fail", "hold"):
            raise HTTPException(400, "Choose Select, Reject or Hold")
        scheduling.record_feedback(s, rr, who, dec, body.get("rating"), str(body.get("notes") or ""), body.get("attended", True) is not False, summary)
    worker.kick()
    return {"ok": True}


@router.get("/api/round-results/{rrid}/file")
async def round_file(rrid: str, req: Request, which: str = "file"):
    """The candidate's uploaded video, practical task file or interview recording, for HR."""
    from fastapi.responses import FileResponse
    with db.session() as s:
        ctx = ctx_of(req, s)
        rr, a, job = _rr(s, ctx, rrid, "view")
        d = rr.data or {}
        key = d.get(which) if which in ("file", "attachment_file") else ((d.get("feedback") or {}).get("recording_file") if which == "recording" else None)
        name = d.get("file_name") or "file"
    if not key:
        raise HTTPException(404, "No file")
    import asyncio as _a
    p = await _a.to_thread(store.get_file, key)
    if not p:
        raise HTTPException(404, "File not found in storage")
    return FileResponse(p, filename=name, content_disposition_type="inline", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/api/round-results/{rrid}/snapshot/{which}")
async def round_snapshot_file(rrid: str, which: str, req: Request):
    """Integrity images for HR: a camera snapshot by number, the photo taken at the start, or the registration photo."""
    from fastapi.responses import FileResponse
    with db.session() as s:
        ctx = ctx_of(req, s)
        rr, a, job = _rr(s, ctx, rrid, "view")
        integ = rr.integrity or {}
        if which == "start":
            key = integ.get("start_photo")
        elif which == "registration":
            c = s.get(db.Candidate, a.candidate_id)
            key = c.photo_file if c else None
        else:
            snaps = integ.get("snapshots") or []
            try:
                key = snaps[int(which)]["file"]
            except (ValueError, IndexError, KeyError, TypeError):
                key = None
    if not key:
        raise HTTPException(404, "No image")
    import asyncio as _a
    p = await _a.to_thread(store.get_file, key)
    if not p:
        raise HTTPException(404, "Image not found in storage")
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


# ---------------------------------------------------------------------------
# messages
# ---------------------------------------------------------------------------
@router.get("/api/candidates/{cid}/messages")
def candidate_messages(cid: str, req: Request):
    from .api_hiring import get_candidate
    with db.session() as s:
        ctx = ctx_of(req, s)
        c = get_candidate(s, ctx, cid)
        return [_msg_json(m) for m in s.query(db.Message).filter(db.Message.candidate_id == c.id).order_by(db.Message.created_at.desc()).limit(100)]


@router.post("/api/messages/{mid}/retry")
def retry_message(mid: str, req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "resend messages")
        m = messages.retry(s, mid, ctx.org_id)
        if not m:
            raise HTTPException(404, "Message not found")
        return _msg_json(m)


@router.get("/api/messages")
def outbox(req: Request, status: str = "", page: int = 1):
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "see the outbox")
        q = s.query(db.Message).filter(db.Message.org_id == ctx.org_id)
        if status:
            q = q.filter(db.Message.status == status)
        total = q.count()
        rows = q.order_by(db.Message.created_at.desc()).offset((max(1, page) - 1) * 50).limit(50).all()
        return {"total": total, "items": [_msg_json(m) for m in rows], "channels": messages.status()}


# ---------------------------------------------------------------------------
# reports and the audit log
# ---------------------------------------------------------------------------
@router.get("/api/reports")
def hiring_reports(req: Request, job: str = "", days: int = 0):
    from . import reports
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "see reports")
        j = get_job(s, ctx, job)[0] if job else None
        return {**reports.build(s, ctx.org_id, auth.visible_job_ids(s, ctx), j, max(0, min(3650, days))),
                "job": {"id": j.id, "title": j.title} if j else None}


@router.get("/api/audit")
def audit_log(req: Request, page: int = 1, action: str = "", user: str = "", q: str = ""):
    """Everything people (and the system) did in this company, newest first. Owners and admins only."""
    from .api_hiring import activity_rows
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_TEAM, "see the audit log")
        qry = s.query(db.Activity).filter(db.Activity.org_id == ctx.org_id)
        if action:
            qry = qry.filter(db.Activity.action == action)
        if user:
            qry = qry.filter(db.Activity.user_id.is_(None) if user == "system" else db.Activity.user_id == user)
        if q.strip():
            qry = qry.filter(db.Activity.detail.ilike(f"%{q.strip()}%"))
        total = qry.count()
        page = max(1, page)
        rows = activity_rows(s, qry, 100, (page - 1) * 100)
        actions = [a for (a,) in s.query(db.Activity.action).filter(db.Activity.org_id == ctx.org_id).distinct().order_by(db.Activity.action)]
        return {"total": total, "items": rows, "actions": actions, "users": _team(s, ctx)}


# ---------------------------------------------------------------------------
# HROne export
# ---------------------------------------------------------------------------
@router.get("/api/hrone/fields")
def hrone_fields(req: Request):
    from . import hrone
    with db.session() as s:
        ctx_of(req, s)
    return {"fields": [{"id": k, "label": v} for k, v in hrone.FIELDS.items()], "default_columns": hrone.DEFAULT_COLUMNS}


@router.get("/api/exports/hrone.xlsx")
def hrone_export(req: Request, job: str = "", ids: str = ""):
    """Selected (offer or hired) candidates as an .xlsx with the company's HROne columns. ids= limits it to some applications."""
    from . import hrone
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "export to HROne")
        q = s.query(db.Application, db.Candidate, db.Job).join(db.Candidate, db.Candidate.id == db.Application.candidate_id) \
            .join(db.Job, db.Job.id == db.Application.job_id).filter(db.Application.org_id == ctx.org_id)
        j = None
        if job:
            j, _ = get_job(s, ctx, job)
            q = q.filter(db.Application.job_id == j.id)
        if ids:
            q = q.filter(db.Application.id.in_([x for x in ids.split(",") if x][:1000]))
        else:
            q = q.filter(db.Application.stage.in_(("offer", "hired")))
        rows = q.order_by(db.Application.decided_at.desc().nullslast()).limit(5000).all()
        if not rows:
            raise HTTPException(404, "No selected candidates to export yet.")
        data = hrone.workbook(org_settings(ctx.org).get("hrone_columns") or [], rows)
        log_activity(s, ctx, "hrone_export", f"{len(rows)} candidate(s)", job_id=j.id if j else None)
        name = hrone.filename(j)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---------------------------------------------------------------------------
# question bank
# ---------------------------------------------------------------------------
@router.get("/api/questions")
def list_questions(req: Request, section: str = "", difficulty: str = "", q: str = "", page: int = 1, limit: int = 50):
    with db.session() as s:
        ctx = ctx_of(req, s)
        qry = s.query(db.Question).filter(db.Question.org_id == ctx.org_id)
        if section:
            qry = qry.filter(db.Question.section == section)
        if difficulty:
            qry = qry.filter(db.Question.difficulty == difficulty)
        if q.strip():
            qry = qry.filter(db.Question.text.ilike(f"%{q.strip()}%"))
        total = qry.count()
        rows = qry.order_by(db.Question.created_at.desc()).offset((max(1, page) - 1) * limit).limit(max(1, min(200, limit))).all()
        stats = {}
        for sec, diff, n in s.query(db.Question.section, db.Question.difficulty, func.count()).filter(db.Question.org_id == ctx.org_id,
                                                                                                    db.Question.active.is_(True)).group_by(db.Question.section, db.Question.difficulty):
            stats.setdefault(sec, {"easy": 0, "medium": 0, "hard": 0})[diff] = n
        answers = ctx.via_key or ctx.has(auth.MANAGE_JOBS)       # answer keys stay with HR
        return {"total": total, "items": [assessments.question_json(x, with_answer=answers) for x in rows], "stats": stats,
                "sections": [{"id": k, "label": v} for k, v in assessments.SECTION_LABEL.items()]}


@router.post("/api/questions")
@offload
async def create_question(req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "edit the question bank")
        items = body.get("questions") if isinstance(body.get("questions"), list) else [body]
        made = []
        for d in items[:200]:
            try:
                q = db.Question(org_id=ctx.org_id, created_by=ctx.user_id, **assessments.clean_question(d))
            except ValueError as e:
                raise HTTPException(400, str(e))
            s.add(q)
            made.append(q)
        s.flush()
        log_activity(s, ctx, "questions_added", f"{len(made)} question(s)")
        return {"created": len(made), "items": [assessments.question_json(q) for q in made]}


@router.patch("/api/questions/{qid}")
@offload
async def update_question(qid: str, req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "edit the question bank")
        q = s.get(db.Question, qid)
        if not q or q.org_id != ctx.org_id:
            raise HTTPException(404, "Question not found")
        if set(body) == {"active"}:
            q.active = bool(body["active"])
        else:
            try:
                d = assessments.clean_question({**assessments.question_json(q), **body})
            except ValueError as e:
                raise HTTPException(400, str(e))
            for k, v in d.items():
                setattr(q, k, v)
            if "active" in body:
                q.active = bool(body["active"])
        return assessments.question_json(q)


@router.delete("/api/questions/{qid}")
def delete_question(qid: str, req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "edit the question bank")
        n = s.query(db.Question).filter_by(id=qid, org_id=ctx.org_id).delete()
        if not n:
            raise HTTPException(404, "Question not found")
    return {"ok": True}


@router.post("/api/questions/import")
async def import_questions(req: Request, file: UploadFile = File(...)):
    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(413, "The file is larger than 5 MB.")
    if not (file.filename or "").lower().endswith((".xlsx", ".xlsm", ".csv")):
        raise HTTPException(400, "Upload an Excel (.xlsx) or CSV file. Download the template for the columns.")
    rows, errors = assessments.parse_import(raw, file.filename or "")
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "edit the question bank")
        for d in rows:
            s.add(db.Question(org_id=ctx.org_id, created_by=ctx.user_id, **d))
        if rows:
            log_activity(s, ctx, "questions_added", f"{len(rows)} imported from {file.filename}")
    return {"created": len(rows), "errors": errors[:50]}


@router.get("/api/questions/template.xlsx")
def question_template(req: Request):
    import openpyxl
    with db.session() as s:
        ctx_of(req, s)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Questions"
    ws.append(["section", "difficulty", "type", "question", "option a", "option b", "option c", "option d", "answer", "marks", "explanation"])
    ws.append(["quantitative", "easy", "single", "A laptop costs Rs 40,000 after a 20% discount. What was the original price?", "48,000", "50,000",
               "52,000", "45,000", "B", 1, "Original x 0.8 = 40,000, so original = 50,000."])
    ws.append(["it_hardware", "medium", "single", "Which component temporarily stores data the CPU is actively using?", "Hard disk", "RAM", "ROM", "GPU",
               "B", 1, "RAM is the working memory."])
    ws.append(["logical", "easy", "numeric", "What comes next: 2, 6, 12, 20, 30, ?", "", "", "", "", "42", 1, "Differences grow by 2: +4 +6 +8 +10 +12."])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="question-bank-template.xlsx"'})


@router.post("/api/questions/draft")
async def draft(req: Request):
    """AI-drafted questions for HR to review; nothing is saved until HR saves them."""
    body = await req.json()
    topic, role = str(body.get("topic") or "")[:300], str(body.get("role") or "")[:120]
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "draft questions")
        if body.get("job_id"):
            # Suggest from a job: its must-have skills, tools and responsibilities become the topic.
            job, _ = get_job(s, ctx, str(body["job_id"]))
            f = job.fields or {}
            parts = [", ".join(f.get("must_have_skills") or []), ", ".join(f.get("tools") or []), "; ".join((f.get("responsibilities") or [])[:5])]
            topic = (topic + " " if topic else "") + " | ".join(p for p in parts if p)
            role = role or job.title
    try:
        items = await assessments.draft_questions(str(body.get("section") or "domain"), topic[:900],
                                                  str(body.get("difficulty") or "medium"), int(body.get("count") or 5), role)
    except Exception as e:
        from .api_hiring import ai_unavailable
        raise HTTPException(503, ai_unavailable(e))
    return {"items": items}


@router.post("/api/questions/sample")
def load_sample_questions(req: Request):
    """A starter bank (quantitative, logical, English, IT hardware, sales awareness) to try tests; editable."""
    from . import question_bank
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "edit the question bank")
        n = question_bank.seed(s, ctx.org_id, ctx.user_id)
        log_activity(s, ctx, "questions_added", f"{n} starter questions")
    return {"created": n}


# ---------------------------------------------------------------------------
# campus drives
# ---------------------------------------------------------------------------
def drive_job_ids(d: db.Drive) -> list[str]:
    """A drive can cover several roles: the first job plus settings["job_ids"]."""
    extra = [x for x in ((d.settings or {}).get("job_ids") or []) if isinstance(x, str)]
    return list(dict.fromkeys([d.job_id, *extra]))


def drive_jobs(s, d: db.Drive) -> list[db.Job]:
    ids = drive_job_ids(d)
    found = {j.id: j for j in s.query(db.Job).filter(db.Job.id.in_(ids))}
    return [found[i] for i in ids if i in found]


def drive_json(d: db.Drive, s=None) -> dict:
    out = {"id": d.id, "job_id": d.job_id, "job_ids": drive_job_ids(d), "college": d.college, "code": d.code, "share_code": d.share_code, "opens_at": d.opens_at,
           "closes_at": d.closes_at, "status": d.status, "settings": d.settings or {}, "created_at": d.created_at,
           "link": f"{flows.base_url()}/drive/{d.code}", "results_link": f"{flows.base_url()}/results/{d.share_code}"}
    if s is not None:
        per = dict(s.query(db.Application.job_id, func.count(db.Application.id)).filter(db.Application.drive_id == d.id).group_by(db.Application.job_id).all())
        out["registered"] = s.query(func.count(func.distinct(db.Application.candidate_id))).filter(db.Application.drive_id == d.id).scalar()
        out["jobs"] = [{"id": j.id, "ref": refs.job_ref(j), "title": j.title, "status": j.status, "registered": per.get(j.id, 0)} for j in drive_jobs(s, d)]
        out["job"] = out["jobs"][0] if out["jobs"] else None
    return out


@router.get("/api/drives")
def all_drives(req: Request):
    """Every campus drive in the company (or in the jobs this person can see), newest first."""
    with db.session() as s:
        ctx = ctx_of(req, s)
        vis = auth.visible_job_ids(s, ctx)
        out = []
        for d in s.query(db.Drive).filter(db.Drive.org_id == ctx.org_id).order_by(db.Drive.created_at.desc()).limit(300):
            if vis is not None and not set(drive_job_ids(d)) & set(vis):
                continue
            out.append(drive_json(d, s))
        return out


@router.get("/api/jobs/{job_id}/drives")
def list_drives(job_id: str, req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        job, _ = get_job(s, ctx, job_id)
        return [drive_json(d, s) for d in s.query(db.Drive).filter(db.Drive.org_id == job.org_id).order_by(db.Drive.created_at.desc())
                if job.id in drive_job_ids(d)]


def _drive_fields(d: db.Drive, body: dict):
    if "college" in body:
        if not str(body["college"]).strip():
            raise HTTPException(400, "College name is required")
        d.college = str(body["college"]).strip()[:200]
    for k in ("opens_at", "closes_at"):
        if k in body:
            v = body[k]
            setattr(d, k, float(v) if isinstance(v, (int, float)) and v > 0 else None)
    if d.opens_at and d.closes_at and d.closes_at <= d.opens_at:
        raise HTTPException(400, "The test window must close after it opens")
    if "status" in body and body["status"] in ("open", "closed"):
        d.status = body["status"]
    if "settings" in body:
        st = body["settings"] or {}
        d.settings = {**(d.settings or {}), "require_photo": st.get("require_photo", True) is not False, "show_scores": bool(st.get("show_scores")),
                      "placement_officer": str(st.get("placement_officer") or "")[:200], "officer_email": str(st.get("officer_email") or "")[:320]}


def _set_drive_jobs(s, ctx, d: db.Drive, keys) -> None:
    """The roles a drive covers (job ids or URL tokens). HR must be able to manage every one of them."""
    jobs = []
    for k in keys or []:
        job, _ = get_job(s, ctx, str(k), "manage")
        if job.status == "closed":
            raise HTTPException(400, f"{job.title} is closed. Reopen it to add it to a drive.")
        if job.id not in [j.id for j in jobs]:
            jobs.append(job)
    if not jobs:
        raise HTTPException(400, "Pick at least one role for the drive.")
    if len(jobs) > 20:
        raise HTTPException(400, "A drive can cover up to 20 roles.")
    d.job_id = jobs[0].id
    d.settings = {**(d.settings or {}), "job_ids": [j.id for j in jobs[1:]]}


@router.post("/api/jobs/{job_id}/drives")
async def create_drive(job_id: str, req: Request):
    body = await req.json()
    return _create_drive(req, body, [job_id, *(body.get("job_ids") or [])])


@router.post("/api/drives")
async def create_drive_multi(req: Request):
    """One drive for a campus, covering one or more roles."""
    body = await req.json()
    return _create_drive(req, body, body.get("job_ids") or [])


def _create_drive(req: Request, body: dict, keys: list) -> dict:
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "create campus drives")
        d = db.Drive(org_id=ctx.org_id, job_id="", college="x", code=secrets.token_urlsafe(8).replace("-", "x").replace("_", "y"),
                     share_code=secrets.token_urlsafe(12), created_by=ctx.user_id, settings={"require_photo": True})
        _set_drive_jobs(s, ctx, d, keys)
        _drive_fields(d, {"settings": {}, **body})
        s.add(d)
        log_activity(s, ctx, "drive_created", f"{d.college} ({len(drive_job_ids(d))} role{'s' if len(drive_job_ids(d)) > 1 else ''})", job_id=d.job_id)
        s.flush()
        return drive_json(d, s)


@router.patch("/api/drives/{did}")
@offload
async def update_drive(did: str, req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = ctx_of(req, s)
        d = s.get(db.Drive, did)
        if not d or d.org_id != ctx.org_id:
            raise HTTPException(404, "Drive not found")
        for jid in drive_job_ids(d):
            if s.get(db.Job, jid):
                get_job(s, ctx, jid, "manage")
        if "job_ids" in body:
            keep = {a for (a,) in s.query(db.Application.job_id).filter(db.Application.drive_id == d.id).distinct()}
            new_keys = list(body.get("job_ids") or [])
            _set_drive_jobs(s, ctx, d, new_keys)
            dropped = keep - set(drive_job_ids(d))
            if dropped:
                names = ", ".join(j.title for j in s.query(db.Job).filter(db.Job.id.in_(dropped)))
                raise HTTPException(400, f"Students already registered for {names}. Close the drive instead of removing that role.")
        _drive_fields(d, body)
        return drive_json(d, s)


@router.delete("/api/drives/{did}")
def delete_drive(did: str, req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        d = s.get(db.Drive, did)
        if not d or d.org_id != ctx.org_id:
            raise HTTPException(404, "Drive not found")
        for jid in drive_job_ids(d):
            if s.get(db.Job, jid):
                get_job(s, ctx, jid, "manage")
        if s.query(db.Application).filter(db.Application.drive_id == d.id).count():
            raise HTTPException(400, "Students have registered through this drive. Close it instead of deleting it.")
        s.delete(d)
    return {"ok": True}


# ---------------------------------------------------------------------------
# interview slots
# ---------------------------------------------------------------------------
@router.get("/api/jobs/{job_id}/rounds/{rid}/slots")
def list_slots(job_id: str, rid: str, req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        job, _ = get_job(s, ctx, job_id)
        rows = s.query(db.Slot).filter(db.Slot.job_id == job.id, db.Slot.round_id == rid, db.Slot.ends_at > time.time() - 86400).order_by(db.Slot.starts_at).all()
        booked = {rr.id: rr for rr in s.query(db.RoundResult).filter(db.RoundResult.id.in_([x.booked_by for x in rows if x.booked_by] or [""]))}
        out = []
        for sl in rows:
            item = scheduling.slot_json(sl, s)
            rr = booked.get(sl.booked_by)
            if rr:
                c = s.get(db.Candidate, rr.candidate_id)
                item["candidate"] = {"name": c.name, "ref": refs.cand_ref(c)} if c else None
                item["status"] = rr.status
            out.append(item)
        return out


@router.post("/api/jobs/{job_id}/rounds/{rid}/slots")
@offload
async def create_slots(job_id: str, rid: str, req: Request):
    """Add availability: either explicit slots, or a series (start, end, minutes per slot, days)."""
    body = await req.json()
    with db.session() as s:
        ctx = ctx_of(req, s)
        job, _ = get_job(s, ctx, job_id, "edit")
        rnd = flows.round_of(job, rid)
        if not rnd or rnd["type"] != "human_interview":
            raise HTTPException(400, "Slots belong to a human interview round")
        mins = int((rnd.get("config") or {}).get("duration_min") or 45)
        for iv in {str(x) for x in [body.get("interviewer_id")] + [sp.get("interviewer_id") for sp in body.get("slots") or [] if isinstance(sp, dict)] if x}:
            if not flows.is_member(s, ctx.org_id, iv):
                raise HTTPException(400, "The interviewer must be a member of your team.")
        made = []
        spans = body.get("slots") or []
        if body.get("series"):
            se = body["series"]
            start, end = float(se["start"]), float(se["end"])
            step = int(se.get("minutes") or mins) * 60
            gap = int(se.get("gap_minutes") or 0) * 60
            t = start
            while t + step <= end and len(spans) < 200:
                spans.append({"starts_at": t, "ends_at": t + step})
                t += step + gap
        for sp in spans[:200]:
            a, b = float(sp["starts_at"]), float(sp.get("ends_at") or float(sp["starts_at"]) + mins * 60)
            if b <= a or a < time.time():
                continue
            iv = str(body.get("interviewer_id") or sp.get("interviewer_id") or ctx.user_id or "") or None
            sl = db.Slot(org_id=ctx.org_id, job_id=job.id, round_id=rid, interviewer_id=iv, starts_at=a, ends_at=b,
                         meeting_url=str(body.get("meeting_url") or sp.get("meeting_url") or "")[:500],
                         location=str(body.get("location") or sp.get("location") or "")[:300])
            s.add(sl)
            made.append(sl)
        s.flush()
        log_activity(s, ctx, "slots_added", f"{rnd['name']}: {len(made)} slot(s)", job_id=job.id)
        return {"created": len(made)}


@router.delete("/api/slots/{sid}")
def delete_slot(sid: str, req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        sl = s.get(db.Slot, sid)
        if not sl or sl.org_id != ctx.org_id:
            raise HTTPException(404, "Slot not found")
        get_job(s, ctx, sl.job_id, "edit")
        if sl.booked_by:
            raise HTTPException(400, "This slot is booked. Ask the candidate to reschedule, or cancel from their profile.")
        s.delete(sl)
    return {"ok": True}


@router.get("/api/my-interviews")
def my_interviews(req: Request):
    """Human interviews booked with me, newest first: prep kit and feedback links."""
    with db.session() as s:
        ctx = ctx_of(req, s)
        slots = s.query(db.Slot).filter(db.Slot.interviewer_id == ctx.user_id, db.Slot.booked_by.isnot(None),
                                        db.Slot.starts_at > time.time() - 14 * 86400).order_by(db.Slot.starts_at).all()
        out = []
        for sl in slots:
            rr = s.get(db.RoundResult, sl.booked_by)
            if not rr:
                continue
            c, job = s.get(db.Candidate, rr.candidate_id), s.get(db.Job, rr.job_id)
            rnd = flows.round_of(job, rr.round_id) or {"name": "Interview"}
            out.append({"round_result_id": rr.id, "status": rr.status, "starts_at": sl.starts_at, "ends_at": sl.ends_at, "meeting_url": sl.meeting_url,
                        "location": sl.location, "round": rnd["name"], "job": job.title, "job_ref": refs.job_ref(job),
                        "candidate": c.name, "candidate_ref": refs.cand_ref(c), "feedback_given": bool((rr.data or {}).get("feedback")),
                        "feedback_link": scheduling.feedback_link(rr)})
        return out


# ---------------------------------------------------------------------------
# accommodations and human-interview requests
# ---------------------------------------------------------------------------
@router.get("/api/requests")
def candidate_requests(req: Request):
    with db.session() as s:
        ctx = ctx_of(req, s)
        auth.require(ctx, auth.MANAGE_JOBS, "see candidate requests")
        rows = s.query(db.Application, db.Candidate, db.Job).join(db.Candidate, db.Candidate.id == db.Application.candidate_id) \
            .join(db.Job, db.Job.id == db.Application.job_id).filter(db.Application.org_id == ctx.org_id) \
            .filter((db.Application.human_requested_at.isnot(None)) | (db.Application.accommodation.isnot(None))).order_by(db.Application.updated_at.desc()).limit(200).all()
        out = []
        for a, c, j in rows:
            acc = a.accommodation or {}
            if a.human_requested_at and not acc.get("human_handled"):
                out.append({"kind": "human", "application_id": a.id, "application_ref": refs.app_ref(a.id), "candidate": c.name, "candidate_ref": refs.cand_ref(c), "job": j.title,
                            "job_ref": refs.job_ref(j), "at": a.human_requested_at, "note": a.human_request_note, "status": "open"})
            if acc.get("request"):
                out.append({"kind": "accommodation", "application_id": a.id, "application_ref": refs.app_ref(a.id), "candidate": c.name, "candidate_ref": refs.cand_ref(c), "job": j.title,
                            "job_ref": refs.job_ref(j), "at": acc.get("requested_at"), "note": acc.get("request"), "status": acc.get("status", "requested"),
                            "extra_time_pct": acc.get("extra_time_pct")})
        return out


@router.post("/api/applications/{aid}/accommodation")
@offload
async def decide_accommodation(aid: str, req: Request):
    body = await req.json()
    with db.session() as s:
        ctx = ctx_of(req, s)
        a, job, _ = _app_and_job(s, ctx, aid, "manage")
        acc = dict(a.accommodation or {})
        st = body.get("status")
        if st not in ("approved", "declined"):
            raise HTTPException(400, "Approve or decline")
        acc.update(status=st, decided_by=ctx.user_id, decided_at=time.time(), hr_note=str(body.get("note") or "")[:500])
        if st == "approved":
            acc["extra_time_pct"] = max(0, min(100, int(body.get("extra_time_pct") or 25)))
        a.accommodation = acc
        text = (f"Your request has been approved{' with ' + str(acc['extra_time_pct']) + '% extra time on tests' if st == 'approved' and acc.get('extra_time_pct') else ''}."
                if st == "approved" else "We're unable to offer this adjustment, but please reply if there's another way we can help.")
        if acc.get("hr_note"):
            text += " " + acc["hr_note"]
        flows.notify_candidate(s, a, "Your accommodation request", text, "accommodation", flows.status_link(a), "Your application")
        log_activity(s, ctx, "accommodation", f"{st}", job_id=job.id, candidate_id=a.candidate_id)
    return {"ok": True}


@router.post("/api/applications/{aid}/human-request")
@offload
async def handle_human_request(aid: str, req: Request):
    """HR handles a request for a human interview: switch the AI round to a human round, or keep the AI round."""
    body = await req.json()
    with db.session() as s:
        ctx = ctx_of(req, s)
        a, job, _ = _app_and_job(s, ctx, aid, "manage")
        acc = dict(a.accommodation or {})
        acc["human_handled"] = {"by": ctx.user_id, "at": time.time(), "action": body.get("action")}
        a.accommodation = acc
        if body.get("action") == "human":
            target = next((r for r in flows.flow_of(job) if r["type"] == "human_interview"), None)
            if not target:
                raise HTTPException(400, "Add a human interview round to this job's flow first.")
            flows.move_to(s, a, job, target["id"], _actor(ctx))
            text = "As you asked, your next interview will be with a member of our team. Please pick a time."
        else:
            text = "Thank you for letting us know. " + str(body.get("note") or "For this role the first round is with our AI interviewer; a person reviews every interview.")
            flows.notify_candidate(s, a, "Your interview request", text, "human_request", flows.status_link(a), "Your application")
        log_activity(s, ctx, "human_request", str(body.get("action")), job_id=job.id, candidate_id=a.candidate_id)
    worker.kick()
    return {"ok": True}


@router.post("/api/jobs/{job_id}/rounds/{rid}/attachment")
async def round_attachment(job_id: str, rid: str, req: Request, file: UploadFile = File(...)):
    """The file candidates download for a practical task (for example an Excel workbook with the brief)."""
    raw = await file.read()
    if len(raw) > 15 * 1024 * 1024:
        raise HTTPException(413, "The file is larger than 15 MB.")
    name = (file.filename or "task").rsplit("/", 1)[-1][:120]
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in name) or "task"
    with db.session() as s:
        ctx = ctx_of(req, s)
        job, _ = get_job(s, ctx, job_id, "edit")
        flow = [dict(r) for r in flows.flow_of(job)]
        rnd = next((r for r in flow if r["id"] == rid), None)
        if not rnd or rnd["type"] != "practical_task":
            raise HTTPException(400, "Attachments belong to a practical task round")
        key = f"{ctx.org_id}/jobs/{job.id}/rounds/{rid}/{safe}"
        store.put_file(key, raw, file.content_type or "application/octet-stream")
        rnd["config"] = {**(rnd.get("config") or {}), "attachment": {"file": key, "name": name}}
        job.flow = flow
        log_activity(s, ctx, "flow_changed", f"{rnd['name']}: task file {name}", job_id=job.id)
        return {"ok": True, "name": name}
