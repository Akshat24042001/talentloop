"""Reads a job description into the job form: title, summary, responsibilities, must-have and nice-to-have skills,
experience, workplace and employment type. Free (no AI) and section-aware: a skill under "Requirements" is a must-have,
under "Nice to have" it is a nice-to-have, and nothing is dropped because of its spelling."""
import re

from . import jd_schema, skills
from .resumes import CITIES

_CITY = re.compile(r"\b(" + "|".join(re.escape(c) for c in sorted(CITIES, key=len, reverse=True) if c != "Remote") + r")\b")

_SECTION_NAMES = {
    "responsibilities": r"(?:key\s+|main\s+|core\s+)?(?:responsibilit(?:y|ies)|what you(?:'|’)?ll do|what you will do|duties|role(?: and| &) responsibilities|the role|your role|day[- ]to[- ]day|you will)",
    "must": r"(?:(?:key\s+|minimum\s+|basic\s+|mandatory\s+|essential\s+)?(?:requirements?|qualifications?)|must[- ]haves?|what you(?:'|’)?ll need|what we(?:'|’)?re looking for|"
            r"who you are|required(?: skills| qualifications| experience)?|skills(?: required| needed)?|technical skills|you have|candidate profile|ideal candidate|eligibility)",
    "nice": r"(?:nice[- ]to[- ]haves?|good[- ]to[- ]haves?|preferred(?: skills| qualifications| experience)?|bonus(?: points)?|desirable|pluses|plus points|an advantage|added advantage|"
            r"it(?:'|’)?s a plus|extra credit)",
    "benefits": r"(?:benefits?|perks|what we offer|why join us|why us|compensation(?: and| &) benefits|we offer)",
    "about": r"(?:about (?:us|the company|the team|the role)|company overview|who we are|overview|job summary|summary|role summary|position summary|description|job description)",
}
_HEAD_RES = {k: re.compile(rf"^\s*(?:{v})\s*[:\-–—]?\s*$", re.I) for k, v in _SECTION_NAMES.items()}
_BULLET = re.compile(r"^\s*(?:[-•*▪●◦➢✓✔►·]|\d{1,2}[.)])\s+")
_TITLE_LABEL = re.compile(r"^\s*(?:job\s+title|position(?:\s+title)?|role|designation|title|opening|vacancy)\s*[:\-–—]\s*(.+)$", re.I)
_NOT_TITLE = re.compile(r"^\s*(?:job\s+description|jd|about\b|company|location|department|apply|posted|date|salary|ctc|experience|www\.|http)", re.I)
_WORDS_YEARS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _sections(lines: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"top": []}
    cur = "top"
    for ln in lines:
        m = _TITLE_LABEL.match(ln)
        head = None if m else next((k for k, rx in _HEAD_RES.items() if rx.match(ln.strip().rstrip(":"))), None)
        if head:
            cur = head
            out.setdefault(cur, [])
        else:
            out.setdefault(cur, []).append(ln)
    return out


def _title(lines: list[str]) -> str:
    for ln in lines[:12]:
        m = _TITLE_LABEL.match(ln)
        if m:
            return _tidy_title(m.group(1))
    for ln in lines[:8]:
        t = ln.strip(" |*#")
        if 3 <= len(t) <= 80 and not _NOT_TITLE.match(t) and not t.endswith((".", ":", ",")) and not re.search(r"@|\d{5,}", t) and len(t.split()) <= 9:
            return _tidy_title(t)
    return ""


def _tidy_title(t: str) -> str:
    t = re.split(r"\s[|–—]\s|\s-\s(?=[A-Z])", t.strip(" .|*#"))[0].strip()
    t = re.sub(r"\s*\((?:remote|hybrid|on-?site|full[- ]time|part[- ]time|contract|\d+\s*openings?).*?\)\s*$", "", t, flags=re.I)
    return t[:120]


def _years(text: str) -> tuple[int | None, int | None]:
    t = re.sub(r"\b(" + "|".join(_WORDS_YEARS) + r")\b(?=\s*(?:\+|-|to)?\s*(?:years?|yrs?))", lambda m: str(_WORDS_YEARS[m.group(1).lower()]), text, flags=re.I)
    m = re.search(r"(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)", t, re.I)
    if m and int(m.group(1)) <= int(m.group(2)) <= 40:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(?:minimum|min\.?|at least|over|more than)?\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)(?:\s+of)?(?:\s+\w+){0,3}?\s+(?:experience|exp)", t, re.I) \
        or re.search(r"(?:experience|exp)\b[^.\n]{0,25}?(\d{1,2})\s*\+?\s*(?:years?|yrs?)", t, re.I)
    if m and int(m.group(1)) <= 40:
        return int(m.group(1)), None
    if re.search(r"\b(?:fresher|freshers|entry[- ]level|no experience (?:required|needed))\b", t, re.I):
        return 0, 1
    return None, None


