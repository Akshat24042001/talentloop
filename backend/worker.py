"""Background worker for hiring flows: everything that needs AI or time, so no click waits on it.

- AI interview rounds: build the plan from the job and the candidate's resume, create the interview, invite.
- CV screening: the optional AI match report for each screened CV.
- Video introductions, role tasks and practical tasks: transcription and AI scoring after upload.
- Time: missed deadlines, reminders before a deadline, interview reminders, automatic no-shows.

`kick()` runs a pass right away (after a request); the sweeper also calls `tick()` every SWEEP_EVERY_SEC.
"""
import asyncio
import logging
import time

from . import brain, db, flows, interviews, ivindex, llm, matching, messages

log = logging.getLogger("worker")
_running = asyncio.Lock()
REC_TO_LABEL = {"strong_yes": "Strong", "yes": "Strong", "maybe": "Maybe", "no": "No"}


async def setup_ai_interview(rr_id: str) -> None:
    with db.session() as s:
        rr = s.get(db.RoundResult, rr_id)
        if not rr or rr.status != "setting_up":
            return
        app = s.get(db.Application, rr.application_id)
        job = s.get(db.Job, rr.job_id)
        org = s.get(db.Org, rr.org_id)
        c = s.get(db.Candidate, rr.candidate_id)
        rnd = flows.round_of(job, rr.round_id) or {}
        cfg = rnd.get("config") or {}
        qs = list((job.fields or {}).get("ai_interview_questions") or [])
        if cfg.get("role_play") and cfg.get("role_play_brief"):
            qs.append(f"Role-play: I'll play a customer. {cfg['role_play_brief']} Please start the conversation as you would on a real call.")
        inp = {"company": org.name, "role": job.title, "candidate_name": c.name, "duration_min": int(cfg.get("duration_min") or 15),
               "jd": interviews.jd_text(job, org), "resume": c.resume_text or "", "questions": qs, "language": cfg.get("language") or "en"}
        ctx = {"org_id": org.id, "created_by": job.created_by, "job_id": job.id, "candidate_id": c.id, "application_id": app.id,
               "email": c.email, "phone": c.phone, "cfg": cfg, "deadline_at": rr.deadline_at}
    plan = await brain.generate_plan(inp)
    settings = interviews.settings_from({"candidate_email": ctx["email"], "candidate_phone": ctx["phone"], "max_warnings": ctx["cfg"].get("max_warnings", 2),
                                         "language": ctx["cfg"].get("language", "en"), "channel": ctx["cfg"].get("channel", "web")})
    hours = max(24.0, ((ctx["deadline_at"] or time.time() + 3 * 86400) - time.time()) / 3600)
    rec = interviews.create_record(org_id=ctx["org_id"], created_by=ctx["created_by"], job_id=ctx["job_id"], candidate_id=ctx["candidate_id"],
                                   application_id=ctx["application_id"], round_result_id=rr_id, plan=plan, inputs=inp, settings=settings,
                                   expires_hours=hours, lines=await brain.localize_lines(settings.get("language") or "en"))
    with db.session() as s:
        rr = s.get(db.RoundResult, rr_id)
        app = s.get(db.Application, rr.application_id)
        if rr.status != "setting_up":
            return
        link = flows.invite_link(s, rr)
        rr.status = "invited"
        rr.data = {**(rr.data or {}), "interview_id": rec["id"], "plan_source": plan.get("source")}
        if app.round_id == rr.round_id:
            app.round_status = "invited"
        job = s.get(db.Job, rr.job_id)
        rnd = flows.round_of(job, rr.round_id) or {}
        text = flows.ROUND_INVITE["ai_interview"].format(name="", minutes=plan.get("duration_min", 15))
        text += (" Before it starts you'll see what the AI assesses and how. If you prefer, you can ask for an interview with a person instead.")
        if rr.deadline_at:
            text += f" Please take it by {time.strftime('%d %b %Y', time.localtime(rr.deadline_at))}."
        if rnd.get("message"):
            text += "\n\n" + rnd["message"]
        flows.notify_candidate(s, app, "Your next step", text, "invite_ai_interview", link, "Start here")
    log.info("[%s] AI interview round ready (%s plan)", rec["id"], plan.get("source"))


async def screening_report(rr_id: str) -> None:
    """Optional AI match report on a CV screening result (cached like job match reports). Database work runs in a
    thread, and no session is held open while the model writes the report."""
    got = await asyncio.to_thread(_screening_load, rr_id)
    if not got:
        return
    job, c, fake = got
    rep, model, inp, outp = await matching._one_report(job, c, fake, asyncio.Semaphore(1))
    await asyncio.to_thread(_screening_save, rr_id, rep, model, inp, outp)


