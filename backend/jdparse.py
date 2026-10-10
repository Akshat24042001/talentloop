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


_SENIORITY = [("Intern", r"\bintern(?:ship)?\b"), ("Lead / Principal", r"\b(?:lead|principal|staff)\b"), ("Senior manager", r"\bsenior manager\b"),
              ("Director", r"\bdirector\b"), ("VP", r"\b(?:vp|vice president)\b"), ("C-level", r"\b(?:cto|ceo|cfo|coo|chief)\b"), ("Manager", r"\bmanager\b"),
              ("Senior", r"\b(?:senior|sr\.?)\b"), ("Associate", r"\bassociate\b"), ("Entry level", r"\b(?:junior|jr\.?|entry[- ]level|fresher|trainee|graduate)\b")]
_DEPTS = [("Engineering", r"\b(?:engineer|developer|devops|sre|software|backend|frontend|full[- ]?stack|qa|test)\b"), ("Data & Analytics", r"\b(?:data|analytics|analyst|machine learning|ml|bi)\b"),
          ("Design", r"\b(?:designer|ux|ui|design)\b"), ("Product", r"\bproduct (?:manager|owner)\b"), ("Sales", r"\b(?:sales|business development|bde|account executive)\b"),
          ("Marketing", r"\b(?:marketing|seo|content|brand|growth)\b"), ("Customer Support", r"\b(?:customer support|support executive|helpdesk|customer service)\b"),
          ("Customer Success", r"\bcustomer success\b"), ("Human Resources", r"\b(?:hr|human resources|recruiter|talent acquisition)\b"),
          ("Finance", r"\b(?:finance|accountant|accounts|audit|tax)\b"), ("Operations", r"\b(?:operations|logistics|supply chain)\b")]
_EDU_MAP = [("PhD", r"\bph\.?\s?d\b|doctorate"), ("MBA", r"\bmba\b|\bpgdm\b"), ("Master's degree", r"\bmaster'?s?\b|\bm\.?\s?tech\b|\bm\.?\s?sc\b|\bmca\b|post[- ]?graduat"),
            ("Bachelor's degree", r"\bbachelor'?s?\b|\bb\.?\s?tech\b|\bb\.?\s?e\b|\bb\.?\s?sc\b|\bbca\b|\bb\.?\s?com\b|\bgraduat(?:e|ion)\b|\bdegree\b"),
            ("Diploma", r"\bdiploma\b"), ("High school", r"\b(?:12th|hsc|high school|higher secondary)\b"),
            ("Professional certification (CA, CS, etc.)", r"\bchartered accountant\b|\b(?:ca|cs|cma|acca)\s+(?:qualified|required)\b")]


