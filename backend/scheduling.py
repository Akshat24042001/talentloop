"""Human interview rounds: interviewer slots, candidate self-booking, calendar invites, reminders, no-shows,
interviewer prep kits and one-click feedback.

Meeting links go through /api/r/<token>/join, so the platform knows the candidate opened the meeting. A booked
interview with no join and no feedback 30 minutes after it ended is marked a no-show automatically (the interviewer
can correct it). One reschedule is allowed by default (round config `reschedules_allowed`).
"""
import json
import os
import logging
import time
from datetime import datetime, timezone

from . import db, flows, llm, messages, tzfmt

log = logging.getLogger("scheduling")
NO_SHOW_AFTER_SEC = 30 * 60


def slot_json(sl: db.Slot, s=None) -> dict:
    u = s.get(db.User, sl.interviewer_id) if s and sl.interviewer_id else None
    return {"id": sl.id, "starts_at": sl.starts_at, "ends_at": sl.ends_at, "meeting_url": sl.meeting_url, "location": sl.location,
            "interviewer_id": sl.interviewer_id, "interviewer": (u.name or u.email) if u else "", "booked": bool(sl.booked_by), "round_id": sl.round_id}


def open_slots(s, job_id: str, round_id: str, lead_sec: int = 3600) -> list[db.Slot]:
    """Bookable slots: free, far enough ahead, with an interviewer who still works here and isn't booked elsewhere then."""
    rows = s.query(db.Slot).filter(db.Slot.job_id == job_id, db.Slot.round_id == round_id, db.Slot.booked_by.is_(None),
                                   db.Slot.starts_at > time.time() + lead_sec).order_by(db.Slot.starts_at).all()
    ivs = {x.interviewer_id for x in rows if x.interviewer_id}
    busy: dict[str, list[tuple[float, float]]] = {}
    if ivs:
        for b in s.query(db.Slot).filter(db.Slot.interviewer_id.in_(ivs), db.Slot.booked_by.isnot(None), db.Slot.ends_at > time.time()):
            busy.setdefault(b.interviewer_id, []).append((b.starts_at, b.ends_at))
    ok = {}                                       # an interviewer who left or was switched off can't be booked
    return [x for x in rows if not x.interviewer_id or (ok.setdefault(x.interviewer_id, flows.is_member(s, x.org_id, x.interviewer_id))
                                                         and not any(a < x.ends_at and e > x.starts_at for a, e in busy.get(x.interviewer_id, [])))]


def _fmt(ts: float, org=None) -> str:
    return tzfmt.when(ts, tzfmt.org_tz(org))


def human_cfg(rnd: dict) -> dict:
    c = rnd.get("config") or {}
    return {"reschedules_allowed": int(c.get("reschedules_allowed", 3)), "cutoff_hours": float(c.get("change_cutoff_hours", 2)),
            "minutes": int(c.get("duration_min") or 45), "mode": c.get("mode", "video")}


def ics(uid: str, start: float, end: float, summary: str, description: str, location: str, organizer: str = "",
        seq: int = 0, cancel: bool = False) -> str:
    """One calendar event. The same uid with a higher SEQUENCE updates the event already in the calendar (a reschedule)
    instead of adding a second one; METHOD:CANCEL removes it."""
    def dt(t):
        return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    esc = lambda x: (x or "").replace("\\", "\\\\").replace(";", "\;").replace(",", "\\,").replace("\n", "\\n")  # noqa: E731
    import hashlib
    uid = hashlib.sha256(f"ics|{uid}".encode()).hexdigest()[:24]          # stable per booking, never a database id
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//TalentLoop//Interviews//EN", f"METHOD:{'CANCEL' if cancel else 'REQUEST'}", "BEGIN:VEVENT",
             f"UID:{uid}@talentloop", f"SEQUENCE:{int(seq)}", f"DTSTAMP:{dt(time.time())}", f"DTSTART:{dt(start)}", f"DTEND:{dt(end)}",
             f"SUMMARY:{esc(summary)}", f"DESCRIPTION:{esc(description)}", f"LOCATION:{esc(location)}",
             f"STATUS:{'CANCELLED' if cancel else 'CONFIRMED'}"]
    if organizer:
        lines.append(f"ORGANIZER:mailto:{organizer}")
    if not cancel:
        lines += ["BEGIN:VALARM", "TRIGGER:-PT30M", "ACTION:DISPLAY", "DESCRIPTION:Interview in 30 minutes", "END:VALARM"]
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines)


