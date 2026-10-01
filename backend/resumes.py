"""Free resume parsing (no AI): text extraction plus regex/dictionary extraction of the fields matching needs."""
import io
import re
import time
from datetime import date

from . import skills

MAX_RESUME_BYTES = 10 * 1024 * 1024
RESUME_TYPES = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ".txt": "text/plain", ".md": "text/plain", ".rtf": "application/rtf"}

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{2,5}\)?[\s-]?)?\d{3,5}[\s-]?\d{4,6}")
LINK = re.compile(r"(?:https?://)?(?:www\.)?(?:linkedin\.com/in/[\w-]+|github\.com/[\w-]+|[\w-]+\.(?:dev|io|me|com)/[\w/-]*)", re.I)
YEARS = re.compile(r"(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?)(?:\s+of)?(?:\s+\w+){0,3}?\s+(?:experience|exp)\b", re.I)
YEARS_LABEL = re.compile(r"(?:total\s+|overall\s+)?(?:work\s+)?experience\s*[:\-–]\s*(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?)", re.I)
YEARS_SIMPLE = re.compile(r"\b(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?)\b", re.I)
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
RANGE = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*(\d{4})\s*[-–—to]+\s*(present|current|now|till date|"
                   r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*\d{4})", re.I)
NOTICE = re.compile(r"notice\s*(?:period)?\s*[:\-]?\s*(?:of\s*)?(\d{1,3})\s*(days?|months?|weeks?)", re.I)
CITIES = ["Bengaluru", "Bangalore", "Mumbai", "Navi Mumbai", "Thane", "Pune", "Hyderabad", "Chennai", "Kolkata", "New Delhi", "Delhi", "Noida",
          "Greater Noida", "Gurugram", "Gurgaon", "Ghaziabad", "Faridabad", "Ahmedabad", "Surat", "Vadodara", "Jaipur", "Lucknow", "Kochi",
          "Thiruvananthapuram", "Trivandrum", "Coimbatore", "Indore", "Bhopal", "Nagpur", "Chandigarh", "Mohali", "Bhubaneswar", "Visakhapatnam",
          "Mysuru", "Mysore", "Mangaluru", "Goa", "Patna", "Ranchi", "Dehradun", "Remote", "Dubai", "Abu Dhabi", "Singapore", "London",
          "New York", "San Francisco", "Seattle", "Austin", "Toronto", "Sydney", "Berlin", "Amsterdam"]
CITY = re.compile(r"\b(" + "|".join(re.escape(c) for c in sorted(CITIES, key=len, reverse=True)) + r")\b", re.I)
CTC = re.compile(r"(?:current|expected)\s*(?:ctc|salary|package)\s*[:\-]?\s*(?:inr|rs\.?|₹)?\s*([\d.,]+)\s*(lpa|lakhs?|l|k|cr)?", re.I)


def extract_text(raw: bytes, filename: str) -> str:
    name = (filename or "").lower()
    if name.endswith(".pdf") or raw[:4] == b"%PDF":
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(raw)).pages)
    if name.endswith(".docx"):
        import docx
        d = docx.Document(io.BytesIO(raw))
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        return "\n".join(parts)
    if name.endswith(".rtf"):
        txt = raw.decode("utf-8", errors="ignore")
        return re.sub(r"\\[a-z]+-?\d* ?|[{}]", " ", txt)
    return raw.decode("utf-8", errors="ignore")


