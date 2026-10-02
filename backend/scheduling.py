"""Human interview rounds: interviewer slots, candidate self-booking, calendar invites, reminders, no-shows,
interviewer prep kits and one-click feedback.

Meeting links go through /api/r/<token>/join, so the platform knows the candidate opened the meeting. A booked
interview with no join and no feedback 30 minutes after it ended is marked a no-show automatically (the interviewer
can correct it). One reschedule is allowed by default (round config `reschedules_allowed`).
"""
import json
import logging
import time
from datetime import datetime, timezone

from . import db, flows, llm, messages

log = logging.getLogger("scheduling")
NO_SHOW_AFTER_SEC = 30 * 60


def slot_json(sl: db.Slot, s=None) -> dict:
    u = s.get(db.User, sl.interviewer_id) if s and sl.interviewer_id else None
    return {"id": sl.id, "starts_at": sl.starts_at, "ends_at": sl.ends_at, "meeting_url": sl.meeting_url, "location": sl.location,
            "interviewer_id": sl.interviewer_id, "interviewer": (u.name or u.email) if u else "", "booked": bool(sl.booked_by), "round_id": sl.round_id}


def open_slots(s, job_id: str, round_id: str) -> list[db.Slot]:
    rows = s.query(db.Slot).filter(db.Slot.job_id == job_id, db.Slot.round_id == round_id, db.Slot.booked_by.is_(None),
                                   db.Slot.starts_at > time.time() + 3600).order_by(db.Slot.starts_at).all()
    ok = {}                                       # an interviewer who left or was switched off can't be booked
    return [x for x in rows if not x.interviewer_id or ok.setdefault(x.interviewer_id, flows.is_member(s, x.org_id, x.interviewer_id))]


def _fmt(ts: float) -> str:
    return time.strftime("%a %d %b %Y, %I:%M %p", time.localtime(ts))