def _history(d: dict, action: str, by: str, starts_at: float | None) -> None:
    d["booking_history"] = (d.get("booking_history") or [])[-30:] + [{"action": action, "by": by, "starts_at": starts_at, "at": time.time()}]


def can_change(rr: db.RoundResult, rnd: dict) -> tuple[bool, str]:
    """May the candidate move or cancel their own booking now? (HR always can.)"""
    d = rr.data or {}
    b = d.get("booking")
    hc = human_cfg(rnd)
    if not b or b.get("cancelled_at"):
        return True, ""
    if int(d.get("reschedules", 0)) >= hc["reschedules_allowed"]:
        return False, ("You've changed the time the maximum number of times. Please contact the hiring team." if hc["reschedules_allowed"]
                       else "Changing the time isn't available for this interview. Please contact the hiring team.")
    if b["starts_at"] - time.time() < hc["cutoff_hours"] * 3600:
        return False, f"It's less than {hc['cutoff_hours']:g} hours to your interview, so the time can't be changed here. Please contact the hiring team."
    return True, ""


def book(s, rr: db.RoundResult, slot_id: str, by_hr: str | None = None) -> db.Slot:
    """Book a slot for the candidate: by the candidate (their link or sign-in) or by HR (by_hr = their name).
    A reschedule frees the old slot at once, so another candidate can take it."""
    sl = s.query(db.Slot).filter_by(id=slot_id, job_id=rr.job_id, round_id=rr.round_id).with_for_update().first()
    if not sl or sl.booked_by:
        raise ValueError("That time was just taken. Please choose another.")
    if sl.starts_at < time.time() + (300 if by_hr else 3600):
        raise ValueError("That time is too soon. Please choose a later slot.")
    if sl.interviewer_id and _interviewer_busy(s, sl):
        raise ValueError("The interviewer is no longer free at that time. Please choose another.")
    job = s.get(db.Job, rr.job_id)
    org = s.get(db.Org, rr.org_id)
    rnd = flows.round_of(job, rr.round_id) or {"config": {}, "name": "Interview"}
    d = dict(rr.data or {})
    old = d.get("booking") if not (d.get("booking") or {}).get("cancelled_at") else None
    if old and not by_hr:
        ok, why = can_change(rr, rnd)
        if not ok:
            raise ValueError(why)
    if old:
        prev = s.get(db.Slot, old["slot_id"])
        if prev and prev.booked_by == rr.id:
            prev.booked_by = None                        # free again for everyone else
        if not by_hr:
            d["reschedules"] = int(d.get("reschedules", 0)) + 1
    sl.booked_by = rr.id
    iv = s.get(db.User, sl.interviewer_id) if sl.interviewer_id else None
    cfg = rnd.get("config") or {}
    seq = int((old or {}).get("seq", 0)) + 1 if old else int(d.get("ics_seq", 0))
    d["booking"] = {"slot_id": sl.id, "starts_at": sl.starts_at, "ends_at": sl.ends_at, "meeting_url": sl.meeting_url or cfg.get("meeting_url", ""),
                    "location": sl.location or cfg.get("location", ""), "interviewer_id": sl.interviewer_id,
                    "interviewer": (iv.name or iv.email) if iv else "", "booked_at": time.time(), "by": by_hr or "candidate", "seq": seq}
    d["ics_seq"] = seq
    d.pop("time_request", None)
    _history(d, "rescheduled" if old else "booked", by_hr or "candidate", sl.starts_at)
    for k in ("reminded_24h", "reminded_1h"):
        d.pop(k, None)
    if "mt" not in d:                                 # the interviewer's no-login feedback link
        tok, th = flows._token()
        rr.manager_token_hash, d["mt"] = th, tok
    rr.data = d
    rr.status = "booked"
    rr.deadline_at = None
    app = s.get(db.Application, rr.application_id)
    if app.round_id == rr.round_id:
        app.round_status = "booked"
    _confirm(s, rr, app, job, rnd, org, old=old, by_hr=by_hr)
    flows._log(s, app, job, None, "interview_booked", f"{rnd['name']} on {_fmt(sl.starts_at, org)}"
               + (" (rescheduled" + (f" by {by_hr})" if by_hr else ")") if old else (f" (booked by {by_hr})" if by_hr else "")))
    return sl


