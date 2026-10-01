"""PDF documents: the full job description, and a resume for candidates who built one in the form."""
import io
import time

from . import exports


def _doc(title: str):
    exports._fonts()
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    ink, muted, brand = colors.HexColor("#131722"), colors.HexColor("#5f6878"), colors.HexColor("#2848e6")
    base = ParagraphStyle("b", fontName="Vera", fontSize=9.6, leading=14, textColor=ink, shaping=1)
    st = {
        "base": base, "small": ParagraphStyle("s", parent=base, fontSize=8.4, leading=11.5, textColor=muted),
        "h1": ParagraphStyle("h1", parent=base, fontName="VeraBd", fontSize=20, leading=25),
        "h2": ParagraphStyle("h2", parent=base, fontName="VeraBd", fontSize=11.5, leading=15, spaceBefore=12, spaceAfter=4, textColor=brand),
        "h3": ParagraphStyle("h3", parent=base, fontName="VeraBd", fontSize=10, leading=13.5, spaceBefore=6),
        "bullet": ParagraphStyle("bl", parent=base, leftIndent=12, bulletIndent=2, spaceAfter=1.5),
    }
    return st, mm, colors, A4


def _build(story, title: str, footer: str) -> bytes:
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate
    from reportlab.lib.pagesizes import A4

    def foot(canvas, doc):
        canvas.saveState()
        canvas.setFont("Vera", 7)
        canvas.setFillColorRGB(0.37, 0.41, 0.47)
        canvas.drawString(18 * mm, 9 * mm, footer)
        canvas.drawRightString(192 * mm, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                      title=title, author="TalentLoop").build(story, onFirstPage=foot, onLaterPages=foot)
    return buf.getvalue()


def jd_pdf(jd: dict) -> bytes:
    """jd: output of jd_schema.compose()."""
    from reportlab.platypus import Paragraph, Spacer
    st, mm, colors, _ = _doc(jd["title"])
    t = exports._t
    story = [Paragraph(t(jd["title"]), st["h1"]), Paragraph(t(jd["company"]), st["h3"]), Spacer(1, 3),
             Paragraph(t("  ·  ".join(jd["facts"])), st["small"]), Spacer(1, 6)]
    for sec in jd["sections"]:
        story.append(Paragraph(t(sec["title"]), st["h2"]))
        for para in [p for p in (sec.get("body") or "").split("\n") if p.strip()]:
            story.append(Paragraph(t(para), st["base"]))
        for it in sec.get("items") or []:
            story.append(Paragraph(t(it), st["bullet"], bulletText="•"))
    if jd.get("contact"):
        story += [Spacer(1, 8), Paragraph(t(f"Questions? Contact {jd['contact']}"), st["small"])]
    return _build(story, jd["title"], f"{jd['company']} · {jd['title']} · generated {time.strftime('%d %b %Y')}")


def resume_pdf(p: dict) -> bytes:
    from reportlab.platypus import Paragraph, Spacer
    st, mm, colors, _ = _doc(p.get("name", "Resume"))
    t = exports._t
    contact = "  ·  ".join(x for x in [p.get("email"), p.get("phone"), p.get("location"), p.get("linkedin"), p.get("portfolio")] if x)
    story = [Paragraph(t(p.get("name", "")), st["h1"])]
    if p.get("headline"):
        story.append(Paragraph(t(p["headline"]), st["h3"]))
    story += [Paragraph(t(contact), st["small"]), Spacer(1, 4)]
    if p.get("summary"):
        story += [Paragraph("Summary", st["h2"]), Paragraph(t(p["summary"]), st["base"])]
    if p.get("experience"):
        story.append(Paragraph("Experience", st["h2"]))
        for e in p["experience"]:
            story.append(Paragraph(t(f"{e.get('title', '')} · {e.get('company', '')}"), st["h3"]))
            story.append(Paragraph(t(f"{e.get('start', '')} – {e.get('end') or 'Present'}" + (f" · {e['location']}" if e.get("location") else "")), st["small"]))
            for line in [x.strip(" -•") for x in (e.get("description") or "").split("\n") if x.strip()]:
                story.append(Paragraph(t(line), st["bullet"], bulletText="•"))
    if p.get("education"):
        story.append(Paragraph("Education", st["h2"]))
        for e in p["education"]:
            story.append(Paragraph(t(" · ".join(x for x in [f"{e.get('degree', '')} {e.get('field', '')}".strip(), e.get("school"), str(e.get("year") or "")] if x)), st["base"]))
    if p.get("skills"):
        story += [Paragraph("Skills", st["h2"]), Paragraph(t(", ".join(p["skills"])), st["base"])]
    if p.get("projects"):
        story.append(Paragraph("Projects", st["h2"]))
        for pr in p["projects"]:
            story.append(Paragraph(t(pr.get("name", "")), st["h3"]))
            if pr.get("description"):
                story.append(Paragraph(t(pr["description"]), st["base"]))
    for key, label in (("certifications", "Certifications"), ("languages", "Languages")):
        if p.get(key):
            story += [Paragraph(label, st["h2"]), Paragraph(t(", ".join(p[key])), st["base"])]
    return _build(story, p.get("name", "Resume"), f"{p.get('name', '')} · resume")