def _screening_load(rr_id: str):
    with db.session() as s:
        rr = s.get(db.RoundResult, rr_id)
        if not rr or not (rr.data or {}).get("ai_report_wanted") or (rr.data or {}).get("ai_report") or (rr.data or {}).get("ai_report_failed"):
            return None
        job, c = s.get(db.Job, rr.job_id), s.get(db.Candidate, rr.candidate_id)
        if not job or not c:
            return None
        m = s.query(db.Match).filter_by(job_id=job.id, candidate_id=c.id).first()
        if m and m.ai_report and m.ai_hash == matching.report_hash(job, c.content_hash or matching.content_hash(c)):
            rr.data = {**rr.data, "ai_report": m.ai_report}
            return None
        fake = db.Match(job_id=job.id, candidate_id=c.id, breakdown=(m.breakdown if m else None) or (rr.data or {}).get("breakdown") or {},
                        score=(m.score if m else None) or rr.score or 0)
        _ = (job.fields, c.resume_text, c.profile, c.parsed)        # loaded before the session closes
        s.expunge(job), s.expunge(c)
        return job, c, fake


def _screening_save(rr_id: str, rep, model, inp, outp) -> None:
    with db.session() as s:
        rr = s.get(db.RoundResult, rr_id)
        if not rr:
            return
        if rep:
            rr.data = {**(rr.data or {}), "ai_report": rep}
            m = s.query(db.Match).filter_by(job_id=rr.job_id, candidate_id=rr.candidate_id).first()
            if m:
                job, c = s.get(db.Job, rr.job_id), s.get(db.Candidate, rr.candidate_id)
                m.ai_report, m.ai_score, m.ai_model, m.ai_at = rep, rep.get("score"), model, db.now()
                m.ai_hash = matching.report_hash(job, c.content_hash or matching.content_hash(c))
        else:
            rr.data = {**(rr.data or {}), "ai_report_failed": True}
        if model != "mock":
            s.add(db.AIUsage(org_id=rr.org_id, kind="cv_screening", model=model, input_chars=inp, output_chars=outp))


def on_interview_scored(rec: dict) -> None:
    """The AI interview of a flow round finished scoring: feed its result into the round."""
    rid = rec.get("round_result_id")
    if not rid:
        return
    rep = rec.get("report") or {}
    overall = (rep.get("computed") or {}).get("overall")
    with db.session() as s:
        rr = s.get(db.RoundResult, rid)
        if not rr or rr.status in ("passed", "failed"):
            return
        dq = rec.get("disqualified")
        risk = (rec.get("proctoring") or {}).get("risk")
        from . import proctor
        pr = proctor.summary(rec) if rec.get("state") else {}
        counts = pr.get("counts") or {}
        flagged = bool(dq) or pr.get("risk") == "high" or bool(rec.get("liveness_failed")) \
            or any(counts.get(k) for k in ("virtual_camera", "identity_mismatch", "person_changed"))
        rr.integrity = {"flagged": flagged, "risk": pr.get("risk") or risk, "reasons": pr.get("reasons", [])[:6],
                        "disqualified": bool(dq), "warnings": len(rec.get("warnings") or [])}
        if rec.get("consent_declined"):           # said no to recording: HR offers another format
            app = s.get(db.Application, rr.application_id)
            if app and not app.human_requested_at:
                app.human_requested_at, app.human_request_note = time.time(), "Declined to be recorded at the start of the AI interview."
            rr.integrity = {**(rr.integrity or {}), "consent_declined": True}
        score = None if overall is None else round(float(overall) / 5 * 100, 1)
        flows.submit(s, rr, score, {"interview_id": rec["id"], "recommendation": rep.get("recommendation"),
                                    "recommendation_label": REC_TO_LABEL.get(rep.get("recommendation") or "", ""),
                                    "summary": (rep.get("summary") or "")[:1500]}, actor=None)


def on_interview_closed_unused(iid: str) -> None:
    """Hook point kept for symmetry (an unused link expiring is handled by deadlines)."""


def _pending() -> tuple[list, list, list]:
    now = time.time()
    with db.session() as s:
        setup_ids = [r.id for r in s.query(db.RoundResult.id).filter(db.RoundResult.status == "setting_up").limit(10)]
        report_ids = [r.id for r in s.query(db.RoundResult).filter(db.RoundResult.round_type == "cv_screening",
                                                                  db.RoundResult.updated_at > now - 7 * 86400).limit(200)
                      if (r.data or {}).get("ai_report_wanted") and not (r.data or {}).get("ai_report") and not (r.data or {}).get("ai_report_failed")][:10]
        scoring = [(r.id, r.round_type) for r in s.query(db.RoundResult).filter(db.RoundResult.status == "submitted",
                                                                               db.RoundResult.round_type.in_(("video_intro", "role_task", "practical_task", "live_task", "reference_check"))).limit(50)
                   if (r.data or {}).get("scoring") == "queued"][:5]
    return setup_ids, report_ids, scoring


