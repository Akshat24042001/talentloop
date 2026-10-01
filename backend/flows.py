"""Hiring flows: the rounds a candidate goes through for one job, and the engine that moves them along.

A job's flow is an ordered list of rounds (job.flow). Each round has a type (see ROUND_TYPES), a pass rule, an
advance mode (automatic or wait for HR), an optional deadline in days and a custom message for candidates.
Every candidate in a round has one RoundResult row: its status, score, data (test paper, video, booking...),
integrity signals and the decision.

Rules the engine keeps:
- The first round is always the application form; it can't be removed.
- Rounds can be added, removed or reordered while a job is live. Candidates already past a point are unaffected;
  a candidate sitting in a removed round continues to the round that now follows that position.
- Integrity flags never reject anyone by themselves: a flagged result always waits for HR.
- Automatic advance moves passing candidates on; with "auto" a result below the pass mark is rejected with a
  respectful closure message, with "hr" it waits for an HR decision either way.
"""
import hashlib
import logging
import os
import secrets
import time

from . import db, messages, refs

log = logging.getLogger("flows")

ROUND_TYPES = {
    "application": {"label": "Application form and knockout questions", "stage": "applied", "candidate": True,
                    "description": "Mandatory details and knockout answers (location, notice period, salary range)."},
    "cv_screening": {"label": "AI CV screening", "stage": "screening", "candidate": False,
                     "description": "Scores and ranks the CV against the job description, with reasons, knockouts and job stability."},
    "test": {"label": "Aptitude and domain test", "stage": "screening", "candidate": True,
             "description": "Proctored test from the question bank, a different random paper for each candidate."},
    "video_intro": {"label": "Video introduction", "stage": "screening", "candidate": True,
                    "description": "A recorded introduction (up to 2 minutes), scored by AI for fluency, clarity, structure and content."},
    "role_task": {"label": "Role task (for example a sales pitch)", "stage": "screening", "candidate": True,
                  "description": "A short recorded task after reading a brief, such as pitching a product."},
    "practical_task": {"label": "Practical task (Excel, take-home)", "stage": "screening", "candidate": True,
                       "description": "Upload-based practical work, reviewed by AI against your rubric."},
    "ai_interview": {"label": "AI first-round interview", "stage": "interview", "candidate": True,
                     "description": "AI voice interview with a scorecard and recommendation."},
    "human_interview": {"label": "Human interview", "stage": "interview", "candidate": True,
                        "description": "Scheduled interview with a manager or panel; candidates book a slot themselves."},
    "manager_approval": {"label": "Manager approval", "stage": "shortlisted", "candidate": False,
                         "description": "One-click Select, Reject or Hold by the hiring manager from a link, no login."},
}
PASS_MODES = ("min_score", "top_n", "hr_review", "auto_pass")
STATUS_LABEL = {"pending": "Not started", "invited": "Invited", "in_progress": "In progress", "submitted": "Waiting for review",
                "passed": "Passed", "failed": "Not progressed", "on_hold": "On hold", "expired": "Missed deadline", "booked": "Slot booked",
                "no_show": "No-show", "skipped": "Skipped", "setting_up": "Preparing"}
OPEN_STATUSES = ("pending", "setting_up", "invited", "in_progress", "booked", "submitted", "on_hold")