def _bullets(body: list[str]) -> list[str]:
    items = []
    for ln in body:
        if _BULLET.match(ln):
            items.append(_BULLET.sub("", ln).strip())
        elif ln.strip() and items and not ln.strip()[0].isupper() and len(ln.strip()) < 160:
            items[-1] += " " + ln.strip()                        # a wrapped bullet continues on the next line
        elif ln.strip() and len(ln.split()) >= 4 and len(ln) <= 220 and not ln.rstrip().endswith(":"):
            items.append(ln.strip())
    return [re.sub(r"\s+", " ", x)[:200] for x in items if len(x) > 6]


def parse(text: str) -> dict:
    lines = [ln.rstrip() for ln in (text or "").replace("\r", "").splitlines() if ln.strip()]
    secs = _sections(lines)
    body = lambda k: secs.get(k, [])
    must_src = "\n".join(body("must"))
    nice_src = "\n".join(body("nice"))
    found_all = skills.extract_all(text)
    must = skills.extract_all(must_src) if must_src else []
    nice = [s for s in (skills.extract_all(nice_src) if nice_src else []) if s not in must]
    if not must:                                              # no requirements section: every skill named in the JD, nice-to-haves apart
        must = [s for s in found_all if s not in nice]
    for s in skills.extract_listed(text):
        if s not in must and s not in nice:
            must.append(s)
    # a "nice to have" line inside the requirements bullets ("Bonus: Kafka") also goes to nice-to-have
    for ln in body("must"):
        m = re.match(r"^\s*(?:[-•*]\s*)?(?:nice to have|preferred|bonus|good to have|plus)\s*[:\-–]\s*(.+)$", ln, re.I)
        if m:
            for s in skills.extract_all(m.group(1)):
                if s in must:
                    must.remove(s)
                if s not in nice:
                    nice.append(s)
    # non-technical skills go to their own field (stated, or implied: "work with cross-functional teams" -> Teamwork)
    soft_names = set(skills.SOFT_EVIDENCE) | {"Communication", "Leadership", "Mentoring", "Stakeholder Management", "Problem Solving",
                                              "Time Management", "Teamwork", "Negotiation", "Public Speaking"}
    soft = [s for s in found_all if s in soft_names] + [s for s in skills.infer_soft(text) if s not in found_all]
    must = [s for s in must if s not in soft_names]
    nice = [s for s in nice if s not in soft_names]
    about = " ".join(ln.strip() for ln in body("about")[:6] if len(ln.split()) >= 6) or next((ln.strip() for ln in body("top")[1:] if len(ln) > 120), "")
    lo, hi = _years("\n".join(body("must")) or text)
    if lo is None:
        lo, hi = _years(text)
    low = text.lower()
    emp = next((e for e, rx in (("Internship", r"\binterns?(?:hip)?\b"), ("Contract", r"\bcontract(?:ual)?\b|\bfreelance\b"), ("Part-time", r"part[- ]time"),
                                ("Full-time", r"full[- ]time|permanent")) if re.search(rx, low)), "")
    work = "Remote" if re.search(r"\bfully remote\b|\bremote(?: only|-first)?\b", low) and not re.search(r"\bhybrid\b|on-?site|work from office", low) \
        else "Hybrid" if "hybrid" in low else "On-site" if re.search(r"on-?site|work from office|\bwfo\b", low) else ""
    fields = {"title": _title(lines), "summary": about[:900], "responsibilities": _bullets(body("responsibilities"))[:10],
              "must_have_skills": must[:15], "nice_to_have_skills": nice[:15], "soft_skills": list(dict.fromkeys(soft))[:12], "tools": found_all[:20],
              "benefits": [], "employment_type": emp, "workplace_type": work}
    if lo is not None:
        fields["experience_min"] = lo
    if hi is not None:
        fields["experience_max"] = hi
    cities = list(dict.fromkeys(m.group(1) for m in _CITY.finditer(text)))
    if cities:
        fields["locations"] = cities[:3]
    KEEP = ("must_have_skills", "nice_to_have_skills", "responsibilities", "tools")      # callers expect these lists, even empty
    return jd_schema.clean({k: v for k, v in fields.items() if k in KEEP or v not in ("", [], None)})