def cancel(s, rr: db.RoundResult, by: str, reason: str = "", notify: bool = True) -> None:
    """Cancel the booking (candidate or HR). The slot is freed and the candidate can pick a new time from their link."""
    d = dict(rr.data or {})
    b = d.get("booking")
    if not b or b.get("cancelled_at"):
        raise ValueError("There is no booked interview to cancel.")
    job, org = s.get(db.Job, rr.job_id), s.get(db.Org, rr.org_id)
    rnd = flows.round_of(job, rr.round_id) or {"config": {}, "name": "Interview"}
    if by == "candidate":
        ok, why = can_change(rr, rnd)
        if not ok:
            raise ValueError(why)
        d["reschedules"] = int(d.get("reschedules", 0)) + 1
    sl = s.get(db.Slot, b.get("slot_id"))
    if sl and sl.booked_by == rr.id:
        sl.booked_by = None
    d["booking"] = {**b, "cancelled_at": time.time(), "cancel_reason": reason[:500], "cancelled_by": by}
    _history(d, "cancelled", by, b["starts_at"])
    rr.data = d
    rr.status = "invited"
    app = s.get(db.Application, rr.application_id)
    if app.round_id == rr.round_id:
        app.round_status = "invited"
    c = s.get(db.Candidate, app.candidate_id)
    title = f"{rnd['name']}: {job.title} at {org.name}"
    cal = ics(rr.id, b["starts_at"], b["ends_at"], title, "Cancelled", "", seq=int(b.get("seq", 0)) + 1, cancel=True)
    link = flows.invite_link(s, rr)
    if notify and c and c.email:
        who = "You cancelled" if by == "candidate" else "The hiring team cancelled"
        text = (f"{who} your {rnd['name']} on {_fmt(b['starts_at'], org)}." + (f" Reason: {reason}" if reason and by != "candidate" else "")
                + " Pick a new time whenever you're ready; the times still open are on your interview page.")
        messages.queue(s, org.id, to_email=c.email, to_phone=c.phone, subject=f"Interview cancelled | {job.title}",
                       body=_body(c, org, text, [("Pick a new time", link), ("Your application status", flows.status_link(app)),
                                                 ("All your applications", f"{flows.base_url()}/me")]) + f"\n\n--ICS--\n{cal}",
                       template="interview_cancelled", candidate_id=c.id, application_id=app.id, whatsapp_text=f"{text} {link}")
    _tell_interviewer(s, b, org, f"Cancelled: {c.name if c else 'Candidate'} | {job.title}",
                      f"The {rnd['name']} with {c.name if c else 'the candidate'} on {_fmt(b['starts_at'], org)} is cancelled"
                      f" ({'by the candidate' if by == 'candidate' else 'by ' + by}). The slot is open again.",
                      ics(rr.id + "-iv", b["starts_at"], b["ends_at"], f"Interview: {c.name if c else ''} ({job.title})", "Cancelled", "",
                          seq=int(b.get("seq", 0)) + 1, cancel=True))
    flows._log(s, app, job, None, "interview_cancelled", f"{rnd['name']} on {_fmt(b['starts_at'], org)} cancelled by {by}" + (f": {reason[:150]}" if reason else ""))