DEFAULT_CONFIG = {
    "cv_screening": {"use_ai_report": True},
    "test": {"sections": [{"section": "quantitative", "count": 10, "difficulty": "mixed", "minutes": 12, "cutoff": 40},
                          {"section": "logical", "count": 10, "difficulty": "mixed", "minutes": 12, "cutoff": 40},
                          {"section": "english", "count": 10, "difficulty": "mixed", "minutes": 10, "cutoff": 40}],
             "negative_marking": 0.0, "max_exits": 3, "require_camera": True, "shuffle_options": True, "overall_cutoff": 50},
    "video_intro": {"prompt": "Introduce yourself: your background, what you are good at, and why you want this role.",
                    "max_seconds": 120, "retakes": 1, "prepare_seconds": 30},
    "role_task": {"brief": "", "prompt": "Pitch this offering to a potential customer as if you were on a sales call.",
                  "max_seconds": 120, "retakes": 1, "prepare_seconds": 60},
    "practical_task": {"instructions": "", "rubric": [{"criterion": "Correctness", "weight": 50}, {"criterion": "Clarity and presentation", "weight": 25},
                                                        {"criterion": "Efficiency (formulas, structure)", "weight": 25}],
                       "file_types": ".xlsx,.xls,.csv,.docx,.pdf,.zip,.txt", "attachment": None},
    "ai_interview": {"duration_min": 15, "language": "en", "channel": "web", "max_warnings": 2, "role_play": False, "role_play_brief": ""},
    "human_interview": {"duration_min": 45, "mode": "video", "interviewers": [], "reschedules_allowed": 1, "meeting_url": "", "location": ""},
    "manager_approval": {"approvers": []},
}
DEFAULT_RULE = {"cv_screening": {"mode": "top_n", "value": 25}, "test": {"mode": "min_score", "value": 50}, "video_intro": {"mode": "hr_review", "value": 0},
                "role_task": {"mode": "hr_review", "value": 0}, "practical_task": {"mode": "hr_review", "value": 0},
                "ai_interview": {"mode": "hr_review", "value": 0}, "human_interview": {"mode": "hr_review", "value": 0},
                "manager_approval": {"mode": "hr_review", "value": 0}, "application": {"mode": "auto_pass", "value": 0}}


def new_round(kind: str, name: str = "", **over) -> dict:
    r = {"id": db.new_id(6), "type": kind, "name": name or ROUND_TYPES[kind]["label"], "pass_rule": dict(DEFAULT_RULE[kind]),
         "advance": "auto" if kind in ("application", "test") else "hr", "deadline_days": 3 if ROUND_TYPES[kind]["candidate"] and kind != "application" else None,
         "message": "", "config": {**DEFAULT_CONFIG.get(kind, {})}}
    r.update(over)
    return r


TEMPLATES = {
    "experienced": ("Experienced hire", "Application, AI CV screening, AI first round, manager round, approval",
                    lambda: [new_round("application"), new_round("cv_screening"), new_round("ai_interview"),
                             new_round("human_interview", "Manager round"), new_round("manager_approval")]),
    "campus": ("Campus / fresher", "Registration, aptitude test, video introduction, approval, final round",
               lambda: [new_round("application"), new_round("test"), new_round("video_intro"), new_round("manager_approval"),
                        new_round("human_interview", "Final round")]),
    "sales_fresher": ("Sales fresher", "Aptitude test, video introduction, sales pitch, approval, final round",
                      lambda: [new_round("application"), new_round("test"), new_round("video_intro"), new_round("role_task", "Sales pitch"),
                               new_round("manager_approval"), new_round("human_interview", "Final round")]),
    "admin_executive": ("Admin executive", "AI CV screening, Excel task, interview, approval",
                        lambda: [new_round("application"), new_round("cv_screening"), new_round("practical_task", "Excel task"),
                                 new_round("human_interview", "HR round"), new_round("manager_approval")]),
    "senior": ("Senior hire", "AI CV screening, AI first round, two panel rounds, approval",
               lambda: [new_round("application"), new_round("cv_screening", pass_rule={"mode": "hr_review", "value": 0}),
                        new_round("ai_interview", config={**DEFAULT_CONFIG["ai_interview"], "duration_min": 20}),
                        new_round("human_interview", "Technical panel"), new_round("human_interview", "Leadership round"), new_round("manager_approval")]),
}


def template_rounds(key: str) -> list[dict]:
    return TEMPLATES.get(key, TEMPLATES["experienced"])[2]()


