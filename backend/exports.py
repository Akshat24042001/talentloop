"""Downloads for HR: full PDF report, plain-text transcript, JSON, CSV of all interviews, ZIP bundle."""
import csv
import io
import json
import os
import time
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from . import proctor, store

REC_LABEL = {"strong_yes": "Strong yes", "yes": "Yes", "maybe": "Maybe", "no": "No"}


def _mmss(t) -> str:
    t = int(t or 0)
    sign, t = ("-" if t < 0 else ""), abs(t)
    return f"{sign}{t // 60:02d}:{t % 60:02d}"


def _when(ts) -> str:
    if not ts:
        return "-"
    tz = os.getenv("REPORT_TZ", "Asia/Kolkata")
    try:
        from zoneinfo import ZoneInfo
        return datetime.fromtimestamp(ts, ZoneInfo(tz)).strftime("%d %b %Y, %H:%M ") + tz.split("/")[-1]
    except Exception:
        return datetime.fromtimestamp(ts, timezone.utc).strftime("%d %b %Y, %H:%M UTC")


def safe_filename(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").strip()
    s = "".join(c if (c.isascii() and c.isalnum()) or c in "-_" else "_" for c in s)
    while "__" in s:
        s = s.replace("__", "_")
    return (s.strip("_") or "interview")[:60]


def base_name(rec: dict) -> str:
    p = rec["plan"]
    return safe_filename(f"{p.get('candidate_name') or 'candidate'}_{p.get('role') or 'role'}_{rec['id']}")


def public_record(rec: dict) -> dict:
    """The interview record without internal secrets and bulky internals."""
    r = json.loads(json.dumps(rec))
    r.pop("snapshots", None)
    st = r.get("state") or {}
    st.pop("token", None)
    st.pop("tokens", None)
    return r


# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------
def transcript_text(rec: dict) -> str:
    p = rec["plan"]
    qs = {q["id"]: q for q in p["questions"]}
    lines = [f"Interview transcript: {p.get('candidate_name', '')} for {p.get('role', '')}"
             f"{' at ' + p['company'] if p.get('company') else ''}",
             f"Interview ID: {rec['id']}   Created: {_when(rec.get('created_at'))}   Status: {rec.get('status')}",
             "Times are minutes:seconds of active interview time.", ""]
    last_q = None
    for e in (rec.get("state") or {}).get("log", []):
        if e["role"] == "ai" and e.get("q_id") != last_q and e.get("action") in ("open", "resume", "next_question"):
            q = qs.get(e["q_id"], {})
            lines += ["", f"=== {e['q_id']} ({q.get('type', '')}) {q.get('ask', '')}"]
            last_q = e["q_id"]
        who = "INTERVIEWER" if e["role"] == "ai" else "CANDIDATE"
        tag = f"  [{e['action']}]" if e.get("action") and e["role"] == "ai" and e["action"] not in ("open", "next_question") else ""
        lines.append(f"[{_mmss(e.get('t'))}] {who}: {e['text']}{tag}")
    return "\n".join(lines).strip() + "\n"


# ---------------------------------------------------------------------------
# CSV of all interviews
# ---------------------------------------------------------------------------
def interviews_csv(recs: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["interview_id", "created", "candidate", "email", "role", "company", "status", "ai_recommendation",
                "ai_confidence", "overall_score_1to5", "questions_asked", "questions_planned", "integrity_risk",
                "integrity_reasons", "hr_decision", "hr_notes", "reconnects", "candidate_feedback_rating", "report_link"])
    for r in recs:
        rep = r.get("report") or {}
        c = rep.get("computed") or {}
        pr = proctor.summary(r) if r.get("state") else {"risk": "", "reasons": []}
        w.writerow([r["id"], _when(r.get("created_at")), r["plan"].get("candidate_name", ""),
                    (r.get("settings") or {}).get("candidate_email", ""), r["plan"].get("role", ""),
                    r["plan"].get("company", ""), r.get("status"), REC_LABEL.get(rep.get("recommendation"), ""),
                    rep.get("confidence", ""), c.get("overall", ""), c.get("questions_asked", ""),
                    c.get("questions_planned", ""), pr["risk"], " | ".join(pr["reasons"]),
                    (r.get("hr") or {}).get("decision", ""), (r.get("hr") or {}).get("notes", ""),
                    ((r.get("state") or {}).get("reconnects", 0)), (r.get("feedback") or {}).get("rating", ""),
                    f"/report.html?id={r['id']}"])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
_FONTS = False


def _fonts():
    global _FONTS
    if _FONTS:
        return
    import reportlab
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    d = Path(reportlab.__file__).parent / "fonts"
    pdfmetrics.registerFont(TTFont("Vera", str(d / "Vera.ttf")))
    pdfmetrics.registerFont(TTFont("VeraBd", str(d / "VeraBd.ttf")))
    pdfmetrics.registerFont(TTFont("VeraIt", str(d / "VeraIt.ttf")))
    pdfmetrics.registerFontFamily("Vera", normal="Vera", bold="VeraBd", italic="VeraIt", boldItalic="VeraBd")
    fd = Path(__file__).parent / "fonts"
    for name, file in (("Deva", "NotoSansDevanagari-Regular.ttf"), ("Guj", "NotoSansGujarati-Regular.ttf")):
        if (fd / file).exists():
            pdfmetrics.registerFont(TTFont(name, str(fd / file)))
            _SCRIPT_FONTS[name] = True
    _FONTS = True


_SCRIPT_FONTS: dict[str, bool] = {}
# Candidate names and answers can be in Hindi/Marathi (Devanagari) or Gujarati. These runs get a Noto
# font; with uharfbuzz installed the conjuncts and vowel signs are shaped correctly.
_SCRIPTS = (("Deva", 0x0900, 0x097F), ("Guj", 0x0A80, 0x0AFF))


def _script(c: str) -> str | None:
    o = ord(c)
    for name, lo, hi in _SCRIPTS:
        if lo <= o <= hi and _SCRIPT_FONTS.get(name):
            return name
    return None


_REPL = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "...",
         "₹": "Rs.", "•": "-", " ": " ", "→": "->", "≤": "<=", "≥": ">="}