def request_times(s, rr: db.RoundResult, note: str) -> None:
    """The candidate says none of the open times work and suggests their own. HR and the interviewers are told."""
    note = (note or "").strip()
    if len(note) < 5:
        raise ValueError("Tell us which days and times suit you.")
    d = dict(rr.data or {})
    d["time_request"] = {"note": note[:600], "at": time.time()}
    rr.data = d
    app, job, org = s.get(db.Application, rr.application_id), s.get(db.Job, rr.job_id), s.get(db.Org, rr.org_id)
    c = s.get(db.Candidate, app.candidate_id)
    rnd = flows.round_of(job, rr.round_id) or {"name": "Interview", "config": {}}
    to = {a["email"] for a in flows.team_for(s, job)}
    for uid in (rnd.get("config") or {}).get("interviewers") or []:
        u = s.get(db.User, uid)
        if u and flows.is_member(s, org.id, u.id):
            to.add(u.email)
    for email in sorted(to):
        messages.queue(s, org.id, to_email=email, subject=f"No suitable interview time: {c.name} | {job.title}",
                       body=f"{c.name} says none of the open times for {rnd['name']} ({job.title}) work for them and suggests:\n\n\"{note[:600]}\"\n\n"
                            f"Add slots in the job's hiring flow, or book a time for them from their application. They are emailed when new times open.\n\n"
                            f"{flows.base_url()}/app/jobs/{job.id}?tab=pipeline",
                       template="time_request", candidate_id=c.id, application_id=app.id)
    flows._log(s, app, job, None, "time_requested", f"{rnd['name']}: {note[:200]}")


def new_times_open(s, job: db.Job, round_id: str) -> int:
    """After HR adds slots: tell candidates who are still waiting to book (at most once a day each)."""
    rnd = flows.round_of(job, round_id) or {"name": "Interview"}
    n = 0
    for rr in s.query(db.RoundResult).filter(db.RoundResult.job_id == job.id, db.RoundResult.round_id == round_id, db.RoundResult.status == "invited"):
        d = dict(rr.data or {})
        app = s.get(db.Application, rr.application_id)
        if not app or app.round_id != round_id or app.stage in flows.CLOSED_STAGES + flows.FINAL_STAGES:
            continue
        if time.time() - float(d.get("slots_notified_at") or 0) < 86400:
            continue
        d["slots_notified_at"] = time.time()
        rr.data = d
        flows.notify_candidate(s, app, "New interview times", f"New times are open for your {rnd['name']}. Pick the one that suits you.",
                               "interview_times", flows.invite_link(s, rr), "Pick a time")
        n += 1
    return n


def _interviewer_busy(s, sl: db.Slot) -> bool:
    """The interviewer already has another booked interview overlapping this slot (any job)."""
    return s.query(db.Slot.id).filter(db.Slot.interviewer_id == sl.interviewer_id, db.Slot.id != sl.id, db.Slot.booked_by.isnot(None),
                                      db.Slot.starts_at < sl.ends_at, db.Slot.ends_at > sl.starts_at).first() is not None


def _body(c, org, text: str, links: list[tuple[str, str]], extra: str = "") -> str:
    first = ((c.name if c else "") or "there").split()[0]
    out = f"Hi {first},\n\n{text}\n"
    if extra:
        out += f"\n{extra}\n"
    for label, url in links:
        if url:
            out += f"\n{label}: {url}"
    return out + f"\n\nRegards,\n{org.name} Hiring Team"


def _tell_interviewer(s, b: dict, org, subject: str, text: str, cal: str) -> None:
    if b.get("interviewer_id") and flows.is_member(s, org.id, b["interviewer_id"]):
        u = s.get(db.User, b["interviewer_id"])
        if u:
            messages.queue(s, org.id, to_email=u.email, subject=subject, body=f"Hi {(u.name or 'there').split()[0]},\n\n{text}\n\n--ICS--\n{cal}",
                           template="interviewer_booked")


MODE_TIPS = {"video": "Join 5 minutes early from a laptop or phone with a working camera and microphone, in a quiet place.",
             "phone": "Keep your phone charged and be somewhere quiet; the interviewer will call you.",
             "in_person": "Please arrive 10 minutes early with a photo ID."}