def _num(v, lo: float, hi: float, default: float) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def normalize_flow(rounds: list) -> list[dict]:
    """Validate a flow from the builder: known types, the application first, unique ids, bounded values."""
    out, seen = [], set()
    for r in rounds or []:
        if not isinstance(r, dict) or r.get("type") not in ROUND_TYPES:
            continue
        kind = r["type"]
        if kind == "application" and out:
            continue                               # only one application round, always first
        rid = str(r.get("id") or db.new_id(6))[:24]
        if rid in seen:
            rid = db.new_id(6)
        seen.add(rid)
        rule = r.get("pass_rule") or {}
        mode = rule.get("mode") if rule.get("mode") in PASS_MODES else DEFAULT_RULE[kind]["mode"]
        cfg = {**DEFAULT_CONFIG.get(kind, {}), **(r.get("config") or {})}
        dd = r.get("deadline_days")
        out.append({"id": rid, "type": kind, "name": str(r.get("name") or ROUND_TYPES[kind]["label"])[:80],
                    "pass_rule": {"mode": mode, "value": _num(rule.get("value"), 0, 10000, DEFAULT_RULE[kind]["value"])},
                    "advance": "auto" if r.get("advance") == "auto" else "hr",
                    "deadline_days": None if dd in (None, "", 0) else int(_num(dd, 1, 60, 3)),
                    "message": str(r.get("message") or "")[:1500], "config": cfg})
    if not out or out[0]["type"] != "application":
        out.insert(0, new_round("application"))
    return out


def flow_of(job: db.Job) -> list[dict]:
    if not job.flow:
        job.flow = template_rounds("experienced")
    return job.flow


def round_of(job: db.Job, rid: str | None) -> dict | None:
    return next((r for r in flow_of(job) if r["id"] == rid), None)


def _token() -> tuple[str, str]:
    t = secrets.token_urlsafe(18)
    return t, hashlib.sha256(t.encode()).hexdigest()


def token_hash(t: str) -> str:
    return hashlib.sha256((t or "").encode()).hexdigest()


def base_url() -> str:
    from .vapi_config import public_url
    return (os.getenv("APP_URL") or public_url() or "").rstrip("/")


# ---------------------------------------------------------------------------
# Candidate-facing text
# ---------------------------------------------------------------------------
ROUND_INVITE = {
    "test": "Your next step is an online test{name}. It takes about {minutes} minutes. Use a laptop or phone with a camera in a quiet place.",
    "video_intro": "Your next step is a short video introduction{name}. Record it in your browser; it takes about 5 minutes.",
    "role_task": "Your next step is a short recorded role task{name}. You'll read a brief, then record your answer.",
    "practical_task": "Your next step is a practical task{name}. Download the instructions and upload your work.",
    "ai_interview": "Your next step is a first-round interview with our AI interviewer{name}. It is a voice conversation in your browser, about {minutes} minutes, available any time.",
    "human_interview": "You're invited to an interview{name}. Please pick a time that suits you.",
}


def _cand_contact(s, app: db.Application) -> tuple[db.Candidate, db.Job, db.Org]:
    return s.get(db.Candidate, app.candidate_id), s.get(db.Job, app.job_id), s.get(db.Org, app.org_id)


def notify_candidate(s, app: db.Application, subject: str, text: str, template: str, link: str = "", link_label: str = "Open") -> None:
    c, job, org = _cand_contact(s, app)
    if not c:
        return
    first = (c.name or "there").split()[0]
    body = f"Hi {first},\n\n{text}\n"
    if link:
        body += f"\n{link_label}: {link}\n"
    body += f"\nRole: {job.title}\n\nRegards,\n{org.name} Hiring Team"
    wa = f"Hi {first}, {text} {link_label}: {link}" if link else f"Hi {first}, {text}"
    messages.queue(s, org.id, to_email=c.email, to_phone=c.phone, subject=f"{subject} | {job.title} at {org.name}", body=body,
                   template=template, candidate_id=c.id, application_id=app.id, whatsapp_text=wa)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
STAGE_OF = {k: v["stage"] for k, v in ROUND_TYPES.items()}


