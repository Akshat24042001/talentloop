"""Public pages behind private links (no sign-in): the candidate's round page (/r/<token>), their application status
page (/status/<token>), the manager's decision page (/decide/<token>), the interviewer's feedback page
(/feedback/<token>), campus drive registration (/drive/<code>) and the placement officer's results (/results/<code>).

Links are random tokens stored hashed. Answer keys and other candidates' data are never returned.
"""
import asyncio
import json
import time

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response

from . import assessments, auth, db, flows, jd_schema, matching, refs, resumes, scheduling, store, worker
from .api_accounts import org_settings

router = APIRouter()
MAX_VIDEO_BYTES = 80 * 1024 * 1024
MAX_TASK_BYTES = 25 * 1024 * 1024
MAX_PHOTO_BYTES = 3 * 1024 * 1024


def _limit(req: Request, key: str, n: int = 120, per: int = 600):
    auth.rate_limit(f"portal:{key}:{auth.client_ip(req)}", n, per)


def _by_token(s, token: str) -> tuple[db.RoundResult, db.Application, db.Job, db.Org]:
    rr = s.query(db.RoundResult).filter(db.RoundResult.token_hash == flows.token_hash(token)).first() if token else None
    if not rr:
        raise HTTPException(404, "This link is not valid. Use the latest link we sent you, or contact the hiring team.")
    app = s.get(db.Application, rr.application_id)
    job = s.get(db.Job, rr.job_id)
    org = s.get(db.Org, rr.org_id)
    if not app or not job or not org or org.disabled:
        raise HTTPException(404, "This link is no longer available.")
    return rr, app, job, org


def _active(rr: db.RoundResult, app: db.Application):
    if app.stage in ("withdrawn",):
        raise HTTPException(410, "You withdrew this application.")
    if app.stage in flows.CLOSED_STAGES + flows.FINAL_STAGES:
        raise HTTPException(410, "This application is closed. Check your application status page for details.")
    if rr.status in ("failed", "skipped", "passed", "no_show"):
        raise HTTPException(410, "This step is finished. Check your application status page for what's next.")
    if app.round_id != rr.round_id and rr.status not in ("booked",):
        raise HTTPException(410, "This step is finished. Check your application status page for what's next.")
    if rr.status in ("expired",):
        raise HTTPException(410, "The deadline for this step has passed. Please contact the hiring team if you need more time.")


def brand(org: db.Org) -> dict:
    st = org_settings(org)
    return {"name": org.name, "logo_url": st.get("logo_url", ""), "brand_color": st.get("brand_color", "#2848e6"), "slug": org.slug}


def transparency(rnd: dict) -> dict:
    """What the candidate is told about each round: what is measured, how, and who decides."""
    kind = rnd["type"]
    cfg = rnd.get("config") or {}
    if kind == "test":
        return {"measures": [f"{s.get('section', '').replace('_', ' ').title()} ({s.get('count')} questions, {s.get('minutes')} min)" for s in cfg.get("sections", [])],
                "how": ["Answers are marked automatically against the correct answers."
                        + (f" Wrong answers lose {float(cfg.get('negative_marking') or 0):g} of a mark." if cfg.get("negative_marking") else " There is no negative marking."),
                        "Each section has its own timer. You can't go back to an earlier section.",
                        "To keep the test fair we note leaving the test screen or full screen, copy and paste, and take camera snapshots."],
                "human": "Integrity notes never reject anyone on their own: a person reviews every flag."}
    if kind in ("video_intro", "role_task"):
        return {"measures": ["Fluency", "Clarity", "Structure", "Content (what you say)"],
                "how": ["AI listens to what you say and scores each area from 1 to 5.", "It never considers your appearance, accent, gender or background."],
                "human": "A person from the hiring team can watch your video and makes the decision."}
    if kind == "practical_task":
        return {"measures": [r.get("criterion") for r in cfg.get("rubric", []) if r.get("criterion")],
                "how": ["AI reviews your file against these criteria and writes comments."], "human": "The hiring team reviews the work and decides."}
    if kind == "ai_interview":
        return {"measures": ["How well you answer questions about the role and your experience", "How clearly you explain your thinking"],
                "how": ["You talk to an AI assistant, not a person. The interview is recorded and transcribed.",
                        "It asks only job-related questions, and scores what you say against what the role needs, never your face, accent or background.",
                        "It can't make promises about salary, selection or timelines."],
                "human": "A person reviews every interview and makes the decision. You can ask for an interview with a person instead."}
    if kind == "human_interview":
        return {"measures": ["A conversation with the hiring team about the role"], "how": [], "human": "People decide."}
    return {"measures": [], "how": [], "human": ""}