def _confirm(s, rr, app, job, rnd, org, old=None, by_hr=None):
    b = rr.data["booking"]
    c = s.get(db.Candidate, app.candidate_id)
    hc = human_cfg(rnd)
    page = flows.invite_link(s, rr)
    join = f"{page}/join" if b.get("meeting_url") else ""
    mode = {"video": "Video call", "phone": "Phone call", "in_person": "In person"}.get(hc["mode"], hc["mode"])
    what = "moved to a new time" if old else "confirmed"
    head = f"Your {rnd['name']} for {job.title} at {org.name} is {what}" + (" by the hiring team." if by_hr else ".")
    rows = [("When", f"{_fmt(b['starts_at'], org)} ({round((b['ends_at'] - b['starts_at']) / 60)} minutes)")]
    if old:
        rows.append(("Was", _fmt(old["starts_at"], org)))
    rows.append(("How", mode))
    if b.get("interviewer"):
        rows.append(("With", b["interviewer"]))
    if join:
        rows.append(("Join link", join))
    elif b.get("location"):
        rows.append(("Where", b["location"]))
    details = "\n".join(f"  {k}: {v}" for k, v in rows)
    left = hc["reschedules_allowed"] - int((rr.data or {}).get("reschedules", 0))
    change = (f"Need a different time? You can change or cancel it {left} more time(s), up to {hc['cutoff_hours']:g} hours before"
              if left > 0 else "To change the time, please reply to this email.")
    text = f"{head}\n\n{details}\n\n{MODE_TIPS.get(hc['mode'], '')}"
    cal = ics(rr.id, b["starts_at"], b["ends_at"], f"{rnd['name']}: {job.title} at {org.name}",
              f"{head}\nJoin: {join}\nChange the time: {page}" if join else f"{head}\nChange the time: {page}", join or b.get("location", ""), seq=int(b.get("seq", 0)))
    body = _body(c, org, text, [(change, page if left > 0 else ""), ("Add to calendar", f"{page}/calendar.ics"),
                                ("Your application status", flows.status_link(app)), ("All your applications (sign in with this email)", f"{flows.base_url()}/me")])
    messages.queue(s, org.id, to_email=c.email, to_phone=c.phone, subject=f"Interview {'rescheduled' if old else 'confirmed'}: {_fmt(b['starts_at'], org)} | {job.title}",
                   body=f"{body}\n\n--ICS--\n{cal}", template="interview_booked", candidate_id=c.id, application_id=app.id,
                   whatsapp_text=f"{head} {_fmt(b['starts_at'], org)}. {('Join: ' + join) if join else ('Venue: ' + (b.get('location') or 'to be shared'))}. Change: {page}")
    if old and old.get("interviewer_id") and old.get("interviewer_id") != b.get("interviewer_id"):
        _tell_interviewer(s, old, org, f"Moved away: {c.name} | {job.title}",
                          f"{c.name}'s {rnd['name']} on {_fmt(old['starts_at'], org)} moved to another interviewer's slot. Your slot is open again.",
                          ics(rr.id + "-iv", old["starts_at"], old["ends_at"], f"Interview: {c.name} ({job.title})", "Cancelled", "", seq=int(old.get("seq", 0)) + 1, cancel=True))
    fb = feedback_link(rr)
    itext = (f"{c.name}'s {rnd['name']} for {job.title} is {'moved to' if old else 'booked for'} {_fmt(b['starts_at'], org)}"
             + (f" (was {_fmt(old['starts_at'], org)})" if old else "") + f". Meeting: {b.get('meeting_url') or b.get('location') or 'not set'}.\n\nPrep kit and one-click feedback: {fb}")
    _tell_interviewer(s, b, org, f"Interview {'moved' if old else 'booked'}: {c.name} | {job.title}", itext,
                      ics(rr.id + "-iv", b["starts_at"], b["ends_at"], f"Interview: {c.name} ({job.title})", itext, b.get("meeting_url") or b.get("location") or "",
                          seq=int(b.get("seq", 0))))


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
        org = s.get(db.Org, rr.org_id)
        rnd = flows.round_of(job, rr.round_id) or {"name": "Interview"}
        start, end = b["starts_at"], b["ends_at"]
        page = flows.invite_link(s, rr)
        join = f"{page}/join" if b.get("meeting_url") else ""
        if 3600 < start - now <= 86400 and not d.get("reminded_24h"):
            d["reminded_24h"] = now
            flows.notify_candidate(s, app, "Interview tomorrow", f"A reminder: your {rnd['name']} is on {_fmt(start, org)}."
                                   + (f" Join link: {join}." if join else f" Venue: {b.get('location') or 'as shared'}.")
                                   + " If you can no longer make it, change the time from your interview page.", "interview_reminder", page, "Details, change or cancel")
        elif 0 < start - now <= 3600 and not d.get("reminded_1h"):
            d["reminded_1h"] = now
            flows.notify_candidate(s, app, "Interview in one hour", f"Your {rnd['name']} starts at {tzfmt.clock(start, tzfmt.org_tz(org))}.",
                                   "interview_reminder", join or page, "Join" if join else "Details")
        elif now > end + NO_SHOW_AFTER_SEC and not d.get("joined_at") and b.get("meeting_url") and not d.get("feedback"):
            rr.status = "no_show"
            if app.round_id == rr.round_id:
                app.round_status = "no_show"
            flows._log(s, app, job, None, "no_show", f"{rnd['name']}: didn't join the meeting (marked automatically)")
        rr.data = d
    ai_reminders(s, now)


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