def get_result(s, app: db.Application, rid: str) -> db.RoundResult | None:
    return s.query(db.RoundResult).filter_by(application_id=app.id, round_id=rid).first()


def on_applied(s, app: db.Application, job: db.Job, *, knockout_failed: list[str] | None = None, notify: bool = True,
               sourced: bool = False) -> None:
    """A new application: record the application round, then start the next round (or reject on knockouts)."""
    flow = flow_of(job)
    first = flow[0]
    rr = get_result(s, app, first["id"]) or db.RoundResult(org_id=app.org_id, job_id=job.id, application_id=app.id,
                                                           candidate_id=app.candidate_id, round_id=first["id"], round_type="application")
    s.add(rr)
    rr.status, rr.completed_at, rr.data = ("failed" if knockout_failed else "passed"), time.time(), {"pos": 0, "knockouts": knockout_failed or []}
    app.round_id, app.round_status = first["id"], rr.status
    s.flush()
    tok, th = _token()
    app.portal_token_hash, app.portal_token = th, tok
    status_link = f"{base_url()}/status/{tok}"
    if knockout_failed:
        reject(s, app, "Screening questions: " + "; ".join(knockout_failed), actor=None, notify=notify)
        return
    if notify and not sourced:
        notify_candidate(s, app, "Application received", f"Thank you for applying. We have received your application. You can follow its "
                         f"status, ask for a human interview instead of an AI one, or request an accommodation here.", "application_received",
                         status_link, "Your application status")
    advance(s, app, job, actor=None, notify=notify)


def advance(s, app: db.Application, job: db.Job, actor: str | None, notify: bool = True) -> db.RoundResult | None:
    """Move the candidate to the next round after their current one; with none left they are selected."""
    flow = flow_of(job)
    ids = [r["id"] for r in flow]
    cur = app.round_id
    if cur in ids:
        nxt = ids.index(cur) + 1
    else:                                        # their round was removed: continue from its old position
        rr = get_result(s, app, cur) if cur else None
        nxt = int(((rr.data or {}).get("pos") if rr else 0) or 0)
        nxt = max(1, min(nxt, len(flow)))
    if nxt >= len(flow):
        select(s, app, actor, notify=notify)
        return None
    return enter_round(s, app, job, flow[nxt], actor, notify=notify)


def enter_round(s, app: db.Application, job: db.Job, rnd: dict, actor: str | None, notify: bool = True) -> db.RoundResult:
    flow = flow_of(job)
    pos = next((i for i, r in enumerate(flow) if r["id"] == rnd["id"]), 0)
    rr = get_result(s, app, rnd["id"])
    if rr is None:
        rr = db.RoundResult(org_id=app.org_id, job_id=job.id, application_id=app.id, candidate_id=app.candidate_id,
                            round_id=rnd["id"], round_type=rnd["type"])
        s.add(rr)
    rr.status, rr.score, rr.decision, rr.decided_by = "pending", None, "", ""
    rr.data, rr.integrity, rr.started_at, rr.completed_at = {"pos": pos}, None, None, None
    rr.deadline_at = time.time() + rnd["deadline_days"] * 86400 if rnd.get("deadline_days") else None
    app.round_id, app.round_status = rnd["id"], "pending"
    if app.stage not in ("offer", "hired"):
        app.stage = STAGE_OF.get(rnd["type"], app.stage)
    app.updated_at = time.time()
    s.flush()
    _start(s, app, job, rnd, rr, notify)
    app.round_status = rr.status
    _log(s, app, job, actor, "round_started", f"{rnd['name']}")
    return rr