# ---------------------------------------------------------------------------
# round page
# ---------------------------------------------------------------------------
@router.get("/api/r/{token}")
def round_page(token: str, req: Request):
    _limit(req, "get", 300)
    with db.session() as s:
        rr, app, job, org = _by_token(s, token)
        rnd = flows.round_of(job, rr.round_id) or {"type": rr.round_type, "name": rr.round_type, "config": {}}
        c = s.get(db.Candidate, app.candidate_id)
        cfg = rnd.get("config") or {}
        d = rr.data or {}
        out = {"type": rr.round_type, "name": rnd["name"], "status": rr.status, "status_label": flows.STATUS_LABEL.get(rr.status, rr.status),
               "deadline_at": rr.deadline_at, "message": rnd.get("message", ""), "org": brand(org), "job": {"title": job.title},
               "candidate": {"first_name": (c.name or "").split()[0] if c else "", "has_photo": bool(c and c.photo_file)},
               "transparency": transparency(rnd), "finished": rr.status in ("submitted", "passed", "failed", "on_hold", "skipped", "no_show"),
               "current": app.round_id == rr.round_id, "withdrawn": app.stage == "withdrawn", "status_link": flows.status_link(app),
               "closed": app.stage in flows.CLOSED_STAGES + flows.FINAL_STAGES or rr.status in ("failed", "skipped", "no_show"),
               "human_requested": bool(app.human_requested_at), "accommodation": (app.accommodation or {}).get("status")}
        kind = rr.round_type
        if kind == "test":
            out["test"] = {"sections": [{"label": assessments.SECTION_LABEL.get(x.get("section"), x.get("section")), "count": x.get("count"),
                                         "minutes": round(int(x.get("minutes") or 0) * assessments.extra_time_factor(app), 1)} for x in cfg.get("sections", [])],
                           "negative_marking": cfg.get("negative_marking") or 0, "max_exits": cfg.get("max_exits", 3), "require_camera": cfg.get("require_camera", True),
                           "started": bool(d.get("paper")), "sessions_used": int(d.get("sessions", 0)), "max_sessions": assessments.MAX_SESSIONS,
                           "window": _drive_window(s, app), "extra_time": assessments.extra_time_factor(app) > 1}
            if rr.status in ("submitted", "passed", "failed", "on_hold"):
                out["test"]["done"] = True
        elif kind in ("video_intro", "role_task"):
            out["recording"] = {"prompt": cfg.get("prompt", ""), "brief": cfg.get("brief", "") if kind == "role_task" else "",
                                "max_seconds": int(cfg.get("max_seconds") or 120), "retakes": int(cfg.get("retakes") or 0),
                                "prepare_seconds": int(cfg.get("prepare_seconds") or 30), "uploaded": bool(d.get("file"))}
        elif kind == "practical_task":
            att = cfg.get("attachment") or {}
            out["task"] = {"instructions": cfg.get("instructions", ""), "file_types": cfg.get("file_types", ""), "attachment": att.get("name") if att else None,
                           "rubric": [r.get("criterion") for r in cfg.get("rubric", [])], "uploaded": d.get("file_name")}
        elif kind == "ai_interview":
            iid = d.get("interview_id")
            out["interview"] = {"url": f"/interview.html?id={iid}" if iid and rr.status in ("invited", "in_progress") else None,
                                "duration_min": cfg.get("duration_min", 15), "language": cfg.get("language", "en"),
                                "phone_available": _phone_ok() and bool(c and c.phone), "preparing": rr.status == "setting_up"}
        elif kind == "human_interview":
            b = d.get("booking")
            reschedules_left = int(cfg.get("reschedules_allowed", 1)) - int(d.get("reschedules", 0))
            out["interview"] = {"booking": {k: b.get(k) for k in ("starts_at", "ends_at", "location", "interviewer")} | {"has_link": bool(b.get("meeting_url"))} if b else None,
                                "slots": [] if (b and reschedules_left <= 0) else [scheduling.slot_json(x) | {"meeting_url": ""} for x in scheduling.open_slots(s, job.id, rr.round_id)[:60]],
                                "reschedules_left": max(0, reschedules_left), "duration_min": cfg.get("duration_min", 45), "mode": cfg.get("mode", "video")}
        return out


def _phone_ok() -> bool:
    from . import phone
    return phone.enabled()


def _drive_window(s, app: db.Application) -> dict | None:
    if not app.drive_id:
        return None
    d = s.get(db.Drive, app.drive_id)
    if not d:
        return None
    now = time.time()
    return {"opens_at": d.opens_at, "closes_at": d.closes_at, "open": (not d.opens_at or now >= d.opens_at) and (not d.closes_at or now <= d.closes_at)
            and d.status == "open", "college": d.college}


# ---- tests
def _test_rr(s, token: str):
    rr, app, job, org = _by_token(s, token)
    if rr.round_type != "test":
        raise HTTPException(400, "This link is not a test.")
    return rr, app, job, org


def _maybe_roll(s, rr: db.RoundResult) -> None:
    """Move past sections whose time is over; finish the test after the last one."""
    d = dict(rr.data or {})
    while d.get("current") is not None:
        idx = d["current"]
        sec = d["paper"]["sections"][idx]
        started = (d.get("section_started") or {}).get(str(idx))
        if not started or time.time() <= started + sec["minutes"] * 60 * float(d.get("time_factor") or 1) + assessments.GRACE_SEC:
            break
        _next_section(rr, d)
        d = dict(rr.data)
    if (rr.data or {}).get("current") is None and rr.status == "in_progress":
        assessments.finish_test(s, rr, "time_up")


def _next_section(rr: db.RoundResult, d: dict) -> None:
    idx = d["current"]
    if idx + 1 < len(d["paper"]["sections"]):
        d["current"] = idx + 1
        d.setdefault("section_started", {})[str(idx + 1)] = time.time()
    else:
        d["current"] = None
    rr.data = d


