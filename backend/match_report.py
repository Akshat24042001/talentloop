"""The detailed candidate-job match report: how the fit score is built, requirement by requirement, with the AI
report when one exists. Served as JSON for the report page and as a PDF for download."""
import time

from . import db, jd_schema, matching, refs, verify

SIGNALS = (("skills", "Skills"), ("experience", "Experience"), ("relevance", "Keyword relevance"),
           ("location", "Location"), ("logistics", "Notice & salary"))


def _money(v, cur: str) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return ""
    if cur == "INR":
        return f"₹{v / 100000:.1f} L" if v >= 100000 else f"₹{int(v):,}"
    return f"{cur} {int(v):,}"


def build(s, job: db.Job, cand: db.Candidate, weights: dict, default_top_n: int) -> dict:
    cands, idx = matching.load_pool(s, job.org_id)
    me = next((i for i, c in enumerate(cands) if c.id == cand.id), None)
    jf = matching.job_features(job, default_top_n)
    if me is None:
        score, bd, ko = 0.0, {}, []
    else:
        raw = idx.bm25(jf.terms)
        top = max(raw.values()) if raw else 0
        score, bd, ko = matching.score_one(jf, cands[me], (raw.get(me, 0) / top) if top else 0, weights)
    total_w = sum(max(0, float(weights.get(k, 0) or 0)) for k, _ in SIGNALS) or 1
    signals = []
    for k, label in SIGNALS:
        w = max(0, float(weights.get(k, 0) or 0)) / total_w
        sc = float((bd.get(k) or {}).get("score") or 0)
        signals.append({"key": k, "label": label, "weight": round(w * 100), "score": round(sc * 100), "points": round(w * sc * 100, 1)})

    f, cur = job.fields or {}, (job.fields or {}).get("currency") or "INR"
    sk = bd.get("skills") or {}
    skills = ([{"skill": x, "kind": "Must-have", "status": "matched"} for x in sk.get("must_matched", [])]
              + [{"skill": x, "kind": "Must-have", "status": "related"} for x in sk.get("must_related", [])]
              + [{"skill": x, "kind": "Must-have", "status": "missing"} for x in sk.get("must_missing", [])]
              + [{"skill": x, "kind": "Nice-to-have", "status": "matched"} for x in sk.get("nice_matched", [])]
              + [{"skill": x, "kind": "Nice-to-have", "status": "related"} for x in sk.get("nice_related", [])])
    nice_all = [x for x in (f.get("nice_to_have_skills") or []) if isinstance(x, str)]
    seen = {x["skill"].lower() for x in skills}
    skills += [{"skill": x, "kind": "Nice-to-have", "status": "missing"} for x in nice_all if x.lower() not in seen]

    ex, lo, lg = bd.get("experience") or {}, bd.get("location") or {}, bd.get("logistics") or {}
    def status(v: float) -> str:
        return "good" if v >= 0.75 else "partial" if v >= 0.4 else "gap"
    comparison = [
        {"label": "Experience", "required": jd_schema.experience_text(f) or "Not set",
         "candidate": f"{cand.years:g} years" if cand.years is not None else "Not stated", "note": ex.get("note", ""),
         "status": "info" if cand.years is None else status(ex.get("score", 0))},
        {"label": "Location", "required": " · ".join(filter(None, [f.get("workplace_type"), ", ".join(f.get("locations") or [])])) or "Not set",
         "candidate": cand.location or lo.get("candidate") or "Not stated", "note": lo.get("note", ""), "status": status(lo.get("score", 0))},
        {"label": "Notice period", "required": f"Up to {f['max_notice_days']} days" if f.get("max_notice_days") not in (None, "") else "No limit",
         "candidate": f"{int(cand.notice_days)} days" if cand.notice_days is not None else "Not stated", "note": lg.get("notice", ""),
         "status": "info" if cand.notice_days is None else "gap" if any("notice" in k.lower() for k in ko) else status(lg.get("score", 0))},
        {"label": "Salary", "required": jd_schema.salary_text(f) or "Not set",
         "candidate": _money(cand.expected_salary, cur) or "Not stated", "note": lg.get("salary", ""),
         "status": "info" if cand.expected_salary is None else "gap" if any("salary" in k.lower() for k in ko) else status(lg.get("score", 0))},
        {"label": "Must-have skills", "required": f"{len(jf.must)} skills",
         "candidate": f"{len(sk.get('must_matched', []))} matched, {len(sk.get('must_related', []))} related",
         "note": "", "status": status(sk.get("score", 0))},
    ]
    if f.get("education"):
        p = cand.profile or {}
        edu = "; ".join(filter(None, [" ".join(filter(None, [e.get("degree"), e.get("field")])) for e in (p.get("education") or []) if isinstance(e, dict)])) or cand.college or "Not stated"
        comparison.append({"label": "Education", "required": str(f["education"]), "candidate": edu, "note": "", "status": "info"})

    # The shortlist's average on each signal (for the spider chart) and everyone's fit score (for the distribution).
    rows = s.query(db.Match.score, db.Match.rank, db.Match.breakdown).filter(db.Match.job_id == job.id).all()
    dist = sorted(round(float(r.score or 0)) for r in rows)
    top_n = max(1, int(job.top_n or default_top_n or 5))
    short = [r.breakdown or {} for r in rows if r.rank and r.rank <= top_n]
    avg = {k: round(sum(float((b.get(k) or {}).get("score") or 0) for b in short) / len(short) * 100) for k, _ in SIGNALS} if short else {}
    m = s.query(db.Match).filter_by(job_id=job.id, candidate_id=cand.id).first()
    shortlisted = s.query(db.Match).filter(db.Match.job_id == job.id, db.Match.rank < 9999).count()
    app = s.query(db.Application).filter_by(job_id=job.id, candidate_id=cand.id).first()
    return {
        "job": {"id": job.id, "ref": refs.job_ref(job), "title": job.title, "department": job.department, "status": job.status},
        "candidate": {"id": cand.id, "ref": refs.cand_ref(cand), "name": cand.name, "headline": cand.headline, "email": cand.email,
                      "location": cand.location, "years": cand.years, "current_company": cand.current_company},
        "score": score, "knocked_out": ko, "signals": signals, "skills": skills, "comparison": comparison,
        "shortlist_avg": avg, "shortlist_size": len(short), "distribution": dist, "verification": verify.ensure(s, cand),
        "verdict_line": verdict_line(score, ko, skills, comparison, cand),
        "rank": m.rank if m and m.rank < 9999 else None, "ranked": shortlisted,
        "ai": (m.ai_report if m else None), "ai_score": (m.ai_score if m else None), "ai_at": (m.ai_at if m else None),
        "application": {"ref": refs.app_ref(app.id), "stage": app.stage} if app else None,
        "generated_at": time.time(),
    }