def _start(s, app, job, rnd, rr, notify):
    kind = rnd["type"]
    if kind == "cv_screening":
        from . import screening
        screening.score_application(s, app, job, rnd, rr)
        submit(s, rr, rr.score, None, actor=None)
        return
    if kind == "manager_approval":
        request_manager_approval(s, app, job, rnd, rr, notify)
        return
    if kind == "ai_interview":
        rr.status = "setting_up"                 # plan + interview are created in the background (worker.py)
        return
    tok, th = _token()
    rr.token_hash = th
    rr.data = {**(rr.data or {}), "t": tok}
    rr.status = "invited"
    if notify:
        cfg = rnd.get("config") or {}
        minutes = sum(int(x.get("minutes") or 0) for x in cfg.get("sections", [])) if kind == "test" else cfg.get("duration_min", 15)
        text = ROUND_INVITE.get(kind, "Your next step is ready{name}.").format(name=f" ({rnd['name']})" if rnd["name"] != ROUND_TYPES[kind]["label"] else "",
                                                                                 minutes=minutes or 15)
        if rr.deadline_at:
            text += f" Please complete it by {time.strftime('%d %b %Y', time.localtime(rr.deadline_at))}."
        if rnd.get("message"):
            text += "\n\n" + rnd["message"]
        notify_candidate(s, app, "Your next step", text, f"invite_{kind}", f"{base_url()}/r/{tok}",
                         "Book a slot" if kind == "human_interview" else "Start here")


def invite_link(s, rr: db.RoundResult, renew: bool = False) -> str:
    """The candidate's link for this round. renew=True issues a new one (the previous link stops working)."""
    tok = (rr.data or {}).get("t")
    if renew or not tok:
        tok, th = _token()
        rr.token_hash = th
        rr.data = {**(rr.data or {}), "t": tok}
    return f"{base_url()}/r/{tok}"


def manager_link(rr: db.RoundResult) -> str:
    tok = (rr.data or {}).get("mt")
    return f"{base_url()}/decide/{tok}" if tok else ""


def status_link(app: db.Application) -> str:
    return f"{base_url()}/status/{app.portal_token}" if app.portal_token else ""


def submit(s, rr: db.RoundResult, score: float | None, data: dict | None, actor: str | None) -> None:
    """A result came in (test submitted, video scored, interview scored, CV scored...): apply the round's pass rule."""
    app = s.get(db.Application, rr.application_id)
    job = s.get(db.Job, rr.job_id)
    rnd = round_of(job, rr.round_id) or {"pass_rule": {"mode": "hr_review"}, "advance": "hr", "name": rr.round_type, "type": rr.round_type}
    rr.score = None if score is None else round(float(score), 1)
    if data:
        rr.data = {**(rr.data or {}), **data}
    rr.completed_at = rr.completed_at or time.time()
    rr.status = "submitted"
    flagged = bool((rr.integrity or {}).get("flagged"))
    rule = rnd.get("pass_rule") or {}
    mode, value = rule.get("mode", "hr_review"), float(rule.get("value") or 0)
    suggestion = None
    if mode == "auto_pass":
        suggestion = "pass"
    elif mode == "min_score" and rr.score is not None:
        cut = (rr.data or {}).get("section_cutoff_failed")
        suggestion = "pass" if rr.score >= value and not cut else "fail"
    rr.data = {**(rr.data or {}), "suggestion": suggestion}
    if app.round_id == rr.round_id:
        app.round_status = "submitted"
    if suggestion and rnd.get("advance") == "auto" and not flagged and app.round_id == rr.round_id:
        decide(s, rr, suggestion, actor or "Automatic", reason=f"{'Met' if suggestion == 'pass' else 'Below'} the pass mark ({value:g})"
               if mode == "min_score" else "Automatic")
    else:
        _log(s, app, job, actor, "round_submitted", f"{rnd['name']}: {'score ' + str(rr.score) if rr.score is not None else 'submitted'}"
             + (" (integrity flags: HR review)" if flagged else ""))