def ics(uid: str, start: float, end: float, summary: str, description: str, location: str, organizer: str = "") -> str:
    def dt(t):
        return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    esc = lambda x: (x or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")  # noqa: E731
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//TalentLoop//Interviews//EN", "METHOD:REQUEST", "BEGIN:VEVENT",
             f"UID:{uid}@talentloop", f"DTSTAMP:{dt(time.time())}", f"DTSTART:{dt(start)}", f"DTEND:{dt(end)}",
             f"SUMMARY:{esc(summary)}", f"DESCRIPTION:{esc(description)}", f"LOCATION:{esc(location)}"]
    if organizer:
        lines.append(f"ORGANIZER:mailto:{organizer}")
    lines += ["BEGIN:VALARM", "TRIGGER:-PT30M", "ACTION:DISPLAY", "DESCRIPTION:Interview in 30 minutes", "END:VALARM", "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines)


def book(s, rr: db.RoundResult, slot_id: str) -> db.Slot:
    """The candidate picks a slot (also used for a reschedule)."""
    sl = s.query(db.Slot).filter_by(id=slot_id, job_id=rr.job_id, round_id=rr.round_id).with_for_update().first()
    if not sl or sl.booked_by:
        raise ValueError("That time was just taken. Please choose another.")
    if sl.starts_at < time.time() + 3600:
        raise ValueError("That time is too soon. Please choose a later slot.")
    job = s.get(db.Job, rr.job_id)
    rnd = flows.round_of(job, rr.round_id) or {"config": {}, "name": "Interview"}
    d = dict(rr.data or {})
    old = d.get("booking") if not (d.get("booking") or {}).get("cancelled_at") else None
    if old:
        allowed = int((rnd.get("config") or {}).get("reschedules_allowed", 1))
        if int(d.get("reschedules", 0)) >= allowed:
            raise ValueError("You can't change the time again from here. Please contact the hiring team." if allowed else
                             "Rescheduling isn't available for this interview. Please contact the hiring team.")
        prev = s.get(db.Slot, old["slot_id"])
        if prev and prev.booked_by == rr.id:
            prev.booked_by = None
        d["reschedules"] = int(d.get("reschedules", 0)) + 1
    sl.booked_by = rr.id
    iv = s.get(db.User, sl.interviewer_id) if sl.interviewer_id else None
    d["booking"] = {"slot_id": sl.id, "starts_at": sl.starts_at, "ends_at": sl.ends_at, "meeting_url": sl.meeting_url or (rnd.get("config") or {}).get("meeting_url", ""),
                    "location": sl.location or (rnd.get("config") or {}).get("location", ""), "interviewer_id": sl.interviewer_id,
                    "interviewer": (iv.name or iv.email) if iv else "", "booked_at": time.time()}
    d.pop("reminded_24h", None)
    d.pop("reminded_1h", None)
    if "mt" not in d:                                 # the interviewer's no-login feedback link
        tok, th = flows._token()
        rr.manager_token_hash, d["mt"] = th, tok
    rr.data = d
    rr.status = "booked"
    rr.deadline_at = None
    app = s.get(db.Application, rr.application_id)
    if app.round_id == rr.round_id:
        app.round_status = "booked"
    _confirm(s, rr, app, job, rnd, rescheduled=bool(old))
    flows._log(s, app, job, None, "interview_booked", f"{rnd['name']} on {_fmt(sl.starts_at)}" + (" (rescheduled)" if old else ""))
    return sl


def _confirm(s, rr, app, job, rnd, rescheduled=False):
    b = rr.data["booking"]
    c = s.get(db.Candidate, app.candidate_id)
    org = s.get(db.Org, app.org_id)
    join = f"{flows.invite_link(s, rr)}/join" if b.get("meeting_url") else ""
    where = join or b.get("location") or "We will share the details."
    text = (f"Your {rnd['name']} is {'rescheduled to' if rescheduled else 'booked for'} {_fmt(b['starts_at'])}."
            f" {'Join here: ' + join if join else 'Venue: ' + where}."
            + (" You can change the time from your link if needed." if int((rnd.get("config") or {}).get("reschedules_allowed", 1)) > int((rr.data or {}).get("reschedules", 0)) else ""))
    cal = ics(rr.id, b["starts_at"], b["ends_at"], f"{rnd['name']}: {job.title} at {org.name}", text, where)
    body = f"Hi {(c.name or 'there').split()[0]},\n\n{text}\n\nRegards,\n{org.name} Hiring Team\n\n--ICS--\n{cal}"
    messages.queue(s, org.id, to_email=c.email, to_phone=c.phone, subject=f"Interview {'rescheduled' if rescheduled else 'confirmed'} | {job.title}",
                   body=body, template="interview_booked", candidate_id=c.id, application_id=app.id, whatsapp_text=text)
    if b.get("interviewer_id") and flows.is_member(s, app.org_id, b["interviewer_id"]):
        u = s.get(db.User, b["interviewer_id"])
        if u:
            fb = feedback_link(rr)
            itext = (f"{c.name} booked your {rnd['name']} slot for {job.title} on {_fmt(b['starts_at'])}. Prep kit and one-click feedback: {fb}")
            ical = ics(rr.id + "-iv", b["starts_at"], b["ends_at"], f"Interview: {c.name} ({job.title})", itext, b.get("meeting_url") or b.get("location") or "")
            messages.queue(s, org.id, to_email=u.email, subject=f"Interview booked: {c.name} | {job.title}",
                           body=f"Hi {(u.name or 'there').split()[0]},\n\n{itext}\n\n--ICS--\n{ical}", template="interviewer_booked")


def feedback_link(rr: db.RoundResult) -> str:
    tok = (rr.data or {}).get("mt")
    return f"{flows.base_url()}/feedback/{tok}" if tok else ""


def mark_joined(s, rr: db.RoundResult) -> str:
    d = dict(rr.data or {})
    d["joined_at"] = d.get("joined_at") or time.time()
    rr.data = d
    return (d.get("booking") or {}).get("meeting_url") or ""


def reminders_and_no_shows(s, now: float) -> None:
    rows = s.query(db.RoundResult).filter(db.RoundResult.round_type == "human_interview", db.RoundResult.status == "booked").limit(500).all()
    for rr in rows:
        d = dict(rr.data or {})
        b = d.get("booking") or {}
        if not b:
            continue
        app = s.get(db.Application, rr.application_id)
        job = s.get(db.Job, rr.job_id)
        if not app or not job or app.round_id != rr.round_id or app.stage in flows.CLOSED_STAGES + flows.FINAL_STAGES or b.get("cancelled_at"):
            continue                                  # no reminders for an interview that no longer applies
        rnd = flows.round_of(job, rr.round_id) or {"name": "Interview"}
        start, end = b["starts_at"], b["ends_at"]
        if 0 < start - now <= 86400 and not d.get("reminded_24h"):
            d["reminded_24h"] = now
            flows.notify_candidate(s, app, "Interview tomorrow", f"A reminder: your {rnd['name']} is on {_fmt(start)}.", "interview_reminder",
                                   f"{flows.invite_link(s, rr)}", "Details and join link")
        elif 0 < start - now <= 3600 and not d.get("reminded_1h"):
            d["reminded_1h"] = now
            flows.notify_candidate(s, app, "Interview in one hour", f"Your {rnd['name']} starts at {time.strftime('%I:%M %p', time.localtime(start))}.",
                                   "interview_reminder", f"{flows.invite_link(s, rr)}", "Join")
        elif now > end + NO_SHOW_AFTER_SEC and not d.get("joined_at") and b.get("meeting_url") and not d.get("feedback"):
            rr.status = "no_show"
            if app.round_id == rr.round_id:
                app.round_status = "no_show"
            flows._log(s, app, job, None, "no_show", f"{rnd['name']}: didn't join the meeting (marked automatically)")
        rr.data = d


PREP_SYSTEM = """You prepare a human interviewer for the next round. Output ONLY JSON: {"focus": [str] (3-5 areas to probe, each
citing evidence from earlier rounds), "questions": [str] (6 role-specific questions that test ability, not definitions), "watch_for": [str] (2-3)}.
Use only the evidence given. Never suggest questions about age, marital status, religion, caste, health or family."""


def evidence(s, app: db.Application) -> dict:
    """Earlier rounds' results for the prep kit and the manager summary."""
    out = []
    for rr in s.query(db.RoundResult).filter_by(application_id=app.id).order_by(db.RoundResult.created_at):
        d = rr.data or {}
        item = {"round": rr.round_type, "status": rr.status, "score": rr.score}
        if rr.round_type == "cv_screening":
            item["reasons"] = d.get("reasons", [])[:8]
            item["stability"] = (d.get("stability") or {}).get("label")
            if d.get("ai_report"):
                item["ai_gaps"] = d["ai_report"].get("gaps", [])
        elif rr.round_type == "test":
            item["sections"] = [{"section": x["label"], "pct": x["pct"]} for x in (d.get("result") or {}).get("sections", [])]
        elif rr.round_type in ("video_intro", "role_task", "practical_task", "live_task", "reference_check"):
            a = d.get("assessment") or {}
            item["summary"] = a.get("summary")
            item["improvements"] = a.get("improvements") or a.get("concerns")
        elif rr.round_type == "ai_interview":
            item["recommendation"] = d.get("recommendation_label")
            item["summary"] = d.get("summary")
        elif rr.round_type == "human_interview" and d.get("feedback"):
            item["feedback"] = {k: d["feedback"].get(k) for k in ("decision", "rating", "notes")}
        if rr.integrity and rr.integrity.get("flagged"):
            item["integrity"] = rr.integrity.get("reasons", [])[:3]
        out.append(item)
    return {"rounds": out}


async def prep_kit(rr_id: str) -> dict:
    with db.session() as s:
        rr = s.get(db.RoundResult, rr_id)
        if (rr.data or {}).get("prep_kit"):
            return rr.data["prep_kit"]
        app, job = s.get(db.Application, rr.application_id), s.get(db.Job, rr.job_id)
        c = s.get(db.Candidate, app.candidate_id)
        ev = evidence(s, app)
        f = job.fields or {}
        role = {"title": job.title, "must_have_skills": f.get("must_have_skills"), "responsibilities": f.get("responsibilities")}
        cand = {"name": c.name, "headline": c.headline, "years": c.years}
    if llm.MOCK:
        kit = {"focus": [f"Depth in {x}" for x in (role.get("must_have_skills") or ["the core skill"])[:3]],
               "questions": [f"Walk me through how you used {x} on a real problem." for x in (role.get("must_have_skills") or ["your main skill"])[:6]],
               "watch_for": ["Specific examples over generic answers"], "source": "mock"}
    else:
        try:
            kit = await llm.complete_json(PREP_SYSTEM, json.dumps({"role": role, "candidate": cand, "evidence": ev}, ensure_ascii=False, default=str),
                                          llm.FAST_MODEL, temperature=0.3, max_tokens=900, timeout=45, fast=True)
            kit["source"] = "ai"
        except Exception as e:
            log.warning("prep kit AI failed: %s", e)
            kit = {"focus": [], "questions": [f"Tell me about a recent problem you solved using {x}." for x in (role.get("must_have_skills") or [])[:6]],
                   "watch_for": [], "source": "template"}
    kit["evidence"] = ev
    with db.session() as s:
        rr = s.get(db.RoundResult, rr_id)
        rr.data = {**(rr.data or {}), "prep_kit": kit}
    return kit


NOTES_SYSTEM = """Summarise an interviewer's notes or interview transcript for the candidate's profile. Output ONLY JSON:
{"summary": str (3-4 sentences), "strengths": [str], "concerns": [str], "evidence": [str] (short quotes or facts)}. Use only what is given."""


async def summarise_notes(text: str) -> dict:
    if not text.strip():
        return {}
    if llm.MOCK:
        return {"summary": text[:300], "strengths": [], "concerns": [], "evidence": []}
    try:
        return await llm.complete_json(NOTES_SYSTEM, text[:12000], llm.FAST_MODEL, temperature=0.2, max_tokens=600, timeout=45, fast=True)
    except Exception as e:
        log.warning("notes summary failed: %s", e)
        return {}


def record_feedback(s, rr: db.RoundResult, by: str, decision: str, rating: int | None, notes: str, attended: bool = True,
                    summary: dict | None = None, recording_file: str = "") -> None:
    d = dict(rr.data or {})
    d["feedback"] = {"by": by[:200], "decision": decision, "rating": rating, "notes": notes[:8000], "attended": attended,
                     "summary": summary or {}, "recording_file": recording_file, "at": time.time()}
    rr.data = d
    if not attended:
        rr.status = "no_show"
        app = s.get(db.Application, rr.application_id)
        if app.round_id == rr.round_id:
            app.round_status = "no_show"
        flows._log(s, app, s.get(db.Job, rr.job_id), None, "no_show", f"Marked by {by}")
        return
    if rating:
        rr.score = max(1, min(5, int(rating))) * 20
    flows.decide(s, rr, decision, by, reason=(summary or {}).get("summary") or notes[:300])


# ---------------------------------------------------------------------------
# Feedback for the candidate (drafted from the evidence; a person edits and sends it)
# ---------------------------------------------------------------------------
FEEDBACK_SYSTEM = """You draft short, kind and useful feedback for a job candidate, for the hiring team to review before
sending. Use ONLY the evidence given; never invent results, quotes or numbers. Never mention: integrity or proctoring
flags, other candidates, ranks, interviewer names, salary, or anything about age, gender, religion, caste, health or
family. Do not promise future roles. Give 1-2 genuine strengths and 2-3 specific, actionable areas to grow, each tied to
a round. Plain words, second person, under 170 words, no greeting and no sign-off (they are added for you).
Output ONLY JSON: {"text": str, "basis": [str] (for the hiring team: which piece of evidence each point came from)}"""

FEEDBACK_BLOCK = ("integrity", "proctor", "cheat", "flagged", "suspicious", "other candidates", "ranked")


def feedback_evidence(s, app: db.Application) -> list[dict]:
    """Rounds the candidate actually did, without integrity flags or interviewers' private notes."""
    out = []
    for item in evidence(s, app)["rounds"]:
        if item["round"] in ("application", "manager_approval") or item.get("status") in ("pending", "invited", "skipped", "setting_up"):
            continue
        item = {k: v for k, v in item.items() if k not in ("integrity", "feedback", "stability")}
        out.append(item)
    return out


async def feedback_draft(app_id: str) -> dict:
    with db.session() as s:
        app = s.get(db.Application, app_id)
        job = s.get(db.Job, app.job_id)
        ev = feedback_evidence(s, app)
        role = job.title
    if not ev:
        return {"text": "", "basis": [], "note": "No completed rounds to base feedback on yet."}
    if llm.MOCK:
        r = {"text": f"Thank you for the time you put into the {role} process. You did well where it counted most for you. "
                     "To grow: practise explaining your approach step by step.", "basis": [f"{x['round']}: {x.get('summary') or x.get('score')}" for x in ev][:3]}
    else:
        r = await llm.complete_json(FEEDBACK_SYSTEM, json.dumps({"role": role, "rounds": ev}, ensure_ascii=False), llm.SMART_MODEL,
                                    temperature=0.3, max_tokens=700, timeout=60)
    text = str(r.get("text") or "").strip()[:1500]
    warn = [w for w in FEEDBACK_BLOCK if w in text.lower()]
    return {"text": text, "basis": [str(x)[:200] for x in r.get("basis") or []][:5],
            "note": f"Please check before sending: the draft mentions '{warn[0]}'." if warn else ""}