@router.post("/api/r/{token}/test/start")
async def test_start(token: str, req: Request, consent: str = Form("0"), photo: UploadFile | None = File(None)):
    _limit(req, "start", 30)
    raw = await photo.read() if photo is not None and photo.filename else None
    if raw and len(raw) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "The photo is too large.")
    with db.session() as s:
        rr, app, job, org = _test_rr(s, token)
        _active(rr, app)
        if rr.status in ("submitted", "passed", "failed", "on_hold"):
            raise HTTPException(409, "You have already submitted this test.")
        win = _drive_window(s, app)
        if win and not win["open"]:
            raise HTTPException(403, "The test window for your college is not open right now." + (
                f" It opens {time.strftime('%d %b, %I:%M %p', time.localtime(win['opens_at']))}." if win.get("opens_at") and time.time() < win["opens_at"] else ""))
        if consent not in ("1", "true", "yes"):
            raise HTTPException(400, "Please accept the consent notice to start.")
        d = dict(rr.data or {})
        if int(d.get("sessions", 0)) >= assessments.MAX_SESSIONS:
            raise HTTPException(403, "You have already resumed this test once. Please contact the hiring team to continue.")
        rnd = flows.round_of(job, rr.round_id) or {"config": flows.DEFAULT_CONFIG["test"]}
        if not d.get("paper"):
            d["paper"] = assessments.build_paper(s, org.id, rnd.get("config") or {}, seed=f"{rr.id}-{app.id}")
            if not d["paper"]["sections"]:
                raise HTTPException(503, "This test isn't ready yet (no questions in the bank). Please contact the hiring team.")
            d.update(current=0, section_started={"0": time.time()}, answers={}, time_factor=assessments.extra_time_factor(app), consent_at=time.time(),
                     consent_ip=auth.client_ip(req))
            rr.started_at = time.time()
        else:                                    # resume: give back the time lost while disconnected (up to 10 minutes)
            gap = min(600.0, max(0.0, time.time() - float(d.get("last_seen") or time.time())))
            cur = d.get("current")
            if cur is not None and gap > 15:
                d.setdefault("section_started", {})[str(cur)] = float(d["section_started"][str(cur)]) + gap
            d.setdefault("resumes", []).append({"at": time.time(), "credited_sec": round(gap)})
        d["sessions"] = int(d.get("sessions", 0)) + 1
        d["last_seen"] = time.time()
        rr.data = d
        rr.status = "in_progress"
        app.round_status = "in_progress"
        if raw:
            key = f"{org.id}/rounds/{rr.id}/start-photo.jpg"
            store.put_file(key, raw, "image/jpeg")
            integ = dict(rr.integrity or {})
            integ["start_photo"] = key
            rr.integrity = integ
        _maybe_roll(s, rr)
        if rr.status != "in_progress":
            return {"done": True}
        return {"section": assessments.section_view(s, rr, rr.data["current"])}


@router.get("/api/r/{token}/test/section")
def test_section(token: str, req: Request):
    _limit(req, "section", 600)
    with db.session() as s:
        rr, app, job, org = _test_rr(s, token)
        if rr.status != "in_progress":
            return {"done": rr.status in ("submitted", "passed", "failed", "on_hold"), "status": rr.status}
        _maybe_roll(s, rr)
        if rr.status != "in_progress" or (rr.data or {}).get("current") is None:
            return {"done": True}
        d = dict(rr.data)
        d["last_seen"] = time.time()
        rr.data = d
        return {"section": assessments.section_view(s, rr, d["current"])}


@router.post("/api/r/{token}/test/answer")
async def test_answer(token: str, req: Request):
    _limit(req, "answer", 2000)
    body = await req.json()
    with db.session() as s:
        rr, app, job, org = _test_rr(s, token)
        if rr.status != "in_progress":
            raise HTTPException(409, "This test is no longer in progress.")
        _maybe_roll(s, rr)
        if rr.status != "in_progress":
            return {"saved": False, "done": True}
        ok = assessments.save_answer(s, rr, int(body.get("section", -1)), str(body.get("qid") or ""), body.get("answer"))
        d = dict(rr.data)
        d["last_seen"] = time.time()
        rr.data = d
        return {"saved": ok}


@router.post("/api/r/{token}/test/next")
def test_next(token: str, req: Request):
    with db.session() as s:
        rr, app, job, org = _test_rr(s, token)
        if rr.status != "in_progress":
            return {"done": True}
        d = dict(rr.data)
        if d.get("current") is not None:
            _next_section(rr, d)
        if rr.data.get("current") is None:
            res = assessments.finish_test(s, rr, "submitted")
            return {"done": True, "result": _candidate_result(rr, job, res)}
        return {"section": assessments.section_view(s, rr, rr.data["current"])}


@router.post("/api/r/{token}/test/submit")
def test_submit(token: str, req: Request):
    with db.session() as s:
        rr, app, job, org = _test_rr(s, token)
        if rr.status != "in_progress":
            return {"done": True}
        d = dict(rr.data)
        d["current"] = None
        rr.data = d
        res = assessments.finish_test(s, rr, "submitted")
        return {"done": True, "result": _candidate_result(rr, job, res)}


def _candidate_result(rr, job, res) -> dict | None:
    """Candidates see their own score only if HR allows it (round config show_score)."""
    cfg = (flows.round_of(job, rr.round_id) or {}).get("config") or {}
    if not cfg.get("show_score"):
        return None
    return {"overall": res["overall"], "sections": [{"label": x["label"], "pct": x["pct"]} for x in res["sections"]]}


@router.post("/api/r/{token}/event")
async def round_event(token: str, req: Request):
    _limit(req, "event", 600)
    body = await req.json()
    with db.session() as s:
        rr, app, job, org = _by_token(s, token)
        if rr.status not in ("in_progress", "invited"):
            return {"ok": True}
        res = assessments.record_event(s, rr, str(body.get("type") or "")[:30], str(body.get("detail") or ""))
        if res["auto_submit"]:
            d = dict(rr.data)
            d["current"] = None
            rr.data = d
            assessments.finish_test(s, rr, "auto_submitted_exits")
            return {**res, "submitted": True}
        return res


@router.post("/api/r/{token}/snapshot")
async def round_snapshot(token: str, req: Request, image: UploadFile = File(...), reason: str = Form("routine")):
    _limit(req, "snap", 200)
    raw = await image.read()
    if len(raw) > MAX_PHOTO_BYTES or not raw.startswith(b"\xff\xd8"):
        raise HTTPException(400, "Snapshots must be JPEG images under 3 MB.")
    with db.session() as s:
        rr, app, job, org = _by_token(s, token)
        if rr.status not in ("invited", "in_progress"):
            return {"ok": True, "kept": False}
        integ = dict(rr.integrity or {})
        snaps = integ.get("snapshots", [])
        if len(snaps) >= 60:
            return {"ok": True, "kept": False}
        key = f"{org.id}/rounds/{rr.id}/snap-{len(snaps) + 1:03d}.jpg"
        store.put_file(key, raw, "image/jpeg")
        snaps.append({"file": key, "t": time.time(), "reason": reason[:30]})
        integ["snapshots"] = snaps
        rr.integrity = integ
        return {"ok": True, "kept": True}