def decide(s, rr: db.RoundResult, decision: str, actor: str | None, reason: str = "", notify: bool = True) -> None:
    """HR, a manager or the automatic rule decides a round: pass (next round), fail (rejected) or hold."""
    if decision not in ("pass", "fail", "hold"):
        raise ValueError("decision must be pass, fail or hold")
    app = s.get(db.Application, rr.application_id)
    job = s.get(db.Job, rr.job_id)
    rnd = round_of(job, rr.round_id) or {"name": rr.round_type}
    rr.decision, rr.decided_by = decision, (actor or "")[:200]
    rr.data = {**(rr.data or {}), "reason": reason[:1000]}
    rr.status = {"pass": "passed", "fail": "failed", "hold": "on_hold"}[decision]
    rr.completed_at = rr.completed_at or time.time()
    rr.updated_at = time.time()
    _log(s, app, job, actor, "round_decided", f"{rnd['name']}: {STATUS_LABEL[rr.status]}" + (f" ({reason})" if reason else ""))
    if app.round_id != rr.round_id:
        return                                   # an old round re-decided: no movement
    app.round_status = rr.status
    if decision == "pass":
        advance(s, app, job, actor, notify=notify)
    elif decision == "fail":
        reject(s, app, reason, actor, notify=notify)
    else:
        app.updated_at = time.time()


def move_to(s, app: db.Application, job: db.Job, rid: str, actor: str | None, notify: bool = True) -> db.RoundResult:
    """HR moves a candidate to any round (skip ahead or send back). The round starts fresh."""
    rnd = round_of(job, rid)
    if not rnd:
        raise ValueError("Unknown round")
    if rnd["type"] == "application":
        raise ValueError("Candidates can't be moved back to the application form")
    cur = get_result(s, app, app.round_id) if app.round_id else None
    if cur and cur.status in OPEN_STATUSES and cur.round_id != rid:
        cur.status, cur.decision, cur.decided_by = "skipped", "skip", (actor or "")[:200]
    if app.stage in ("rejected", "withdrawn"):
        app.stage = STAGE_OF.get(rnd["type"], "screening")
    return enter_round(s, app, job, rnd, actor, notify=notify)


def reject(s, app: db.Application, reason: str, actor: str | None, notify: bool = True) -> None:
    job = s.get(db.Job, app.job_id)
    cur = get_result(s, app, app.round_id) if app.round_id else None
    if cur and cur.status in OPEN_STATUSES:
        cur.status, cur.decision = "failed", "fail"
    app.stage, app.round_status, app.decided_at, app.updated_at = "rejected", "failed", time.time(), time.time()
    _log(s, app, job, actor, "rejected", reason or "Not progressed")
    if notify:
        notify_candidate(s, app, "Your application", "Thank you for the time and effort you put into your application. After careful review, "
                         "we won't be moving forward with it for this role. We will keep your profile and may contact you about future openings "
                         "that match. We wish you every success.", "closure")


def select(s, app: db.Application, actor: str | None, notify: bool = True) -> None:
    job = s.get(db.Job, app.job_id)
    app.stage, app.round_status, app.decided_at, app.updated_at = "offer", "passed", time.time(), time.time()
    _log(s, app, job, actor, "selected", "Passed every round")
    if notify:
        notify_candidate(s, app, "Good news", "Congratulations, you have cleared our selection process. Our HR team will contact you shortly "
                         "about the next steps.", "selected")


def withdraw(s, app: db.Application, note: str = "") -> None:
    job = s.get(db.Job, app.job_id)
    cur = get_result(s, app, app.round_id) if app.round_id else None
    if cur and cur.status in OPEN_STATUSES:
        cur.status = "skipped"
    app.stage, app.updated_at = "withdrawn", time.time()
    _log(s, app, job, None, "withdrawn", note or "The candidate withdrew")