def verdict_line(score: float, ko: list, skills: list, comparison: list, cand) -> dict:
    """One sentence on the fit, built only from the numbers above (no AI, so nothing is invented)."""
    must = [x for x in skills if x["kind"] == "Must-have"]
    hit = [x["skill"] for x in must if x["status"] == "matched"]
    miss = [x["skill"] for x in must if x["status"] == "missing"]
    rows = {r["label"]: r for r in comparison}
    pros, cons = [], []
    if must:
        (pros if len(hit) >= 0.75 * len(must) else cons).append(
            f"has {len(hit)} of {len(must)} must-have skills" if hit else f"none of the {len(must)} must-have skills")
    if miss:
        cons.append("no " + ", ".join(miss[:3]) + (f" and {len(miss) - 3} more" if len(miss) > 3 else ""))
    ex = rows.get("Experience")
    if ex and ex["status"] == "good":
        pros.append(f"{ex['candidate']} of experience ({ex['required']} asked)")
    elif ex and ex["status"] in ("partial", "gap"):
        cons.append(f"{ex['candidate']} of experience vs {ex['required']} asked")
    for label in ("Location", "Notice period", "Salary"):
        r = rows.get(label)
        if r and r["status"] == "gap":
            cons.append(f"{label.lower()} {r['candidate']} vs {r['required']}")
        elif r and r["status"] == "good" and label == "Location" and len(pros) < 3:
            pros.append(f"based in {r['candidate']}")
    if ko:
        return {"level": "Screened out", "tone": "danger", "text": "Screened out by the job's rules: " + "; ".join(ko[:2]) + "."}
    level, tone = ("Strong fit", "success") if score >= 75 else ("Possible fit", "warning") if score >= 55 else ("Weak fit", "danger")
    parts = []
    if pros:
        parts.append("; ".join(pros[:2]))
    if cons:
        parts.append(("Watch: " if level != "Weak fit" else "Main gaps: ") + "; ".join(cons[:2]))
    text = ". ".join(p[0].upper() + p[1:] for p in parts) or "Not enough in the resume to compare with the job"
    return {"level": f"{level} · {round(score)}/100", "tone": tone, "text": text + "."}