# ---- recordings (video introduction, role task)
@router.post("/api/r/{token}/recording")
async def upload_recording(token: str, req: Request, video: UploadFile = File(...), meta: str = Form("{}")):
    _limit(req, "rec", 20, 3600)
    raw = await video.read()
    if len(raw) > MAX_VIDEO_BYTES:
        raise HTTPException(413, "The recording is too large. Please record again with a shorter answer.")
    if len(raw) < 1000:
        raise HTTPException(400, "The recording is empty. Please try again.")
    try:
        m = json.loads(meta or "{}")
    except json.JSONDecodeError:
        m = {}
    with db.session() as s:
        rr, app, job, org = _by_token(s, token)
        if rr.round_type not in ("video_intro", "role_task"):
            raise HTTPException(400, "This link doesn't take a recording.")
        _active(rr, app)
        if (rr.data or {}).get("file"):
            raise HTTPException(409, "You have already submitted your recording.")
        ext = ".mp4" if (video.content_type or "").endswith("mp4") else ".webm"
        key = f"{org.id}/rounds/{rr.id}/recording{ext}"
        store.put_file(key, raw, video.content_type or "video/webm")
        rr.data = {**(rr.data or {}), "file": key, "file_name": f"{rr.round_type}{ext}", "duration": float(m.get("duration") or 0),
                   "browser_transcript": str(m.get("transcript") or "")[:20000], "attempts": int(m.get("attempts") or 1), "scoring": "queued",
                   "consent_at": time.time()}
        rr.started_at = rr.started_at or time.time()
        rr.status, rr.completed_at = "submitted", time.time()
        app.round_status = "submitted"
        flows._log(s, app, job, None, "round_submitted", f"{rr.round_type.replace('_', ' ')} recorded")
    worker.kick()
    return {"ok": True}


# ---- practical task
@router.get("/api/r/{token}/attachment")
def task_attachment(token: str, req: Request):
    with db.session() as s:
        rr, app, job, org = _by_token(s, token)
        att = ((flows.round_of(job, rr.round_id) or {}).get("config") or {}).get("attachment") or {}
    if not att.get("file"):
        raise HTTPException(404, "No file for this task")
    p = store.get_file(att["file"])
    if not p:
        raise HTTPException(404, "File not found")
    return FileResponse(p, filename=att.get("name") or "task")


@router.post("/api/r/{token}/upload")
async def task_upload(token: str, req: Request, file: UploadFile = File(...), note: str = Form("")):
    _limit(req, "upload", 20, 3600)
    raw = await file.read()
    if len(raw) > MAX_TASK_BYTES:
        raise HTTPException(413, "The file is larger than 25 MB.")
    with db.session() as s:
        rr, app, job, org = _by_token(s, token)
        if rr.round_type != "practical_task":
            raise HTTPException(400, "This link doesn't take an upload.")
        _active(rr, app)
        if (rr.data or {}).get("file"):
            raise HTTPException(409, "You have already submitted this task.")
        cfg = (flows.round_of(job, rr.round_id) or {}).get("config") or {}
        allowed = [x.strip().lower() for x in str(cfg.get("file_types") or "").split(",") if x.strip()]
        name = (file.filename or "submission").rsplit("/", 1)[-1][:120]
        ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
        if allowed and ext not in allowed:
            raise HTTPException(400, f"Please upload one of: {', '.join(allowed)}")
        key = f"{org.id}/rounds/{rr.id}/submission{ext}"
        store.put_file(key, raw, file.content_type or "application/octet-stream")
        rr.data = {**(rr.data or {}), "file": key, "file_name": name, "note": note[:2000], "scoring": "queued", "uploaded_at": time.time()}
        rr.started_at = rr.started_at or time.time()
        rr.status, rr.completed_at = "submitted", time.time()
        app.round_status = "submitted"
        flows._log(s, app, job, None, "round_submitted", f"practical task uploaded ({name})")
    worker.kick()
    return {"ok": True}


# ---- human interview booking
@router.post("/api/r/{token}/book")
async def book_slot(token: str, req: Request):
    _limit(req, "book", 30)
    body = await req.json()
    with db.session() as s:
        rr, app, job, org = _by_token(s, token)
        if rr.round_type != "human_interview":
            raise HTTPException(400, "This link is not for booking.")
        _active(rr, app)
        try:
            sl = scheduling.book(s, rr, str(body.get("slot_id") or ""))
        except ValueError as e:
            raise HTTPException(409, str(e))
        return {"ok": True, "starts_at": sl.starts_at}


@router.get("/api/r/{token}/join")
def join_meeting(token: str, req: Request):
    with db.session() as s:
        rr, app, job, org = _by_token(s, token)
        if ((rr.data or {}).get("booking") or {}).get("cancelled_at") or app.stage in flows.CLOSED_STAGES:
            raise HTTPException(410, "This interview was cancelled. Check your application status page.")
        url = scheduling.mark_joined(s, rr)
    if not url:
        raise HTTPException(404, "No meeting link for this interview.")
    return RedirectResponse(url, status_code=302)