def request_manager_approval(s, app, job, rnd, rr, notify=True) -> list[str]:
    """Send the approver(s) a no-login decision link. Returns the links (for HR to copy if messages aren't set up)."""
    approvers = approvers_for(s, job, rnd)
    tok, th = _token()
    rr.manager_token_hash = th
    rr.status = "invited"
    link = f"{base_url()}/decide/{tok}"
    rr.data = {**(rr.data or {}), "mt": tok}
    rr.data = {**(rr.data or {}), "approvers": [a["email"] for a in approvers]}
    c = s.get(db.Candidate, app.candidate_id)
    org = s.get(db.Org, app.org_id)
    if notify:
        for a in approvers:
            messages.queue(s, org.id, to_email=a["email"], to_phone=a.get("phone", ""), subject=f"Decision needed: {c.name} for {job.title}",
                           body=f"Hi {a['name'].split()[0] if a['name'] else 'there'},\n\n{c.name} has cleared the earlier rounds for {job.title}. "
                                f"Please review the one-page summary and choose Select, Reject or Hold. No sign-in needed.\n\n{link}\n\n{org.name} Hiring Team",
                           template="manager_approval", candidate_id=c.id, application_id=app.id,
                           whatsapp_text=f"Decision needed: {c.name} for {job.title}. Review and choose Select, Reject or Hold: {link}")
    rr.data = {**rr.data, "link_sent_at": time.time()}
    return [link]


def approvers_for(s, job: db.Job, rnd: dict) -> list[dict]:
    """Configured approvers (team member ids or emails), else the job's assigned hiring managers, else its creator."""
    out = []
    for a in (rnd.get("config") or {}).get("approvers") or []:
        u = s.get(db.User, a) if isinstance(a, str) and "@" not in a else None
        if u:
            out.append({"name": u.name, "email": u.email})
        elif isinstance(a, str) and "@" in a:
            out.append({"name": "", "email": a.strip().lower()})
    if not out:
        for col, u in s.query(db.JobCollaborator, db.User).join(db.User, db.User.id == db.JobCollaborator.user_id).filter(db.JobCollaborator.job_id == job.id):
            out.append({"name": u.name, "email": u.email})
    if not out and job.created_by:
        u = s.get(db.User, job.created_by)
        if u:
            out.append({"name": u.name, "email": u.email})
    return out


def _log(s, app, job, actor, action, detail):
    c = s.get(db.Candidate, app.candidate_id)
    s.add(db.Activity(org_id=app.org_id, user_id=actor if actor and len(actor) <= 24 and " " not in actor else None, job_id=job.id if job else None,
                      candidate_id=app.candidate_id, action=action, detail=f"{c.name if c else ''}: {detail}"[:2000]))


# ---------------------------------------------------------------------------
# Live flow edits
# ---------------------------------------------------------------------------
def apply_flow_change(s, job: db.Job, new_rounds: list[dict]) -> dict:
    """Save an edited flow. Returns what happened to candidates in removed rounds (they continue from the same
    position on their next decision; open invitations stay valid)."""
    old_ids = {r["id"] for r in flow_of(job)}
    job.flow = normalize_flow(new_rounds)
    new_ids = {r["id"] for r in job.flow}
    removed = old_ids - new_ids
    affected = s.query(db.Application).filter(db.Application.job_id == job.id, db.Application.round_id.in_(removed or {""}),
                                             db.Application.stage.notin_(("rejected", "withdrawn", "offer", "hired"))).count()
    job.updated_at = time.time()
    return {"rounds": len(job.flow), "removed": len(removed), "candidates_in_removed_rounds": affected}


def summary_for(rr: db.RoundResult) -> dict:
    d = rr.data or {}
    return {"id": rr.id, "round_id": rr.round_id, "type": rr.round_type, "status": rr.status, "status_label": STATUS_LABEL.get(rr.status, rr.status),
            "score": rr.score, "decision": rr.decision, "decided_by": rr.decided_by, "reason": d.get("reason", ""),
            "suggestion": d.get("suggestion"), "deadline_at": rr.deadline_at, "started_at": rr.started_at, "completed_at": rr.completed_at,
            "flagged": bool((rr.integrity or {}).get("flagged")), "integrity": rr.integrity or {}, "updated_at": rr.updated_at,
            "candidate_link": f"{base_url()}/r/{d['t']}" if d.get("t") else "", "manager_link": manager_link(rr)}