# ---------------------------------------------------------------------------
# AI interview times: run by the platform, no interviewer calendars
# ---------------------------------------------------------------------------
# The AI interviewer is free any time, but the voice provider caps how many calls run at once (shared by every company
# on this server). Candidates either start right away or book a 30-minute start time; a time is offered only while
# fewer than AI_SLOT_CAPACITY booked interviews overlap it. Booking is a commitment with reminders, not a lock: the
# candidate may still start earlier, and a missed time is released with an email to pick a new one.
AI_CAPACITY = int(os.getenv("AI_SLOT_CAPACITY", "10"))
AI_STEP = 1800
AI_MISSED_AFTER = 2 * 3600


def ai_cfg(rnd: dict) -> dict:
    c = rnd.get("config") or {}
    return {"allow": c.get("allow_scheduling", True) is not False, "from": int(c.get("day_from", 8)), "to": int(c.get("day_to", 22)),
            "reschedules": int(c.get("reschedules_allowed", 5)), "minutes": int(c.get("duration_min") or 15), "cutoff_min": 30,
            "days_ahead": int(c.get("days_ahead", 14))}


def _ai_load(s, exclude: str) -> list[tuple[float, float]]:
    out = []
    for rr in s.query(db.RoundResult).filter(db.RoundResult.round_type == "ai_interview", db.RoundResult.status == "invited").limit(5000):
        b = (rr.data or {}).get("ai_booking")
        if rr.id != exclude and b and not b.get("cancelled_at") and b["ends_at"] > time.time():
            out.append((b["starts_at"], b["ends_at"]))
    return out