@router.get("/api/r/{token}/calendar.ics")
def booking_ics(token: str):
    with db.session() as s:
        rr, app, job, org = _by_token(s, token)
        b = (rr.data or {}).get("booking")
        if not b or b.get("cancelled_at"):
            raise HTTPException(404, "Nothing booked")
        rnd = flows.round_of(job, rr.round_id) or {"name": "Interview"}
        cal = scheduling.ics(rr.id, b["starts_at"], b["ends_at"], f"{rnd['name']}: {job.title} at {org.name}", "Your interview",
                             f"{flows.invite_link(s, rr)}/join" if b.get("meeting_url") else b.get("location", ""))
    return Response(cal, media_type="text/calendar", headers={"Content-Disposition": 'attachment; filename="interview.ics"'})


# ---- transparency actions on a round
@router.post("/api/r/{token}/request-human")
async def request_human(token: str, req: Request):
    _limit(req, "human", 10, 3600)
    body = await req.json() if (await req.body()) else {}
    with db.session() as s:
        rr, app, job, org = _by_token(s, token)
        _request_human(s, app, job, str(body.get("note") or ""))
    return {"ok": True}


def _request_human(s, app: db.Application, job: db.Job, note: str):
    if app.human_requested_at:
        return
    app.human_requested_at, app.human_request_note = time.time(), note[:1000]
    app.updated_at = time.time()
    flows._log(s, app, job, None, "human_requested", f"Asked for a human interview{': ' + note[:200] if note else ''}")
    from . import messages
    for a in flows.approvers_for(s, job, {"config": {}}):
        messages.queue(s, app.org_id, to_email=a["email"], subject=f"A candidate asked for a human interview | {job.title}",
                       body=f"A candidate for {job.title} asked to be interviewed by a person instead of the AI interviewer.\n\n"
                            f"Note: {note or '(none)'}\n\nOpen TalentLoop > Requests to switch them to a human round or reply.", template="human_request_hr")


@router.post("/api/r/{token}/call-me")
async def call_me(token: str, req: Request):
    """Phone-first interviews: the AI interviewer calls the candidate's phone instead of using the browser."""
    _limit(req, "call", 5, 3600)
    from . import phone
    with db.session() as s:
        rr, app, job, org = _by_token(s, token)
        if rr.round_type != "ai_interview":
            raise HTTPException(400, "This link is not an AI interview.")
        _active(rr, app)
        iid = (rr.data or {}).get("interview_id")
        c = s.get(db.Candidate, app.candidate_id)
        number = c.phone if c else ""
    if not phone.enabled():
        raise HTTPException(503, "Phone interviews aren't set up. Please take the interview in your browser.")
    if not iid or not number:
        raise HTTPException(400, "We don't have a phone number for you. Please take the interview in your browser.")
    try:
        await phone.call_candidate(iid, number)
    except phone.PhoneError as e:
        raise HTTPException(e.status, str(e))
    return {"ok": True, "number": number[-4:]}


# ---------------------------------------------------------------------------
# application status page
# ---------------------------------------------------------------------------
def _by_portal(s, token: str) -> tuple[db.Application, db.Job, db.Org, db.Candidate]:
    app = s.query(db.Application).filter(db.Application.portal_token_hash == flows.token_hash(token)).first() if token else None
    if not app:
        raise HTTPException(404, "This link is not valid. Use the latest link we sent you.")
    job, org, c = s.get(db.Job, app.job_id), s.get(db.Org, app.org_id), s.get(db.Candidate, app.candidate_id)
    if not job or not org or not c:
        raise HTTPException(404, "This application is no longer available.")
    return app, job, org, c


CAND_STAGE = {"applied": "Application received", "screening": "Being assessed", "shortlisted": "Shortlisted", "interview": "Interviews",
              "offer": "Selected", "hired": "Hired", "rejected": "Not progressed", "withdrawn": "Withdrawn"}


@router.get("/api/status/{token}")
def status_page(token: str, req: Request):
    _limit(req, "status", 300)
    with db.session() as s:
        app, job, org, c = _by_portal(s, token)
        rrs = {rr.round_id: rr for rr in s.query(db.RoundResult).filter_by(application_id=app.id)}
        steps = []
        for r in flows.flow_of(job):
            if r["type"] == "manager_approval":
                label = "Hiring manager review"
            else:
                label = r["name"]
            rr = rrs.get(r["id"])
            st = rr.status if rr else "upcoming"
            link = flows.invite_link(s, rr) if rr and app.round_id == r["id"] and r["type"] not in ("cv_screening", "manager_approval", "application") \
                and st in ("invited", "in_progress", "booked") else None
            steps.append({"name": label, "type": r["type"], "status": st, "label": flows.STATUS_LABEL.get(st, "Upcoming") if st != "upcoming" else "Upcoming",
                          "current": app.round_id == r["id"], "link": link, "transparency": transparency(r) if ROUND_FACING(r) else None})
        return {"org": brand(org), "job": {"title": job.title, "ref": refs.job_ref(job)}, "candidate": {"name": c.name, "email": c.email},
                "stage": app.stage, "stage_label": CAND_STAGE.get(app.stage, app.stage), "applied_at": app.created_at, "steps": steps,
                "human_requested": bool(app.human_requested_at), "accommodation": app.accommodation or None,
                "has_ai_round": any(r["type"] == "ai_interview" for r in flows.flow_of(job)),
                "contact": (job.fields or {}).get("recruiter_contact") or ""}


def ROUND_FACING(r: dict) -> bool:          # noqa: N802
    return r["type"] in ("test", "video_intro", "role_task", "practical_task", "ai_interview")


@router.post("/api/status/{token}/accommodation")
async def request_accommodation(token: str, req: Request):
    _limit(req, "acc", 10, 3600)
    body = await req.json()
    text = str(body.get("request") or "").strip()
    if len(text) < 5:
        raise HTTPException(400, "Please describe what you need.")
    with db.session() as s:
        app, job, org, c = _by_portal(s, token)
        cur = app.accommodation or {}
        if cur.get("request") and cur.get("status") in ("requested", "approved"):
            raise HTTPException(409, "You already have a request with the hiring team. Please contact them to change it.")
        app.accommodation = {**{k: v for k, v in cur.items() if k == "human_handled"}, "request": text[:1500], "requested_at": time.time(), "status": "requested"}
        app.updated_at = time.time()
        flows._log(s, app, job, None, "accommodation_requested", text[:200])
    return {"ok": True}