async def tick() -> None:
    """One pass over pending flow work."""
    if _running.locked():
        return
    async with _running:
        setup_ids, report_ids, scoring = await asyncio.to_thread(_pending)
        for rid in setup_ids:
            try:
                await setup_ai_interview(rid)
            except Exception:
                log.exception("[%s] AI interview setup failed", rid)
                with db.session() as s:
                    rr = s.get(db.RoundResult, rid)
                    if rr and rr.status == "setting_up":
                        tries = int((rr.data or {}).get("setup_tries", 0)) + 1
                        rr.data = {**(rr.data or {}), "setup_tries": tries}
                        if tries >= 3:
                            rr.status, rr.data = "submitted", {**rr.data, "setup_error": "Could not prepare the AI interview. Send it from the candidate page."}
        for rid in report_ids:
            try:
                await screening_report(rid)
            except Exception:
                log.exception("[%s] screening report failed", rid)
        if scoring:
            from . import assessments
            for rid, kind in scoring:
                try:
                    await assessments.score_upload(rid)
                except Exception:
                    log.exception("[%s] %s scoring failed", rid, kind)
        await asyncio.to_thread(time_rules)


def time_rules() -> None:
    """Deadlines, reminders, interview reminders and no-shows."""
    now = time.time()
    with db.session() as s:
        open_rr = s.query(db.RoundResult).filter(db.RoundResult.status.in_(("invited", "in_progress", "booked")),
                                                 db.RoundResult.deadline_at.isnot(None)).limit(500).all()
        for rr in open_rr:
            try:
                _deadline(s, rr, now)
            except Exception:
                log.exception("[%s] deadline check failed", rr.id)
        # Tests left open (browser closed mid-test): sections run out on the server clock and the test is scored.
        from .api_portal import _maybe_roll
        for rr in s.query(db.RoundResult).filter(db.RoundResult.round_type == "test", db.RoundResult.status == "in_progress").limit(200).all():
            try:
                if (rr.data or {}).get("paper") and now - float((rr.data or {}).get("last_seen") or 0) > 60:
                    _maybe_roll(s, rr)
            except Exception:
                log.exception("[%s] closing an abandoned test failed", rr.id)
        # Live tasks whose time ran out with the browser closed: submit the autosaved draft and score it.
        for rr in s.query(db.RoundResult).filter(db.RoundResult.round_type == "live_task", db.RoundResult.status == "in_progress").limit(200).all():
            d = rr.data or {}
            try:
                if d.get("live_ends_at") and not d.get("live_submitted_at") and now > float(d["live_ends_at"]) + 120:
                    app = s.get(db.Application, rr.application_id)
                    rr.data = {**d, "live_content": d.get("live_draft", ""), "live_submitted_at": now, "auto": True, "scoring": "queued",
                               "note": "Submitted automatically when the time ran out (the candidate's page was closed)."}
                    rr.status, rr.completed_at = "submitted", now
                    if app and app.round_id == rr.round_id:
                        app.round_status = "submitted"
                        flows._log(s, app, s.get(db.Job, rr.job_id), None, "round_submitted", "live task submitted automatically (time ran out)")
            except Exception:
                log.exception("[%s] closing an abandoned live task failed", rr.id)
        from . import scheduling
        scheduling.reminders_and_no_shows(s, now)


def _deadline(s, rr: db.RoundResult, now: float) -> None:
    """Expire a round past its deadline, or remind the candidate a day before."""
    app = s.get(db.Application, rr.application_id)
    if not app or not s.get(db.Job, rr.job_id) or app.round_id != rr.round_id or app.stage in flows.CLOSED_STAGES + flows.FINAL_STAGES:
        return
    d = rr.data or {}
    if rr.status != "booked" and rr.deadline_at < now:
        if rr.status == "in_progress" and rr.round_type in ("test", "live_task", "reference_check"):
            return                                # tests and live tasks finish on their own timer; referees may answer late
        rr.status = "expired"
        app.round_status = "expired"
        flows._log(s, app, s.get(db.Job, rr.job_id), None, "round_expired", f"{rr.round_type}: deadline passed")
    elif rr.status == "invited" and rr.deadline_at - now < 86400 and not d.get("reminded"):
        rr.data = {**d, "reminded": now}
        job = s.get(db.Job, rr.job_id)
        rnd = flows.round_of(job, rr.round_id) or {"name": rr.round_type}
        link = flows.invite_link(s, rr)          # the same link they already have
        flows.notify_candidate(s, app, "Reminder", f"A reminder that your next step ({rnd['name']}) closes on "
                               f"{time.strftime('%d %b %Y, %H:%M', time.localtime(rr.deadline_at))}.", "reminder", link, "Continue here")


MAIN_LOOP: asyncio.AbstractEventLoop | None = None    # set at startup: kick() may be called from worker threads


def kick() -> None:
    try:
        cur = asyncio.get_running_loop()
    except RuntimeError:
        cur = None
    loop = MAIN_LOOP if MAIN_LOOP is not None and not MAIN_LOOP.is_closed() else cur
    if loop is None:
        return
    if loop is cur:
        loop.call_soon(lambda: asyncio.ensure_future(tick()))
    else:
        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(tick()))