def ai_slots(s, rr: db.RoundResult, rnd: dict, org) -> list[float]:
    """Start times the candidate can book, in the company's waking hours, before their deadline."""
    ac = ai_cfg(rnd)
    now = time.time()
    first = (int(now + 1800) // AI_STEP + 1) * AI_STEP
    last = min(rr.deadline_at or now + ac["days_ahead"] * 86400, now + ac["days_ahead"] * 86400) - ac["minutes"] * 60
    load = _ai_load(s, rr.id)
    tz = tzfmt.org_tz(org)
    out = []
    t = first
    while t <= last and len(out) < 600:
        h = tzfmt.local(t, tz).hour + tzfmt.local(t, tz).minute / 60
        if ac["from"] <= h and h + ac["minutes"] / 60 <= ac["to"]:
            end = t + ac["minutes"] * 60
            if sum(1 for a, e in load if a < end and e > t) < AI_CAPACITY:
                out.append(t)
        t += AI_STEP
    return out


def ai_can_change(rr: db.RoundResult, rnd: dict) -> tuple[bool, str]:
    d, ac = rr.data or {}, ai_cfg(rnd)
    b = d.get("ai_booking")
    if not b or b.get("cancelled_at"):
        return True, ""
    if int(d.get("ai_reschedules", 0)) >= ac["reschedules"]:
        return False, "You've changed the time the maximum number of times. You can still start the interview any time before your deadline."
    if b["starts_at"] - time.time() < ac["cutoff_min"] * 60:
        return False, "Your interview is about to start, so the time can't be changed now. You can start it from this page."
    return True, ""


def ai_book(s, rr: db.RoundResult, starts_at: float, by_hr: str | None = None) -> dict:
    job, org = s.get(db.Job, rr.job_id), s.get(db.Org, rr.org_id)
    rnd = flows.round_of(job, rr.round_id) or {"config": {}, "name": "AI interview"}
    ac = ai_cfg(rnd)
    if not ac["allow"] and not by_hr:
        raise ValueError("This interview can be taken any time; booking a time isn't needed.")
    if rr.status != "invited" or not (rr.data or {}).get("interview_id"):
        raise ValueError("The interview isn't ready to be scheduled yet.")
    starts_at = float(starts_at)
    if starts_at not in set(ai_slots(s, rr, rnd, org)):
        raise ValueError("That time isn't available any more. Please pick another.")
    d = dict(rr.data or {})
    old = d.get("ai_booking") if not (d.get("ai_booking") or {}).get("cancelled_at") else None
    if old and not by_hr:
        ok, why = ai_can_change(rr, rnd)
        if not ok:
            raise ValueError(why)
        d["ai_reschedules"] = int(d.get("ai_reschedules", 0)) + 1
    seq = int(d.get("ics_seq", 0)) + (1 if old else 0)
    d["ai_booking"] = {"starts_at": starts_at, "ends_at": starts_at + ac["minutes"] * 60, "booked_at": time.time(), "by": by_hr or "candidate", "seq": seq}
    d["ics_seq"] = seq
    for k in ("ai_reminded_24h", "ai_reminded_1h", "ai_reminded_now"):
        d.pop(k, None)
    _history(d, "rescheduled" if old else "booked", by_hr or "candidate", starts_at)
    rr.data = d
    _extend_interview(d.get("interview_id"), starts_at + ac["minutes"] * 60 + AI_MISSED_AFTER + 3600)
    app = s.get(db.Application, rr.application_id)
    c = s.get(db.Candidate, app.candidate_id)
    page = flows.invite_link(s, rr)
    head = (f"Your {rnd['name']} for {job.title} at {org.name} is {'moved to a new time' if old else 'scheduled'}"
            + (" by the hiring team." if by_hr else "."))
    rows = [("When", f"{_fmt(starts_at, org)} (about {ac['minutes']} minutes)")] + ([("Was", _fmt(old["starts_at"], org))] if old else []) + [
        ("How", "Voice interview with an AI interviewer, in your browser"), ("Interview link", page)]
    left = ac["reschedules"] - int(d.get("ai_reschedules", 0))
    text = (f"{head}\n\n" + "\n".join(f"  {k}: {v}" for k, v in rows) +
            "\n\nOpen the link at that time and press Start. Use Chrome, Edge or Safari, a quiet room, and headphones if you have them. "
            "You can also start earlier if you're ready.")
    cal = ics(rr.id, starts_at, starts_at + ac["minutes"] * 60, f"{rnd['name']}: {job.title} at {org.name}", f"{head}\nInterview link: {page}", page, seq=seq)
    body = _body(c, org, text, [(f"Change or cancel the time ({left} change(s) left, up to 30 minutes before)" if left > 0 else "", page),
                                ("Your application status", flows.status_link(app)), ("All your applications (sign in with this email)", f"{flows.base_url()}/me")])
    messages.queue(s, org.id, to_email=c.email, to_phone=c.phone, subject=f"AI interview {'rescheduled' if old else 'scheduled'}: {_fmt(starts_at, org)} | {job.title}",
                   body=f"{body}\n\n--ICS--\n{cal}", template="ai_interview_scheduled", candidate_id=c.id, application_id=app.id,
                   whatsapp_text=f"{head} {_fmt(starts_at, org)}. Interview link: {page}")
    flows._log(s, app, job, None, "interview_booked", f"{rnd['name']} on {_fmt(starts_at, org)}" + (" (rescheduled)" if old else "") + (f" by {by_hr}" if by_hr else ""))
    return d["ai_booking"]


def ai_cancel(s, rr: db.RoundResult, by: str, missed: bool = False) -> None:
    d = dict(rr.data or {})
    b = d.get("ai_booking")
    if not b or b.get("cancelled_at"):
        raise ValueError("No interview time is booked.")
    job, org = s.get(db.Job, rr.job_id), s.get(db.Org, rr.org_id)
    rnd = flows.round_of(job, rr.round_id) or {"config": {}, "name": "AI interview"}
    if by == "candidate":
        ok, why = ai_can_change(rr, rnd)
        if not ok:
            raise ValueError(why)
    d["ai_booking"] = {**b, "cancelled_at": time.time(), "cancelled_by": by, "missed": missed}
    _history(d, "missed" if missed else "cancelled", by, b["starts_at"])
    rr.data = d
    app = s.get(db.Application, rr.application_id)
    c = s.get(db.Candidate, app.candidate_id)
    page = flows.invite_link(s, rr)
    text = (f"We missed you at your {rnd['name']} time ({_fmt(b['starts_at'], org)}). No problem: pick a new time, or start whenever you're ready"
            if missed else f"Your {rnd['name']} time ({_fmt(b['starts_at'], org)}) is cancelled. Pick a new time, or start whenever you're ready")
    text += f" before {tzfmt.day(rr.deadline_at, tzfmt.org_tz(org))}." if rr.deadline_at else "."
    cal = ics(rr.id, b["starts_at"], b["ends_at"], f"{rnd['name']}: {job.title} at {org.name}", "Cancelled", "", seq=int(b.get("seq", 0)) + 1, cancel=True)
    messages.queue(s, org.id, to_email=c.email, to_phone=c.phone, subject=f"{'Missed' if missed else 'Cancelled'}: AI interview time | {job.title}",
                   body=_body(c, org, text, [("Your interview page", page), ("Your application status", flows.status_link(app))]) + f"\n\n--ICS--\n{cal}",
                   template="ai_interview_cancelled", candidate_id=c.id, application_id=app.id, whatsapp_text=f"{text} {page}")
    flows._log(s, app, job, None, "interview_cancelled", f"{rnd['name']} time {_fmt(b['starts_at'], org)} " + ("missed" if missed else f"cancelled by {by}"))


def _extend_interview(iid: str | None, until: float) -> None:
    """Keep the AI interview link valid past the booked time."""
    if not iid:
        return
    from . import store
    rec = store.load(iid)
    if rec and rec.get("status") == "created" and float(rec.get("expires_at") or 0) < until:
        rec["expires_at"] = until
        store.save(rec)


def _ai_started(iid: str | None) -> bool:
    from . import store
    rec = store.load(iid) if iid else None
    return bool(rec) and rec.get("status") != "created"


def ai_reminders(s, now: float) -> None:
    for rr in s.query(db.RoundResult).filter(db.RoundResult.round_type == "ai_interview", db.RoundResult.status == "invited").limit(2000):
        d = dict(rr.data or {})
        b = d.get("ai_booking")
        if not b or b.get("cancelled_at"):
            continue
        start = b["starts_at"]
        due = (("ai_reminded_24h", 3600 < start - now <= 86400), ("ai_reminded_1h", 600 < start - now <= 3600),
               ("ai_reminded_now", -900 <= start - now <= 600))
        key = next((k for k, hit in due if hit and not d.get(k)), None)
        missed = now > b["ends_at"] + AI_MISSED_AFTER
        if not key and not missed:
            continue
        app, job = s.get(db.Application, rr.application_id), s.get(db.Job, rr.job_id)
        if not app or not job or app.round_id != rr.round_id or app.stage in flows.CLOSED_STAGES + flows.FINAL_STAGES:
            continue
        if _ai_started(d.get("interview_id")):
            continue                                   # already taking it, or done
        org = s.get(db.Org, rr.org_id)
        rnd = flows.round_of(job, rr.round_id) or {"name": "AI interview"}
        page = flows.invite_link(s, rr)
        if missed:
            ai_cancel(s, rr, "system", missed=True)
            continue
        d[key] = now
        rr.data = d
        if key == "ai_reminded_now":
            flows.notify_candidate(s, app, "Your AI interview is ready", f"It's time for your {rnd['name']}. Open the link and press Start.",
                                   "ai_interview_reminder", page, "Start the interview")
        else:
            flows.notify_candidate(s, app, "Interview reminder", f"A reminder: your {rnd['name']} is on {_fmt(start, org)}. If the time no longer works, change it from your interview page.",
                                   "ai_interview_reminder", page, "Interview page")