@router.post("/api/status/{token}/human")
async def status_request_human(token: str, req: Request):
    body = await req.json() if (await req.body()) else {}
    with db.session() as s:
        app, job, org, c = _by_portal(s, token)
        _request_human(s, app, job, str(body.get("note") or ""))
    return {"ok": True}


@router.post("/api/status/{token}/withdraw")
def withdraw(token: str, req: Request):
    with db.session() as s:
        app, job, org, c = _by_portal(s, token)
        if app.stage in ("hired",):
            raise HTTPException(400, "Please contact the hiring team.")
        flows.withdraw(s, app, "Withdrew from the status page")
    return {"ok": True}


@router.post("/api/status/{token}/delete")
async def delete_my_data(token: str, req: Request):
    """The candidate erases their data: profile, resume, applications, recordings and interview records."""
    _limit(req, "del", 5, 3600)
    body = await req.json()
    if str(body.get("confirm") or "").strip().upper() != "DELETE":
        raise HTTPException(400, "Type DELETE to confirm.")
    with db.session() as s:
        app, job, org, c = _by_portal(s, token)
        org_id, cid = org.id, c.id
    from .api_hiring import erase_candidate
    erase_candidate(org_id, cid, by="the candidate (self-service)")
    return {"ok": True}


# ---------------------------------------------------------------------------
# manager decision page
# ---------------------------------------------------------------------------
def _by_manager(s, token: str) -> tuple[db.RoundResult, db.Application, db.Job, db.Org, db.Candidate]:
    rr = s.query(db.RoundResult).filter(db.RoundResult.manager_token_hash == flows.token_hash(token)).first() if token else None
    if not rr:
        raise HTTPException(404, "This link is not valid or has been replaced by a newer one.")
    app, job, org = s.get(db.Application, rr.application_id), s.get(db.Job, rr.job_id), s.get(db.Org, rr.org_id)
    c = s.get(db.Candidate, app.candidate_id) if app else None
    if not (app and job and org and c):
        raise HTTPException(404, "This candidate is no longer available.")
    return rr, app, job, org, c


def one_page(s, app, job, c) -> dict:
    ev = scheduling.evidence(s, app)
    return {"candidate": {"name": c.name, "headline": c.headline, "location": c.location, "years": c.years, "notice_days": c.notice_days,
                          "expected_salary": c.expected_salary, "current_company": c.current_company, "college": c.college,
                          "skills": (c.features or {}).get("skills", [])[:20], "has_resume": bool(c.resume_file)},
            "job": {"title": job.title, "department": job.department}, "rounds": ev["rounds"], "notes": app.notes, "rating": app.rating}


@router.get("/api/decide/{token}")
def manager_page(token: str, req: Request):
    _limit(req, "decide", 120)
    with db.session() as s:
        rr, app, job, org, c = _by_manager(s, token)
        if rr.round_type != "manager_approval":
            raise HTTPException(404, "This link is not a decision link.")
        return {"org": brand(org), **one_page(s, app, job, c), "status": rr.status, "decision": rr.decision, "decided_by": rr.decided_by,
                "reason": (rr.data or {}).get("reason", ""), "decided": rr.status in ("passed", "failed", "on_hold") and app.round_id != rr.round_id or rr.decision in ("pass", "fail"),
                "current": app.round_id == rr.round_id, "approvers": (rr.data or {}).get("approvers", [])}


@router.post("/api/decide/{token}")
async def manager_decide(token: str, req: Request):
    _limit(req, "decide-post", 30)
    body = await req.json()
    choice = {"select": "pass", "reject": "fail", "hold": "hold"}.get(str(body.get("decision") or ""))
    if not choice:
        raise HTTPException(400, "Choose Select, Reject or Hold.")
    reason = str(body.get("reason") or "").strip()
    if choice in ("fail", "hold") and len(reason) < 3:
        raise HTTPException(400, "Please add a short reason.")
    with db.session() as s:
        rr, app, job, org, c = _by_manager(s, token)
        if rr.round_type != "manager_approval":
            raise HTTPException(404, "This link is not a decision link.")
        if app.round_id != rr.round_id or rr.status in ("passed", "failed") or app.stage in flows.CLOSED_STAGES + flows.FINAL_STAGES:
            raise HTTPException(409, "A decision has already been recorded for this candidate.")
        who = str(body.get("name") or "").strip()[:100] or ", ".join((rr.data or {}).get("approvers", [])[:1]) or "Manager"
        flows.decide(s, rr, choice, f"{who} (decision link)", reason)
    worker.kick()
    return {"ok": True}


@router.get("/api/decide/{token}/resume")
def manager_resume(token: str):
    with db.session() as s:
        rr, app, job, org, c = _by_manager(s, token)
        key, name = c.resume_file, c.resume_name
    if not key:
        raise HTTPException(404, "No resume")
    p = store.get_file(key)
    if not p:
        raise HTTPException(404, "Resume not found")
    return FileResponse(p, content_disposition_type="inline", filename=name or "resume")


# ---------------------------------------------------------------------------
# interviewer feedback page
# ---------------------------------------------------------------------------
@router.get("/api/feedback/{token}")
async def interviewer_page(token: str, req: Request):
    _limit(req, "fb", 120)
    with db.session() as s:
        rr, app, job, org, c = _by_manager(s, token)
        if rr.round_type != "human_interview":
            raise HTTPException(404, "This link is not a feedback link.")
        rnd = flows.round_of(job, rr.round_id) or {"name": "Interview"}
        out = {"org": brand(org), **one_page(s, app, job, c), "round": rnd["name"], "booking": (rr.data or {}).get("booking"),
               "feedback": (rr.data or {}).get("feedback"), "status": rr.status, "rr_id": rr.id}
    out["prep_kit"] = await scheduling.prep_kit(out.pop("rr_id"))
    return out