def _more(text: str, secs: dict) -> dict:
    """The rest of the job form: seniority, department, salary, openings, education, office days, shift, travel, notice, languages,
    certifications, benefits, reporting line, company description."""
    from .jd_schema import DEPARTMENTS, EDUCATION, SENIORITY
    low, out = text.lower(), {}
    head = " ".join(text.splitlines()[:4]).lower()
    out["seniority"] = next((s for s, rx in _SENIORITY if re.search(rx, head)), "")
    out["department"] = next((d for d, rx in _DEPTS if re.search(rx, head) and d in DEPARTMENTS), "") or next((d for d, rx in _DEPTS if re.search(rx, low) and d in DEPARTMENTS), "")
    for m in re.finditer(r"(?:(₹|inr|rs\.?|\$|usd|€|eur|£|gbp|aed|sgd)\s*)?([\d][\d,.]*)\s*(lpa|lakhs?|lacs?|l|k|cr)?\s*(?:-|–|to)\s*(?:₹|inr|rs\.?|\$|usd|€|eur|£|gbp|aed|sgd)?\s*([\d][\d,.]*)\s*(lpa|lakhs?|lacs?|l|k|cr)?"
                  r"(?:\s*(?:per|/|a)\s*(annum|year|yr|month|mo|hour|hr))?", low):
        if not m or "salary_min" in out:
            break
        if not (m.group(1) or m.group(3) or m.group(5) or re.search(r"salary|ctc|compensation|pay|package", low[max(0, m.start() - 60):m.start()])):
            continue
        if re.match(r"\s*\+?\s*(?:years?|yrs?)", low[m.end():m.end() + 8]):
            continue
        unit = m.group(5) or m.group(3)
        mult = {"l": 1e5, "lpa": 1e5, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "k": 1e3, "cr": 1e7}.get(unit or "", 1)
        try:
            a, b = float(m.group(2).replace(",", "")) * mult, float(m.group(4).replace(",", "")) * mult
            if 0 < a <= b:
                cur = {"₹": "INR", "inr": "INR", "rs": "INR", "rs.": "INR", "$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR", "£": "GBP", "gbp": "GBP", "aed": "AED", "sgd": "SGD"}.get(m.group(1) or "", "INR" if unit in ("l", "lpa", "lakh", "lakhs", "lac", "lacs", "cr") else "")
                per = {"month": "Month", "mo": "Month", "hour": "Hour", "hr": "Hour"}.get(m.group(6) or "", "Year")
                out.update({"salary_min": int(a), "salary_max": int(b), "pay_period": per, **({"currency": cur} if cur else {})})
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,3})\s+(?:open\s+)?(?:positions?|openings?|vacanc(?:y|ies)|roles?|seats?)\b", low) or re.search(r"\b(?:openings?|positions?|vacanc(?:y|ies))\s*[:\-]\s*(\d{1,3})\b", low)
    if m:
        out["openings"] = int(m.group(1))
    edu_src = "\n".join(secs.get("must", [])) or text
    out["education"] = next((e for e, rx in _EDU_MAP if re.search(rx, edu_src, re.I) and e in EDUCATION), "")
    m = re.search(r"\b(?:degree|graduat\w*|bachelor'?s?|master'?s?|b\.?\s?tech|b\.?\s?e)\b[^.\n]{0,25}?\bin\s+([A-Z][A-Za-z &,/]{2,60}?)(?:\s+or\s+(?:a\s+)?related(?:\s+field)?)?(?:[.,;\n]|$)", text)
    if m:
        out["field_of_study"] = m.group(1).strip(" ,")[:120]
    m = re.search(r"\b(\d)\s*(?:days?)\s*(?:a\s+week\s+)?(?:in|from|at)\s+(?:the\s+)?office\b|\b(\d)\s*days?\s*(?:wfo|work from office)\b", low)
    if m:
        out["office_days"] = int(m.group(1) or m.group(2))
    out["shift"] = "Night" if re.search(r"\bnight shifts?\b", low) else "Rotational" if re.search(r"\brotational shifts?\b", low) else "Flexible" if re.search(r"\bflexible (?:hours|timings|shift)\b", low) else "Day" if re.search(r"\bday shift\b", low) else ""
    out["travel"] = "Frequent (25-50%)" if re.search(r"\bfrequent travel|travel (?:up to )?(?:40|50)%", low) else "Occasional (under 25%)" if re.search(r"\boccasional travel|travel (?:up to )?(?:10|20|25)%|willing(?:ness)? to travel", low) else ""
    if re.search(r"\bimmediate joiners?\b", low):
        out["max_notice_days"] = 0
    m = re.search(r"notice period\s*(?:of\s*)?(?:up to|upto|max(?:imum)?|less than|within|<=?)?\s*(\d{1,3})\s*(days?|months?)", low)
    if m:
        out["max_notice_days"] = int(m.group(1)) * (30 if m.group(2).startswith("month") else 1)
    langs = [L for L in ("English", "Hindi", "Bengali", "Marathi", "Telugu", "Tamil", "Gujarati", "Urdu", "Kannada", "Odia", "Malayalam", "Punjabi", "Assamese",
                         "French", "German", "Spanish", "Japanese", "Arabic", "Mandarin")
             if re.search(rf"\b{L}\b[^.\n]{{0,40}}\b(?:speak|spoken|written|fluency|fluent|proficien|communication|language)|"
                          rf"\b(?:fluent|proficient|fluency|communication|speak|spoken|written|verbal)\w*\b[^.\n]{{0,40}}\b{L}\b", text, re.I)]
    if langs:
        out["languages"] = langs
    certs = [c.group(0).strip() for c in re.finditer(r"\b(?:AWS|Azure|GCP|Google Cloud|Microsoft|PMP|CSM|CISSP|CISA|CISM|CCNA|CCNP|ITIL|Six Sigma|Scrum|Salesforce|CFA|CPA|CKA|CKAD|RHCE|"
                                                   r"Prince2|TOGAF|Oracle|SAP)(?:[ -](?:[A-Z][A-Za-z()]*|\d+))*", text)
             if re.search(r"certif|associate|professional|practitioner|administrator|architect|belt|master|\b(?:PMP|CSM|CISSP|CISA|CISM|CCNA|CCNP|CKA|CKAD|RHCE)\b", c.group(0), re.I)]
    if certs:
        out["certifications"] = list(dict.fromkeys(certs))[:8]
    blines = secs.get("benefits", [])
    has_bullets = any(_BULLET.match(ln) for ln in blines)
    ben = [_BULLET.sub("", ln).strip() for ln in blines if (_BULLET.match(ln) if has_bullets else ":" not in ln) and 3 <= len(_BULLET.sub("", ln).strip()) <= 120]
    if ben:
        out["benefits"] = [b[:80] for b in ben][:15]
    m = re.search(r"\b(?i:reports?|reporting)\s+(?i:in)?to\s*[:\-]?\s*(?:the\s+)?([A-Z][A-Za-z ,&/-]{2,60}?)(?:[.;\n]|$)", text)
    if m:
        out["reports_to"] = m.group(1).strip(" ,")
    m = re.search(r"\b(?:industry|domain)\s*(?:experience)?\s*[:\-]\s*([^\n.]{3,80})|\bexperience in (?:the\s+)?([a-z][a-z &/-]{3,40})\s+(?:industry|domain|sector)\b", text, re.I)
    if m:
        out["industry_experience"] = (m.group(1) or m.group(2)).strip()[:120]
    about = [ln for ln in secs.get("about", []) if len(ln.split()) >= 6]
    if about and re.search(r"\b(?:we are|founded|our company|is a|leading)\b", " ".join(about), re.I):
        out["about_company"] = " ".join(about)[:1500]
    m = re.search(r"\b(?:timezone|time zone|working hours)\s*[:\-]\s*([^\n]{3,80})|\b((?:ist|est|pst|gmt|cet|uk|us)\s+(?:hours|time ?zone|overlap)[^\n.]{0,40})", text, re.I)
    if m:
        out["timezone"] = (m.group(1) or m.group(2)).strip()[:120]
    return {k: v for k, v in out.items() if v not in ("", [], None)}


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
    spoken = {"English", "Hindi", "Gujarati", "Marathi", "Tamil", "Telugu", "Kannada", "Bengali", "Malayalam", "Arabic", "French", "German", "Spanish"}
    must = [s for s in must if s not in soft_names and s not in spoken]
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
    extra = _more(text, secs)
    fields = {**extra, "title": _title(lines), "summary": about[:900], "responsibilities": _bullets(body("responsibilities"))[:10],
              "must_have_skills": must[:15], "nice_to_have_skills": nice[:15], "soft_skills": list(dict.fromkeys(soft))[:12], "tools": found_all[:20],
              "employment_type": emp, "workplace_type": work}
    if lo is not None:
        fields["experience_min"] = lo
    if hi is not None:
        fields["experience_max"] = hi
    cities = list(dict.fromkeys(m.group(1) for m in _CITY.finditer(text)))
    if cities:
        fields["locations"] = cities[:3]
    KEEP = ("must_have_skills", "nice_to_have_skills", "responsibilities", "tools")      # callers expect these lists, even empty
    return jd_schema.clean({k: v for k, v in fields.items() if k in KEEP or v not in ("", [], None)})