def _t(s) -> str:
    """Text for reportlab Paragraphs: XML-escaped, Latin text in the base font, Devanagari/Gujarati runs
    wrapped in their own font, anything else the fonts cannot draw replaced with '?'."""
    s = str(s if s is not None else "")
    s = "".join(_REPL.get(c, c) for c in s)
    out, run, run_font = [], [], None

    def flush():
        if run:
            txt = escape("".join(run))
            out.append(f'<font name="{run_font}">{txt}</font>' if run_font else txt)
            run.clear()

    for c in s:
        f = _script(c)
        if f is None and ord(c) >= 256:
            if run_font and unicodedata.category(c) in ("Mn", "Mc", "Cf"):   # joiners, signs inside a word
                f = run_font
            else:
                d = unicodedata.normalize("NFKD", c)
                c = "".join(x for x in d if ord(x) < 256 and not unicodedata.combining(x)) or "?"
        if f != run_font:
            flush()
            run_font = f
        run.append(c)
    flush()
    return "".join(out)


def report_pdf(rec: dict) -> bytes:
    _fonts()
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle)

    ink, muted, line = colors.HexColor("#15181e"), colors.HexColor("#5d6573"), colors.HexColor("#d9dde3")
    ok, warn, bad, brand = (colors.HexColor("#12805c"), colors.HexColor("#b45309"), colors.HexColor("#c62828"),
                            colors.HexColor("#1f5eff"))
    base = ParagraphStyle("b", fontName="Vera", fontSize=9, leading=12.5, textColor=ink, alignment=TA_LEFT,
                          shaping=1)
    small = ParagraphStyle("s", parent=base, fontSize=7.8, leading=10, textColor=muted)
    h1 = ParagraphStyle("h1", parent=base, fontName="VeraBd", fontSize=16, leading=20, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=base, fontName="VeraBd", fontSize=11.5, leading=15, spaceBefore=10, spaceAfter=4,
                        textColor=brand)
    h3 = ParagraphStyle("h3", parent=base, fontName="VeraBd", fontSize=9.5, leading=13, spaceBefore=6)
    P = lambda s, st=base: Paragraph(s, st)  # noqa: E731

    p = rec["plan"]
    rep = rec.get("report") or {}
    comp = rep.get("computed") or {}
    pr = proctor.summary(rec) if rec.get("state") else None
    stt = proctor.stats(rec) if rec.get("state") else None
    hr = rec.get("hr") or {}
    settings = rec.get("settings") or {}
    qstats = {x["q_id"]: x for x in (stt or {}).get("per_question", [])}
    story = []

    def table(rows, widths, header=True, style_extra=()):
        t = Table(rows, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
        st = [("FONT", (0, 0), (-1, -1), "Vera", 8.5), ("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("LINEBELOW", (0, 0), (-1, -1), 0.3, line), ("TOPPADDING", (0, 0), (-1, -1), 3),
              ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        if header:
            st += [("FONT", (0, 0), (-1, 0), "VeraBd", 8.5), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2ff"))]
        t.setStyle(TableStyle(st + list(style_extra)))
        return t

    # --- header
    story += [P(f"Interview report: {_t(p.get('candidate_name') or 'Candidate')}", h1),
              P(f"{_t(p.get('role', ''))}{' at ' + _t(p['company']) if p.get('company') else ''} &nbsp;|&nbsp; "
                f"Interview ID {_t(rec['id'])} &nbsp;|&nbsp; Generated {_t(_when(time.time()))}", small),
              Spacer(1, 6)]
    rec_label = REC_LABEL.get(rep.get("recommendation"), "Not scored yet")
    rec_color = {"strong_yes": ok, "yes": ok, "maybe": warn, "no": bad}.get(rep.get("recommendation"), muted)
    risk = (pr or {}).get("risk", "-")
    risk_color = {"low": ok, "medium": warn, "high": bad}.get(risk, muted)
    summary_rows = [
        [P("<b>AI recommendation</b><br/>(HR decides)", small), P(f"<font color='{rec_color.hexval()}' size=13><b>{_t(rec_label)}</b></font>"),
         P("<b>Integrity risk</b>", small), P(f"<font color='{risk_color.hexval()}' size=13><b>{_t(str(risk).upper())}</b></font>")],
        [P("<b>Overall score</b>", small), P(f"{_t(comp.get('overall', '-'))} / 5"),
         P("<b>HR decision</b>", small), P(_t((hr.get("decision") or "pending").replace("_", " ")))],
        [P("<b>Questions asked</b>", small), P(f"{_t(comp.get('questions_asked', '-'))} of {_t(comp.get('questions_planned', len(p['questions'])))}"),
         P("<b>AI confidence</b>", small), P(_t(rep.get("confidence", "-")))],
        [P("<b>Interview date</b>", small), P(_t(_when(proctor.interview_start(rec)))),
         P("<b>Status</b>", small), P(_t(rec.get("status")))],
        [P("<b>Candidate email</b>", small), P(_t(settings.get("candidate_email") or "-")),
         P("<b>Active time</b>", small), P(f"{_t((stt or {}).get('active_minutes', '-'))} min, {_t((stt or {}).get('reconnects', 0))} reconnects")],
    ]
    story.append(table(summary_rows, [32 * mm, 55 * mm, 32 * mm, 55 * mm], header=False,
                       style_extra=[("BOX", (0, 0), (-1, -1), 0.5, line)]))
    if rep.get("summary"):
        story += [Spacer(1, 6), P(_t(rep["summary"]))]
    reasons = rep.get("human_review_reasons") or []
    if reasons:
        story += [P("Needs human attention", h3)] + [P(f"- {_t(r)}", base) for r in reasons]
    if rep:
        rows = [["Strengths", "Concerns"]]
        s_, c_ = rep.get("strengths") or [], (rep.get("concerns") or []) + [f"RED FLAG: {x}" for x in rep.get("red_flags") or []]
        for i in range(max(len(s_), len(c_), 1)):
            rows.append([P(_t(s_[i]) if i < len(s_) else ""), P(_t(c_[i]) if i < len(c_) else "")])
        story += [Spacer(1, 6), table(rows, [87 * mm, 87 * mm])]
    else:
        sc = rec.get("scoring") or {}
        story.append(P(f"<i>AI scoring {'failed: ' + _t(sc.get('error')) if sc.get('state') == 'failed' else 'has not run yet'}.</i>"))

    # --- integrity
    if pr:
        story.append(P("Integrity and proctoring", h2))
        story.append(P(f"Risk <b>{_t(pr['risk'].upper())}</b> ({pr['risk_points']} points). Signals are evidence for review, "
                       "not proof. Check the video before concluding anything."))
        for r in pr["reasons"]:
            story.append(P(f"- {_t(r)}"))
        d = pr["durations"]
        rows = [["Signal", "Count", "Total time"],
                ["Left the interview tab", pr["counts"].get("tab_hidden", 0), f"{d.get('tab_hidden', 0)}s"],
                ["Other window/app focused", pr["counts"].get("window_blur", 0), f"{d.get('window_blur', 0)}s"],
                ["No face on camera", pr["counts"].get("face_missing_start", 0), f"{d.get('face_missing_start', 0)}s"],
                ["Multiple faces", pr["counts"].get("multiple_faces", 0), "-"],
                ["Microphone muted", pr["counts"].get("mute_on", 0), f"{d.get('mute_on', 0)}s"],
                ["Screen sharing stopped", pr["counts"].get("screen_share_stopped", 0), f"{d.get('screen_share_stopped', 0)}s"],
                ["Paste / copy", f"{pr['counts'].get('paste', 0)} / {pr['counts'].get('copy', 0)}", "-"],
                ["Exited full screen", pr["counts"].get("fullscreen_exit", 0), "-"],
                ["Connection lost", pr["counts"].get("network_offline", 0), f"{d.get('network_offline', 0)}s"]]
        story.append(table([[P(_t(c)) for c in r] for r in rows], [90 * mm, 30 * mm, 40 * mm]))
        tl = [x for x in pr["timeline"] if x["severity"] != "info"][:80]
        if tl:
            story.append(P("Timeline of flagged events", h3))
            rows = [["When", "Question", "Event", "Detail"]] + [
                [_mmss(x["t"]) if x["t"] is not None else "-", x.get("q_id") or "-",
                 P(("<font color='#c62828'>" if x["severity"] == "high" else "") + _t(x["label"]) +
                   ("</font>" if x["severity"] == "high" else "") + (f" ({x['duration']}s)" if x.get("duration") else "")),
                 P(_t(x.get("detail", ""))[:120], small)] for x in tl]
            story.append(table(rows, [16 * mm, 18 * mm, 80 * mm, 60 * mm]))
        # snapshots: reference photo first, then flagged ones
        snaps = rec.get("images") or []
        pick = [s for s in snaps if s.get("reason") == "reference"][:1] + [s for s in snaps if s.get("reason") not in ("reference", "periodic")][:5]
        pick += [s for s in snaps if s.get("reason") == "periodic"][: max(0, 8 - len(pick))]
        cells = []
        for s in pick:
            path = store.media_path(rec["id"], s["file"])
            if path:
                try:
                    cells.append([Image(str(path), width=40 * mm, height=22.5 * mm),
                                  P(f"{_t(s.get('reason'))} {_mmss(s['at'] - (proctor.interview_start(rec) or s['at']))}", small)])
                except Exception:
                    pass
        if cells:
            story.append(P("Camera snapshots", h3))
            rows = []
            for i in range(0, len(cells), 4):
                grp = cells[i:i + 4] + [["", ""]] * (4 - len(cells[i:i + 4]))
                rows.append([c[0] for c in grp])
                rows.append([c[1] for c in grp])
            story.append(Table(rows, colWidths=[44 * mm] * 4))

    # --- per question
    story.append(P("Answers, question by question", h2))
    qres = {q.get("q_id"): q for q in rep.get("questions") or []}
    hr_scores = hr.get("scores") or {}
    for i, q in enumerate(p["questions"], 1):
        r = qres.get(q["id"], {})
        qs = qstats.get(q["id"], {})
        flags = (pr or {}).get("per_question", {}).get(q["id"])
        block = [P(f"Q{i}. {_t(q['ask'])}", h3),
                 P(f"{_t(q['type'])}{'' if q['scored'] else ' (not scored)'} &nbsp;|&nbsp; AI score <b>{_t(r.get('score') if r.get('score') is not None else '-')}</b>/5"
                   f" &nbsp;|&nbsp; HR score {_t(hr_scores.get(q['id'], '-'))} &nbsp;|&nbsp; time {_mmss(qs.get('seconds'))}, "
                   f"{qs.get('answer_words', 0)} words, {qs.get('followups', 0)} follow-ups", small)]
        if q["id"] in ((stt or {}).get("skipped") or []):
            block.append(P("<i>Skipped automatically to save time for mandatory questions.</i>", small))
        if r.get("rationale"):
            block.append(P(_t(r["rationale"])))
        for ev in r.get("evidence") or []:
            mark = {"exact": "verified", "approx": "verified (approx.)", "other_question": "said in another answer"}.get(
                ev.get("verified"), "NOT FOUND in transcript")
            block.append(P(f"&ldquo;{_t(ev.get('quote'))}&rdquo; <font color='#5d6573'>[{_t(ev.get('t'))}] {mark}</font>", base))
        if r.get("missed_points"):
            block.append(P("Missed: " + _t("; ".join(r["missed_points"])), small))
        if flags:
            block.append(P("<font color='#b45309'>Integrity during this question: " +
                           _t(", ".join(f"{k} x{v}" for k, v in flags["types"].items())) + "</font>", small))
        story.append(KeepTogether(block))

    if rep.get("resume_claims"):
        story.append(P("Resume claims checked", h2))
        rows = [["Claim", "Status", "Note"]] + [[P(_t(c.get("claim"))), P(_t(c.get("status"))), P(_t(c.get("note")), small)]
                                               for c in rep["resume_claims"]]
        story.append(table(rows, [80 * mm, 25 * mm, 70 * mm]))

    # --- session, consent, HR
    story.append(P("Sessions, device and consent", h2))
    for s in rec.get("sessions") or []:
        story.append(P(f"- {_t(_when(s.get('at')))}: IP {_t(s.get('ip'))}, {_t((s.get('ua') or '')[:110])}", small))
    dev = rec.get("device") or {}
    if dev:
        story.append(P("Device: " + _t(", ".join(f"{k}={v}" for k, v in dev.items())), small))
    cons = rec.get("consent") or {}
    story.append(P(f"Consent: {'given ' + _t(_when(cons.get('at'))) + ' from IP ' + _t(cons.get('ip')) if cons else 'not recorded'}", small))
    fb = rec.get("feedback")
    if fb:
        story.append(P(f"Candidate feedback: {_t(fb.get('rating'))}/5. {_t(fb.get('comment', ''))}", small))
    if hr.get("notes"):
        story += [P("HR notes", h3), P(_t(hr["notes"]))]

    media = rec.get("media") or []
    if media:
        story.append(P("Recordings (download from the report page or the ZIP bundle)", h3))
        for m in media:
            story.append(P(f"- {_t(m['kind'])}: {_t(m['file'])} ({round((m.get('bytes') or 0) / 1e6, 1)} MB"
                           f"{', ' + str(m.get('duration_sec')) + ' s' if m.get('duration_sec') else ''})", small))

    story += [PageBreak(), P("Full transcript", h2)]
    for ln in transcript_text(rec).splitlines()[3:]:
        if ln.startswith("==="):
            story.append(P(_t(ln.strip("= ")), h3))
        elif ln.strip():
            who_ai = "] INTERVIEWER:" in ln
            story.append(P(("<font color='#5d6573'>" if who_ai else "") + _t(ln) + ("</font>" if who_ai else ""), base))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Vera", 7)
        canvas.setFillColor(muted)
        canvas.drawString(15 * mm, 8 * mm, f"TalentLoop AI interview report | {rec['id']} | Confidential: contains personal data")
        canvas.drawRightString(195 * mm, 8 * mm, f"Page {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm,
                            bottomMargin=15 * mm, title=f"Interview report {p.get('candidate_name', '')}",
                            author="TalentLoop")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# ZIP bundle (report + transcript + data + every recording)
# ---------------------------------------------------------------------------
def bundle_zip(rec: dict, dest: Path) -> Path:
    """Blocking. Writes to dest (a temp file) so big videos never sit in memory."""
    name = base_name(rec)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{name}/report.pdf", report_pdf(rec))
        z.writestr(f"{name}/transcript.txt", transcript_text(rec))
        z.writestr(f"{name}/interview.json", json.dumps(public_record(rec), indent=1, ensure_ascii=False))
        z.writestr(f"{name}/proctoring.json", json.dumps(proctor.summary(rec) if rec.get("state") else {}, indent=1))
        for m in rec.get("media") or []:
            path = store.media_path(rec["id"], m["file"])
            if path:
                folder = "snapshots" if m.get("kind") == "snapshot" else "recordings"
                z.write(path, f"{name}/{folder}/{m['file']}", compress_type=zipfile.ZIP_STORED)
        for s in rec.get("images") or []:
            path = store.media_path(rec["id"], s["file"])
            if path:
                z.write(path, f"{name}/snapshots/{s['file']}", compress_type=zipfile.ZIP_STORED)
    return dest