def _years_from_ranges(text: str) -> float | None:
    spans = []
    today = date.today()
    for m in RANGE.finditer(text):
        try:
            a = date(int(m.group(2)), MONTHS[m.group(1)[:3].lower()], 1)
            end = m.group(3).lower()
            if end.startswith(("present", "current", "now", "till")):
                b = today
            else:
                mm = re.match(r"([a-z]+)\.?\s*(\d{4})", end)
                b = date(int(mm.group(2)), MONTHS[mm.group(1)[:3]], 1)
            if 1970 < a.year <= today.year and a <= b:
                spans.append((a, b))
        except (KeyError, ValueError, AttributeError):
            continue
    if not spans:
        return None
    spans.sort()
    total, cur_a, cur_b = 0, spans[0][0], spans[0][1]
    for a, b in spans[1:]:                      # merge overlapping jobs
        if a <= cur_b:
            cur_b = max(cur_b, b)
        else:
            total += (cur_b - cur_a).days
            cur_a, cur_b = a, b
    total += (cur_b - cur_a).days
    return round(total / 365.25, 1)


def _guess_name(text: str, email: str) -> str:
    for line in [ln.strip() for ln in text.splitlines() if ln.strip()][:6]:
        if EMAIL.search(line) or any(ch.isdigit() for ch in line) or len(line) > 40:
            continue
        words = line.replace("|", " ").split()
        if 1 < len(words) <= 4 and all(w[:1].isupper() for w in words if w.isalpha()):
            return " ".join(words[:4])
    if email:
        local = re.split(r"[._\d]+", email.split("@")[0])
        return " ".join(p.capitalize() for p in local if p)[:60]
    return ""


def parse(text: str) -> dict:
    t = text or ""
    emails = list(dict.fromkeys(e.lower().strip(".") for e in EMAIL.findall(t)))[:3]
    phones, seen = [], set()
    for p in PHONE.findall(t):
        digits = re.sub(r"\D", "", p)
        if 10 <= len(digits) <= 13 and digits not in seen:
            seen.add(digits)
            phones.append(re.sub(r"\s+", " ", p.strip()))
    stated = [float(x) for x in YEARS.findall(t) + YEARS_LABEL.findall(t) if float(x) < 45]
    ranged = _years_from_ranges(t)
    years = max(stated) if stated else ranged
    notice = None
    nm = NOTICE.search(t)
    if nm:
        n, unit = int(nm.group(1)), nm.group(2).lower()
        notice = n * 30 if unit.startswith("month") else n * 7 if unit.startswith("week") else n
    head = "\n".join([ln for ln in t.splitlines() if ln.strip()][:8])     # the contact block at the top
    cm = CITY.search(head)
    location = next((c for c in CITIES if cm and c.lower() == cm.group(1).lower()), "")
    return {
        "emails": emails, "location": location, "phones": phones[:2], "links": list(dict.fromkeys(LINK.findall(t)))[:5],
        "skills": sorted(skills.extract(t)), "years": years, "years_source": "stated" if stated else ("dates" if ranged else None),
        "notice_days": notice, "name_guess": _guess_name(t, emails[0] if emails else ""), "chars": len(t), "parsed_at": time.time(),
    }


def profile_text(p: dict) -> str:
    """Plain text for a candidate who built a profile instead of uploading a resume (used for matching and PDF)."""
    lines = [p.get("name", ""), p.get("headline", ""), p.get("location", ""), p.get("summary", "")]
    for e in p.get("experience") or []:
        lines.append(f"{e.get('title', '')} at {e.get('company', '')} ({e.get('start', '')} - {e.get('end', '') or 'Present'})")
        lines.append(e.get("description", ""))
    for e in p.get("education") or []:
        lines.append(f"{e.get('degree', '')} {e.get('field', '')}, {e.get('school', '')} {e.get('year', '')}")
    if p.get("skills"):
        lines.append("Skills: " + ", ".join(p["skills"]))
    for pr in p.get("projects") or []:
        lines.append(f"Project: {pr.get('name', '')}. {pr.get('description', '')}")
    if p.get("certifications"):
        lines.append("Certifications: " + ", ".join(p["certifications"]))
    if p.get("languages"):
        lines.append("Languages: " + ", ".join(p["languages"]))
    if p.get("total_experience_years") not in (None, ""):
        lines.append(f"{p['total_experience_years']} years of experience")
    return "\n".join(x for x in lines if x)