def pdf(d: dict, company: str) -> bytes:
    from reportlab.graphics.shapes import Drawing, Rect, String
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
    from . import docs_pdf, exports
    st, mm, colors, _ = docs_pdf._doc("Match report")
    t = exports._t
    green, amber, red, track, brand = (colors.HexColor(x) for x in ("#0ca30c", "#d99a06", "#d03b3b", "#e8ecf3", "#2848e6"))
    tone = {"good": green, "matched": green, "partial": amber, "related": amber, "gap": red, "missing": red}
    c, j, ai = d["candidate"], d["job"], d.get("ai") or {}
    story = [Paragraph(t(f"{c['name']} for {j['title']}"), st["h1"]),
             Paragraph(t(" · ".join(filter(None, [c.get("headline"), c.get("location"), f"{c['years']:g} years" if c.get("years") is not None else ""]))), st["small"]),
             Spacer(1, 8)]
    boxes = [["Fit score", "AI score", "Shortlist rank", "Verdict"],
             [f"{round(d['score'])}/100", f"{round(d['ai_score'])}/100" if d.get("ai_score") is not None else "Not run",
              f"#{d['rank']} of {d['ranked']}" if d.get("rank") else "Not ranked", (ai.get("verdict") or "-").title()]]
    bt = Table(boxes, colWidths=[43 * mm] * 4)
    bt.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), "Vera", 8), ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#5f6878")),
                            ("FONT", (0, 1), (-1, 1), "VeraBd", 15), ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f4f6fb")),
                            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#dfe4ee")), ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
                            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [bt]
    if d.get("knocked_out"):
        story += [Spacer(1, 6), Paragraph(t("Screened out: " + "; ".join(d["knocked_out"])), st["base"])]
    if d.get("verdict_line"):
        story += [Spacer(1, 6), Paragraph(t(f"{d['verdict_line']['level']}: {d['verdict_line']['text']}"), st["base"])]
    vf = d.get("verification") or {}
    if vf:
        story += [Paragraph("Resume check", st["h2"]), Paragraph(t(f"{vf.get('level')} ({vf.get('score')}/100)."), st["base"])]
        story += [Paragraph(t(f"{x['title']}" + (f": {x['evidence']}" if x.get("evidence") else "")), st["bullet"], bulletText="•") for x in (vf.get("findings") or [])[:5]]
    if ai.get("summary"):
        story += [Paragraph("AI summary", st["h2"]), Paragraph(t(ai["summary"]), st["base"])]

    story.append(Paragraph("How the fit score is built", st["h2"]))
    width, row_h = 174 * mm, 15
    dr = Drawing(width, row_h * len(d["signals"]) + 4)
    for i, sg in enumerate(d["signals"]):
        y = row_h * (len(d["signals"]) - 1 - i) + 4
        dr.add(String(0, y + 3, sg["label"], fontName="Vera", fontSize=8))
        dr.add(Rect(40 * mm, y + 1, 90 * mm, 7, fillColor=track, strokeColor=None))
        dr.add(Rect(40 * mm, y + 1, 90 * mm * sg["score"] / 100, 7, fillColor=brand, strokeColor=None))
        dr.add(String(133 * mm, y + 3, f"{sg['score']}% x weight {sg['weight']}% = {sg['points']} pts", fontName="Vera", fontSize=7.5))
    story += [dr]

    def table(rows, widths, colour_col=None):
        tb = Table(rows, colWidths=widths, repeatRows=1)
        style = [("FONT", (0, 0), (-1, 0), "VeraBd", 8), ("FONT", (0, 1), (-1, -1), "Vera", 8), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#e3e7ef")), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
        if colour_col is not None:
            for r, row in enumerate(rows[1:], 1):
                c_ = tone.get(str(row[colour_col]).lower())
                if c_:
                    style.append(("TEXTCOLOR", (colour_col, r), (colour_col, r), c_))
        tb.setStyle(TableStyle(style))
        return tb
    P = lambda x: Paragraph(t(x or "-"), st["small"])
    story += [Paragraph("Requirements vs candidate", st["h2"]),
              table([["Requirement", "Job asks for", "Candidate", "Fit"]] + [[r["label"], P(r["required"]), P(r["candidate"] + (f" ({r['note']})" if r.get("note") and r["note"] not in r["candidate"] else "")), {"good": "Good", "partial": "Partial", "gap": "Gap", "info": "-"}[r["status"]]] for r in d["comparison"]],
                    [32 * mm, 52 * mm, 70 * mm, 20 * mm], colour_col=3)]
    if d["skills"]:
        story += [Paragraph("Skills", st["h2"]),
                  table([["Skill", "Type", "Status"]] + [[x["skill"], x["kind"], x["status"].title()] for x in d["skills"]], [80 * mm, 50 * mm, 44 * mm], colour_col=2)]
    for title, key in (("Strengths", "strengths"), ("Gaps", "gaps"), ("Risks", "risks"), ("Questions to ask in the interview", "interview_questions")):
        items = ai.get(key) or []
        if items:
            story.append(Paragraph(title, st["h2"]))
            story += [Paragraph(t(x), st["bullet"], bulletText="•") for x in items]
    if not ai:
        story += [Spacer(1, 8), Paragraph("No AI report yet: it is written for each job's shortlist from the Match center.", st["small"])]
    return docs_pdf._build(story, f"{c['name']} - {j['title']}", f"{company} · Match report · {c['name']} for {j['title']} · {time.strftime('%d %b %Y')}")