@router.post("/api/feedback/{token}")
async def interviewer_feedback(token: str, req: Request, data: str = Form(...), recording: UploadFile | None = File(None)):
    _limit(req, "fb-post", 20)
    try:
        body = json.loads(data)
    except json.JSONDecodeError:
        raise HTTPException(400, "Bad form data")
    raw = await recording.read() if recording is not None and recording.filename else None
    if raw and len(raw) > MAX_VIDEO_BYTES:
        raise HTTPException(413, "The recording is too large (max 80 MB).")
    with db.session() as s:
        rr, app, job, org, c = _by_manager(s, token)
        if rr.round_type != "human_interview":
            raise HTTPException(404, "This link is not a feedback link.")
        if (rr.data or {}).get("feedback"):
            raise HTTPException(409, "Feedback has already been submitted.")
        rec_key = ""
        if raw:
            rec_key = f"{org.id}/rounds/{rr.id}/interview-recording{'.mp3' if (recording.filename or '').lower().endswith('.mp3') else '.webm'}"
            store.put_file(rec_key, raw, recording.content_type or "audio/webm")
    notes = str(body.get("notes") or "")
    transcript = ""
    if rec_key:
        try:
            p = store.get_file(rec_key)
            transcript = await assessments.transcribe(str(p)) if p else ""
        except Exception:
            transcript = ""
    summary = await scheduling.summarise_notes((notes + "\n\nTranscript:\n" + transcript).strip())
    dec = str(body.get("decision") or "hold")
    if dec not in ("pass", "fail", "hold"):
        raise HTTPException(400, "Choose Select, Reject or Hold.")
    with db.session() as s:
        rr, app, job, org, c = _by_manager(s, token)
        scheduling.record_feedback(s, rr, str(body.get("name") or "Interviewer")[:100], dec, body.get("rating"), notes,
                                   body.get("attended", True) is not False, summary, rec_key)
        if transcript:
            rr.data = {**rr.data, "feedback": {**rr.data["feedback"], "transcript": transcript[:20000]}}
    worker.kick()
    return {"ok": True}


# ---------------------------------------------------------------------------
# campus drives
# ---------------------------------------------------------------------------
@router.get("/api/drive/{code}")
def drive_page(code: str, req: Request):
    _limit(req, "drive", 300)
    with db.session() as s:
        from .api_flows import drive_jobs
        d = s.query(db.Drive).filter_by(code=code).first()
        if not d:
            raise HTTPException(404, "This drive link is not valid.")
        org = s.get(db.Org, d.org_id)
        jobs = [j for j in drive_jobs(s, d) if j.status != "closed"]
        if not org or org.disabled or not drive_jobs(s, d):
            raise HTTPException(404, "This drive link is not valid.")
        st = org_settings(org)
        roles = []
        for j in jobs:
            jd = jd_schema.compose(j.fields or {}, org.name, st, public=True)
            roles.append({"key": refs.job_ref(j), "title": j.title, "facts": jd["facts"], "summary": (j.fields or {}).get("summary", ""),
                          "questions": [{k: q.get(k) for k in ("id", "question", "kind", "required")} for q in (j.fields or {}).get("screening_questions") or []]})
        now = time.time()
        first = roles[0] if roles else {"title": drive_jobs(s, d)[0].title, "facts": [], "summary": "", "questions": []}
        return {"org": brand(org), "college": d.college, "roles": roles,
                "job": {k: first[k] for k in ("title", "facts", "summary")}, "questions": first["questions"],   # single-role pages and old clients
                "opens_at": d.opens_at, "closes_at": d.closes_at, "registration_open": d.status == "open" and bool(roles) and (not d.closes_at or now <= d.closes_at),
                "test_open": d.status == "open" and (not d.opens_at or now >= d.opens_at) and (not d.closes_at or now <= d.closes_at),
                "require_photo": (d.settings or {}).get("require_photo", True)}


@router.post("/api/drive/{code}/register")
async def drive_register(code: str, req: Request, data: str = Form(...), resume: UploadFile | None = File(None), photo: UploadFile | None = File(None)):
    auth.rate_limit(f"drive-reg:{auth.client_ip(req)}", 40, 3600)      # a college lab shares one IP
    from .api_hiring import check_resume, clean_profile, evaluate_knockouts, upsert_candidate
    try:
        d = json.loads(data or "{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "Bad form data")
    from .api_flows import drive_jobs
    with db.session() as s:
        drive = s.query(db.Drive).filter_by(code=code).first()
        if not drive or drive.status != "open" or (drive.closes_at and time.time() > drive.closes_at):
            raise HTTPException(404, "Registration for this drive is closed.")
        open_jobs = {refs.job_ref(j): j for j in drive_jobs(s, drive) if j.status != "closed"}
        if not open_jobs:
            raise HTTPException(404, "Registration for this drive is closed.")
        picked = [str(k) for k in (d.get("roles") or [])] or (list(open_jobs)[:1] if len(open_jobs) == 1 else [])
        if not picked:
            raise HTTPException(400, "Choose at least one role to apply for.")
        if any(k not in open_jobs for k in picked):
            raise HTTPException(400, "One of the roles you picked is no longer open. Refresh the page and choose again.")
        need_photo = (drive.settings or {}).get("require_photo", True)
        drive_id, org_id, college = drive.id, drive.org_id, drive.college
        targets = [(k, open_jobs[k].id, open_jobs[k].title, (open_jobs[k].fields or {}).get("screening_questions") or []) for k in dict.fromkeys(picked)]
    profile = clean_profile({**d, "college": college})
    for k, label in (("name", "Name"), ("email", "Email"), ("phone", "Phone"), ("degree", "Degree"), ("graduation_year", "Year of passing")):
        if not profile.get(k):
            raise HTTPException(400, f"{label} is required.")
    auth.norm_email(profile["email"])
    if not d.get("consent"):
        raise HTTPException(400, "Please accept the consent notice.")
    raw = None
    text = ""
    if resume is not None and resume.filename:
        raw = await resume.read()
        check_resume(raw, resume.filename)
        text = await asyncio.to_thread(resumes.extract_text, raw, resume.filename)
    pic = await photo.read() if photo is not None and photo.filename else None
    if need_photo and not pic:
        raise HTTPException(400, "Please take a live photo with your camera.")
    if pic and (len(pic) > MAX_PHOTO_BYTES or not pic.startswith(b"\xff\xd8")):
        raise HTTPException(400, "The photo must be a JPEG under 3 MB.")
    raw_answers = d.get("answers") or {}
    per_role = {}
    for key, _jid, title, questions in targets:
        a_ = raw_answers.get(key) if isinstance(raw_answers.get(key), dict) else raw_answers   # per role, or one set (single role)
        answers = {str(k): v for k, v in (a_ or {}).items() if not isinstance(v, dict)}
        missing, failed = evaluate_knockouts(questions, answers)
        if missing:
            raise HTTPException(400, (f"For {title}, please answer: " if len(targets) > 1 else "Please answer: ") + "; ".join(missing))
        per_role[key] = (answers, failed)
    full = (text + "\n" + resumes.profile_text(profile) + f"\n{profile.get('degree', '')} {d.get('branch', '')} {college}").strip()
    with db.session() as s:
        cand, created = upsert_candidate(s, org_id, text=full, parsed=resumes.parse(full), profile={**profile, "branch": str(d.get("branch") or "")[:120],
                                         "cgpa": str(d.get("cgpa") or "")[:10]}, source="campus", raw=raw, filename=resume.filename if raw else "")
        cand.college = college
        if pic:
            key = f"{org_id}/candidates/{cand.id}/photo.jpg"
            store.put_file(key, pic, "image/jpeg")
            cand.photo_file = key
        fresh = [t_ for t_ in targets if not s.query(db.Application).filter_by(job_id=t_[1], candidate_id=cand.id).first()]
        if not fresh:
            raise HTTPException(409, "You have already registered for " + ("this drive." if len(targets) == 1 else "these roles."))
        results = []
        for key, jid, title, _q in fresh:
            answers, failed = per_role[key]
            app = db.Application(org_id=org_id, job_id=jid, candidate_id=cand.id, answers=answers, knockout_failed=failed, stage="applied",
                                 source="campus", drive_id=drive_id)
            s.add(app)
            s.flush()
            flows.on_applied(s, app, s.get(db.Job, jid), knockout_failed=failed)
            s.query(db.Job).filter_by(id=jid).update({db.Job.matched_at: None})
            rr = flows.get_result(s, app, app.round_id) if app.round_id else None
            results.append({"role": title, "next_link": flows.invite_link(s, rr) if rr and rr.status == "invited" and rr.data and rr.data.get("t") else None,
                            "status_link": flows.status_link(app)})
        skipped = [t_[2] for t_ in targets if t_ not in fresh]
    worker.kick()
    return {"ok": True, "next_link": results[0]["next_link"], "status_link": results[0]["status_link"], "roles": results, "already": skipped}


@router.get("/api/results/{share_code}")
def drive_results(share_code: str, req: Request):
    _limit(req, "results", 120)
    with db.session() as s:
        d = s.query(db.Drive).filter_by(share_code=share_code).first()
        if not d:
            raise HTTPException(404, "This results link is not valid.")
        from .api_flows import drive_jobs
        org = s.get(db.Org, d.org_id)
        jobs = {j.id: j for j in drive_jobs(s, d)}
        if not jobs or not org:
            raise HTTPException(404, "This results link is not valid.")
        show = (d.settings or {}).get("show_scores")
        flow = {r["id"]: r for j in jobs.values() for r in flows.flow_of(j)}
        rows = s.query(db.Application, db.Candidate).join(db.Candidate, db.Candidate.id == db.Application.candidate_id).filter(db.Application.drive_id == d.id).all()
        tests = {rr.application_id: rr for rr in s.query(db.RoundResult).filter(db.RoundResult.application_id.in_([a.id for a, _ in rows] or [""]),
                                                                                db.RoundResult.round_type == "test")}
        out = []
        for a, c in rows:
            t = tests.get(a.id)
            out.append({"name": c.name, "role": jobs[a.job_id].title if a.job_id in jobs else "", "stage": CAND_STAGE.get(a.stage, a.stage), "round": (flow.get(a.round_id) or {}).get("name", ""),
                        "round_status": flows.STATUS_LABEL.get(a.round_status, a.round_status or ""), "test_score": t.score if (t and show) else None,
                        "test_taken": bool(t and t.status in ("submitted", "passed", "failed", "on_hold"))})
        out.sort(key=lambda x: (-(x["test_score"] or -1), x["name"]))
        return {"org": brand(org), "college": d.college, "job": " · ".join(j.title for j in jobs.values()), "roles": [j.title for j in jobs.values()],
                "students": out, "show_scores": bool(show),
                "summary": {"registered": len({c.id for _, c in rows}), "applications": len(out), "tested": sum(1 for x in out if x["test_taken"]),
                            "progressed": sum(1 for x in out if x["stage"] in ("Being assessed", "Shortlisted", "Interviews", "Selected", "Hired") and x["test_taken"])}}
