"""Free resume parsing (no AI): text extraction plus regex/dictionary extraction of the fields matching needs."""
import io
import logging
import re
import time
from datetime import date

from . import skills

log = logging.getLogger("resumes")

MAX_RESUME_BYTES = 10 * 1024 * 1024
RESUME_TYPES = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ".txt": "text/plain", ".md": "text/plain", ".rtf": "application/rtf",
                ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<![\w/.])(?:\+?\d{1,3}[ \t.-]?)?(?:\(?\d{2,5}\)?[ \t.-]?)?\d{3,5}[ \t.-]?\d{4,6}(?![\w/])")   # one line only
URL = re.compile(r"(?:https?://|www\.)[^\s<>\"'|,;()]+|\b(?:[a-z0-9-]+\.)*(?:linkedin\.com/in|github\.com|gitlab\.com|behance\.net|dribbble\.com|medium\.com)/[^\s<>\"'|,;()]+|"
                 r"\b[a-z0-9-]+\.(?:github\.io|vercel\.app|netlify\.app|wixsite\.com|carrd\.co|framer\.website)\b[^\s<>\"'|,;()]*", re.I)
LINK = URL
YEARS = re.compile(r"(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?)(?:\s+of)?(?:\s+\w+){0,3}?\s+(?:experience|exp)\b", re.I)
YEARS_LABEL = re.compile(r"(?:total\s+|overall\s+)?(?:work\s+)?experience\s*[:\-–]\s*(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?)", re.I)
YEARS_SIMPLE = re.compile(r"\b(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?)\b", re.I)
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
RANGE = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*(\d{4})\s*[-–—to]+\s*(present|current|now|till date|"
                   r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*\d{4})", re.I)
NOTICE = re.compile(r"notice\s*(?:period)?\s*[:\-]?\s*(?:of\s*)?(\d{1,3})\s*(days?|months?|weeks?)", re.I)
CITIES = ["Bengaluru", "Bangalore", "Mumbai", "Navi Mumbai", "Thane", "Pune", "Hyderabad", "Secunderabad", "Chennai", "Kolkata", "New Delhi", "Delhi",
          "Noida", "Greater Noida", "Gurugram", "Gurgaon", "Ghaziabad", "Faridabad", "Ahmedabad", "Surat", "Vadodara", "Baroda", "Rajkot", "Bhavnagar",
          "Jamnagar", "Junagadh", "Gandhinagar", "Anand", "Nadiad", "Bharuch", "Ankleshwar", "Vapi", "Valsad", "Navsari", "Mehsana", "Morbi",
          "Gandhidham", "Bhuj", "Porbandar", "Amreli", "Botad", "Surendranagar", "Palanpur", "Himmatnagar", "Godhra", "Dahod", "Patan", "Veraval",
          "Jaipur", "Jodhpur", "Udaipur", "Kota", "Ajmer", "Bikaner", "Alwar", "Bhilwara", "Sikar", "Lucknow", "Kanpur", "Agra", "Varanasi",
          "Prayagraj", "Allahabad", "Meerut", "Bareilly", "Aligarh", "Moradabad", "Gorakhpur", "Jhansi", "Mathura", "Saharanpur", "Indore", "Bhopal",
          "Gwalior", "Jabalpur", "Ujjain", "Sagar", "Raipur", "Bhilai", "Bilaspur", "Nagpur", "Nashik", "Aurangabad", "Chhatrapati Sambhajinagar",
          "Solapur", "Kolhapur", "Amravati", "Sangli", "Satara", "Jalgaon", "Akola", "Latur", "Nanded", "Ahmednagar", "Kalyan", "Vasai", "Virar",
          "Panvel", "Pimpri-Chinchwad", "Pimpri Chinchwad", "Chandigarh", "Mohali", "Panchkula", "Zirakpur", "Ludhiana", "Amritsar", "Jalandhar",
          "Patiala", "Bathinda", "Ambala", "Karnal", "Panipat", "Sonipat", "Rohtak", "Hisar", "Kurukshetra", "Shimla", "Dharamshala", "Solan",
          "Jammu", "Srinagar", "Dehradun", "Haridwar", "Roorkee", "Rishikesh", "Haldwani", "Kochi", "Cochin", "Ernakulam", "Thiruvananthapuram",
          "Trivandrum", "Kozhikode", "Calicut", "Thrissur", "Kollam", "Kannur", "Palakkad", "Kottayam", "Coimbatore", "Madurai", "Tiruchirappalli",
          "Trichy", "Salem", "Tirunelveli", "Erode", "Vellore", "Tiruppur", "Thoothukudi", "Hosur", "Pondicherry", "Puducherry", "Mysuru", "Mysore",
          "Mangaluru", "Mangalore", "Hubli", "Hubballi", "Dharwad", "Belgaum", "Belagavi", "Davangere", "Ballari", "Shivamogga", "Tumakuru",
          "Udupi", "Manipal", "Visakhapatnam", "Vizag", "Vijayawada", "Guntur", "Nellore", "Tirupati", "Kakinada", "Rajahmundry", "Kurnool",
          "Anantapur", "Warangal", "Karimnagar", "Nizamabad", "Khammam", "Bhubaneswar", "Cuttack", "Rourkela", "Sambalpur", "Puri", "Berhampur",
          "Patna", "Gaya", "Muzaffarpur", "Bhagalpur", "Darbhanga", "Ranchi", "Jamshedpur", "Dhanbad", "Bokaro", "Hazaribagh", "Howrah", "Durgapur",
          "Asansol", "Siliguri", "Kharagpur", "Guwahati", "Silchar", "Dibrugarh", "Jorhat", "Shillong", "Imphal", "Agartala", "Aizawl", "Kohima",
          "Gangtok", "Itanagar", "Goa", "Panaji", "Margao", "Vasco da Gama", "Remote", "Dubai", "Abu Dhabi", "Sharjah", "Doha", "Riyadh", "Muscat",
          "Kuwait", "Singapore", "Kuala Lumpur", "London", "Manchester", "Dublin", "New York", "San Francisco", "San Jose", "Seattle", "Austin",
          "Boston", "Chicago", "Dallas", "Toronto", "Vancouver", "Sydney", "Melbourne", "Berlin", "Munich", "Amsterdam", "Paris"]
CITY = re.compile(r"\b(" + "|".join(re.escape(c) for c in sorted(CITIES, key=len, reverse=True)) + r")\b", re.I)
CTC = re.compile(r"(?:current|expected)\s*(?:ctc|salary|package)\s*[:\-]?\s*(?:inr|rs\.?|₹)?\s*([\d.,]+)\s*(lpa|lakhs?|l|k|cr)?", re.I)


def extract_text(raw: bytes, filename: str) -> str:
    name = (filename or "").lower()
    if name.endswith(".pdf") or raw[:4] == b"%PDF":
        from pypdf import PdfReader
        flat = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(raw)).pages)
        try:
            ordered = pdf_text(raw)
        except Exception as e:                                # a PDF pdfplumber cannot read: the plain reading still works
            log.warning("column-aware PDF reading failed, using the plain reading: %s", e)
            return flat
        return ordered if len(re.sub(r"\s", "", ordered)) >= 0.8 * len(re.sub(r"\s", "", flat)) else flat
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


# --- PDF text in reading order ---------------------------------------------------------------------------------------------
# pypdf returns text in the order it was drawn. Resume builders (Canva, Word templates) draw two-column layouts in any order,
# so the name could land on line 45 and the email next to a reference's phone. Here words are placed by their position on the
# page: visual lines, then the gutter between columns, then each column top to bottom (a full-width line such as a centred
# header splits the page into bands, read in order).
def pdf_text(raw: bytes) -> str:
    import pdfplumber
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    pages = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages[:12]:
            words = page.extract_words(x_tolerance=1.5, y_tolerance=2.5, extra_attrs=["size"])
            if words:
                pages.append("\n".join(_emit(_rows(words), 0)))
    return "\n\n".join(pages)


def _join(ws: list[dict]) -> str:
    """Words of one chunk. Letter-spaced headings ("S K I L L S") come back one letter per word: the wider gaps are the spaces."""
    if len(ws) > 3 and sum(len(w["text"]) == 1 for w in ws) >= 0.7 * len(ws):
        gaps = sorted(b["x0"] - a["x1"] for a, b in zip(ws, ws[1:]))
        cut = gaps[len(gaps) // 2] * 1.8 + 0.5
        out = ws[0]["text"]
        for a, b in zip(ws, ws[1:]):
            out += (" " if b["x0"] - a["x1"] > cut else "") + b["text"]
        return out
    return " ".join(w["text"] for w in ws)


def _rows(words: list[dict]) -> list[list[dict]]:
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        tol = max(2.0, 0.45 * float(w.get("size") or 10))
        for ln in lines[-4:]:
            if abs(ln[0]["top"] - w["top"]) <= tol:
                ln.append(w)
                break
        else:
            lines.append([w])
    rows = []
    for ln in sorted(lines, key=lambda l: min(w["top"] for w in l)):
        ln.sort(key=lambda w: w["x0"])
        chunks, cur = [], [ln[0]]
        for a, b in zip(ln, ln[1:]):
            if b["x0"] - a["x1"] > max(12.0, 1.6 * float(a.get("size") or 10)):
                chunks.append(cur)
                cur = []
            cur.append(b)
        chunks.append(cur)
        rows.append([{"x0": c[0]["x0"], "x1": max(w["x1"] for w in c), "text": _join(c)} for c in chunks])
    return rows


def _line(r: list[dict]) -> str:
    """One visual line. A wide gap (side-by-side items, not a justified line) becomes 3 spaces, which the readers treat as a break."""
    out = r[0]["text"]
    for a, b in zip(r, r[1:]):
        out += ("   " if b["x0"] - a["x1"] > 30 else " ") + b["text"]
    return out


def _gutter(chunks: list[dict]) -> float | None:
    if len(chunks) < 8:
        return None
    lo, hi = min(c["x0"] for c in chunks), max(c["x1"] for c in chunks)
    best, best_x, x = None, None, lo + (hi - lo) * 0.15
    while x < lo + (hi - lo) * 0.85:
        cover = sum(1 for c in chunks if c["x0"] < x < c["x1"])
        if (sum(1 for c in chunks if c["x1"] <= x) >= 4 and sum(1 for c in chunks if c["x0"] >= x) >= 4
                and (best is None or cover < best)):
            best, best_x = cover, x
        x += 3
    return best_x if best is not None and best <= max(2, 0.12 * len(chunks)) else None


def _emit(rows: list[list[dict]], depth: int) -> list[str]:
    g = _gutter([c for r in rows for c in r]) if depth < 2 else None
    if g is None:
        return [_line(r) for r in rows]
    out: list[str] = []
    left: list[list[dict]] = []
    right: list[list[dict]] = []
    for r in rows + [None]:
        if r is None or any(c["x0"] < g < c["x1"] for c in r):
            out += _emit(left, depth + 1) + _emit(right, depth + 1)
            left, right = [], []
            if r is not None:
                out.append(_line(r))
            continue
        if (lc := [c for c in r if c["x1"] <= g]):
            left.append(lc)
        if (rc := [c for c in r if c["x0"] >= g]):
            right.append(rc)
    return out


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


# --- names ------------------------------------------------------------------------------------------------------------
_LABEL = re.compile(r"^\s*(?:(?:candidate|applicant|employee)\s+)?(?:full\s+|first\s+|last\s+)?name\s*(?:of\s+(?:the\s+)?(?:candidate|applicant))?\s*[:\-–—=|]\s*", re.I)
_DOC_WORDS = re.compile(r"^\s*(?:(?:resume|résumé|curriculum\s+vitae|cv|profile|bio-?data|biodata)(?:\s+(?:of|for))?\s*[:\-–—|]?\s*)+", re.I)
_HONORIFIC = re.compile(r"^\s*(?:mr|mrs|ms|miss|dr|prof|shri|smt|sri|kumari)\b\.?\s+", re.I)
_CREDENTIALS = re.compile(r"[,\s]+(?:mba|pmp|ca|cs|cfa|frm|phd|ph\.d|m\.?tech|b\.?tech|b\.?e|m\.?e|b\.?sc|m\.?sc|bca|mca|b\.?com|m\.?com|"
                          r"cissp|cism|aws|csm|six sigma|pgdm|llb|md)\.?\s*$", re.I)
_NOT_A_NAME = {"resume", "résumé", "curriculum", "vitae", "cv", "profile", "summary", "objective", "contact", "details", "personal", "information",
               "experience", "education", "skills", "projects", "references", "declaration", "page", "career", "about", "me", "name", "email", "phone",
               "mobile", "address", "linkedin", "github", "portfolio", "engineer", "developer", "manager", "analyst", "executive", "consultant",
               "designer", "architect", "intern", "lead", "senior", "junior", "associate", "specialist", "administrator", "officer", "director",
               "recruiter", "sales", "software", "data", "business", "customer", "support", "product", "project", "marketing", "operations", "hr",
               "technical", "professional", "fresher", "student", "graduate", "present", "confidential", "private", "limited", "ltd", "pvt", "inc",
               "technologies", "solutions", "services", "university", "college", "institute", "school", "bachelor", "master", "degree", "certificate"}


def clean_name(raw: str) -> str:
    """A person's name from a header line or a form value: "Name: Priya Sharma", "RESUME OF PRIYA SHARMA", "Dr. Priya Sharma, MBA |
    Pune" and "priya.sharma" all give "Priya Sharma". Empty when the text is not a plausible name."""
    s = re.sub(r"\s+", " ", str(raw or "")).strip()
    for _ in range(3):                                     # labels can stack: "Resume - Name: ..."
        n = _DOC_WORDS.sub("", _LABEL.sub("", s)).strip()
        if n == s:
            break
        s = n
    s = _HONORIFIC.sub("", s)
    s = re.split(r"\s[|•·/–—-]\s|\s{2,}|[|•·@()\[\]:;\d]|,\s*(?=[a-z.]*\s*$)", s)[0].strip(" ,.-")
    s = _CREDENTIALS.sub("", s).strip(" ,.-")
    words = s.split()
    if not 1 <= len(words) <= 5 or len(s) > 60:
        return ""
    if any(not re.fullmatch(r"[^\W\d_](?:[^\W\d_]|['.\u2019-])*", w) for w in words):
        return ""
    if any(w.lower().strip(".") in _NOT_A_NAME for w in words) or (len(words) == 1 and len(words[0]) < 3):
        return ""
    if s.isupper() or s.islower():
        s = " ".join(w if len(w) <= 2 and w.endswith(".") else w[:1].upper() + w[1:].lower() for w in words)
        s = re.sub(r"\b(Mc|Mac|O')([a-z])", lambda m: m.group(1) + m.group(2).upper(), s)
    return s


def safe_name(raw: str) -> str:
    """clean_name, but a name it cannot judge (one unusual word, an initial) is kept with only its label removed."""
    n = clean_name(raw)
    if n:
        return n
    s = _LABEL.sub("", re.sub(r"\s+", " ", str(raw or "")).strip()).strip()
    return "" if not s or len(s) > 80 or re.search(r"[\d@:/]", s) else s


def _guess_name(text: str, email: str) -> str:
    lines = [ln.strip() for ln in _without_references(text or "").splitlines() if ln.strip()]
    for ln in lines[:25]:                                  # an explicit "Name: ..." line wins over any guess
        m = _LABEL.match(ln)
        if m and (n := clean_name(ln)):
            return n
    whole = re.sub(r"[^a-z]", "", email.split("@")[0].lower()) if email else ""
    local = [p.lower() for p in re.split(r"[._\d\-+]+", email.split("@")[0]) if len(p) > 1] if email else []
    if len(whole) >= 4:                                    # a line whose every word is in the email address ("chauhanmittal2810" -> "Mittal Chauhan")
        for ln in lines[:60]:
            for part in re.split(r"\s{3,}", ln):
                n = clean_name(part)
                toks = [t.lower() for t in re.split(r"[\s.'-]+", n) if len(t) > 1]
                if len(toks) >= 2 and all(t in whole for t in toks):
                    return n
    found = []
    for ln in lines[:10]:
        if EMAIL.search(ln) and len(ln) > 60:
            continue
        n = clean_name(re.split(r"\s{3,}", ln)[0])
        if n and len(n.split()) >= 2:
            found.append(n)
        if len(found) == 3:
            break
    if found:                                              # prefer the line that agrees with the email address
        for n in found:
            if any(tok in n.lower() for tok in local) or any(len(t) > 2 and t in whole for t in n.lower().split()):
                return n
        return found[0]
    if local:
        return " ".join(p.capitalize() for p in local)[:60]
    return ""


# --- text clean-up the readers rely on ------------------------------------------------------------------------------------
_TLD = r"(?:com|in|org|net|co|edu|ac|io|ai|me|info|biz|gov|us|uk|dev|tech|app|xyz|online|live|outlook|yahoo)"
_SPACED_EMAIL = re.compile(rf"[\w.+-]+\s*(?:@|\[at\]|\(at\))\s*[\w-]+(?:\s*\.\s*[\w-]+)*?\s*\.\s*{_TLD}\b(?:\s*\.\s*(?:in|uk|au|sg))?", re.I)
_URL_TAIL = re.compile(r"^/?[\w.~%-]+(?:/[\w.~%-]*)*/?$")


def tidy(text: str) -> str:
    """Repairs what PDF builders break: "name@gmail. com" (a space inside the address), a link wrapped onto the next line
    ("https://x.github.io/" + "portfolio/"), and a heading wrapped after "&" ("TOOLS &" + "LANGUAGES")."""
    t = text or ""
    t = _SPACED_EMAIL.sub(lambda m: re.sub(r"\s+", "", re.sub(r"\s*(?:\[at\]|\(at\))\s*", "@", m.group(0), flags=re.I)), t)
    lines = t.split("\n")
    out: list[str] = []
    for ln in lines:
        prev = out[-1].rstrip() if out else ""
        last = prev.split()[-1] if prev.split() else ""
        nxt = ln.strip()
        if last and URL.fullmatch(last) and nxt and " " not in nxt and "/" in nxt and _URL_TAIL.match(nxt) and len(nxt) < 80:
            out[-1] = prev + (nxt if last.endswith("/") or nxt.startswith("/") else "/" + nxt)
            continue
        if re.fullmatch(r"[A-Z][A-Z ]{1,30}\s*(?:&|AND)", prev) and re.fullmatch(r"[A-Z][A-Z ]{1,30}", nxt):
            out[-1] = prev + " " + nxt
            continue
        out.append(ln)
    return "\n".join(out)


_REF_HEAD = re.compile(r"^\s*(?:professional\s+)?references?(?:\s+details)?\s*[:\-–]?\s*$", re.I)


def _references_block(text: str) -> tuple[int, int]:
    """Start and end (line numbers) of the References section: its phones, emails and names are other people's."""
    lines = (text or "").splitlines()
    for i, ln in enumerate(lines):
        if _REF_HEAD.match(ln):
            for j in range(i + 1, len(lines)):
                s = lines[j].strip()
                if s and s.isupper() and len(s) < 40 and (_ANY_HEAD.match(s) or _WORK_HEAD.match(s) or _EDU_HEAD.match(s)) and not _REF_HEAD.match(s):
                    return i, j
            return i, len(lines)
    return -1, -1


def _without_references(text: str) -> str:
    a, b = _references_block(text)
    if a < 0:
        return text or ""
    lines = (text or "").splitlines()
    return "\n".join(lines[:a] + lines[b:])


def references(text: str) -> list[str]:
    """The referees as written (name, role, phone), one entry per person where the layout allows."""
    a, b = _references_block(text)
    if a < 0:
        return []
    rows = [ln.strip() for ln in (text or "").splitlines()[a + 1:b] if ln.strip() and not re.match(r"^(?:available\s+on\s+request|on\s+request)\.?$", ln.strip(), re.I)]
    cols = [re.split(r"\s{3,}", r) for r in rows]
    width = max((len(c) for c in cols), default=0)
    if width > 1 and sum(len(c) == width for c in cols) >= len(cols) * 0.6:     # referees side by side
        return [", ".join(c[k].strip() for c in cols if k < len(c) and c[k].strip())[:200] for k in range(width)][:4]
    people, cur = [], []
    for r in rows:
        if cur and clean_name(r) and len(clean_name(r).split()) >= 2:
            people.append(", ".join(cur))
            cur = []
        cur.append(r)
    if cur:
        people.append(", ".join(cur))
    return [x[:200] for x in people][:4]


_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
              "twelve": 12, "fifteen": 15, "eighteen": 18, "twenty": 20}
_DURATION = re.compile(r"\b(\d{1,2}(?:\.\d)?|" + "|".join(_NUM_WORDS) + r")\s*\+?\s*(months?|years?|yrs?)\b(?:\s+of)?(?:\s+[\w-]+){0,3}?\s+"
                       r"(?:experience|exp|internship)\b", re.I)
_INTERN_AT = re.compile(r"\b(?:internship|interned|intern)\s+(?:at|with)\s+([A-Z][\w&.'-]*(?:\s+[A-Z][\w&.'-]*){0,4})", re.M)


def _stated_years(t: str) -> list[float]:
    """Experience written as a number: "3+ years of experience", "Experience: 4 years", "two months experience" (in years)."""
    out = [float(x) for x in YEARS.findall(t) + YEARS_LABEL.findall(t)]
    for m in _DURATION.finditer(t):
        n = float(_NUM_WORDS.get(m.group(1).lower(), 0) or (m.group(1) if m.group(1)[0].isdigit() else 0))
        if m.group(2).lower().startswith("month"):
            out.append(round(n / 12, 1) or 0.1)
        else:
            out.append(n)
    return [x for x in out if 0 < x < 45]


def _location(t: str) -> tuple[str, str]:
    """(city, how it was found): a labelled address or location line, else the contact block at the top, else the city the
    resume mentions most (where the person studied or worked: a likely current city, marked as inferred)."""
    known = lambda s: next((c for c in CITIES if (m := CITY.search(s or "")) and c.lower() == m.group(1).lower()), "")
    for ln in t.splitlines()[:80]:
        m = re.match(r"^\s*(?:current\s+)?(?:address|location|city|residence|based\s+in|lives?\s+in|hometown|place)\s*[:\-–]\s*(.+)$", ln, re.I)
        if m:
            v = re.split(r"\s{3,}", m.group(1))[0].strip(" .,")
            if (c := known(v)):
                return c, "stated"
            parts = [x.strip(" .") for x in re.split(r",", v) if x.strip(" .") and not re.search(r"\d", x)]
            if parts and 2 < len(parts[-1 if len(parts) < 3 else -2]) < 40:
                return parts[-1 if len(parts) < 3 else -2], "stated"
    head = "\n".join([ln for ln in t.splitlines() if ln.strip()][:8])
    if (c := known(head)) and c != "Remote":
        return c, "stated"
    counts: dict[str, int] = {}
    for m in CITY.finditer(t):
        c = next((x for x in CITIES if x.lower() == m.group(1).lower()), "")
        if c and c != "Remote":
            counts[c] = counts.get(c, 0) + 1
    if counts:
        return max(counts, key=lambda c: counts[c]), "inferred"
    return "", ""


def parse(text: str) -> dict:
    t = tidy(text or "")
    own = _without_references(t)                          # the referees' phones, emails and names are not the candidate's
    emails = list(dict.fromkeys(e.lower().strip(".") for e in EMAIL.findall(own)))[:3]
    phones, seen = [], set()
    for p in PHONE.findall(own):
        digits = re.sub(r"\D", "", p)
        if 10 <= len(digits) <= 13 and digits not in seen and not re.fullmatch(r"(?:19|20)\d{2}(?:19|20)\d{2}\d*", digits):
            seen.add(digits)
            phones.append(re.sub(r"\s+", " ", p.strip()))
    stated = _stated_years(t)
    hist = history(t)
    ranged = hist["years"] if hist["years"] is not None else _years_from_ranges(t)
    years = max(stated) if stated else ranged
    notice = None
    nm = NOTICE.search(t)
    if nm:
        n, unit = int(nm.group(1)), nm.group(2).lower()
        notice = n * 30 if unit.startswith("month") else n * 7 if unit.startswith("week") else n
    location, location_source = _location(own)
    return {
        "emails": emails, "location": location, "location_source": location_source, "phones": phones[:2],
        "links": list(dict.fromkeys(u.rstrip(".") for u in URL.findall(own)))[:8], "references": references(t),
        "skills": skills.extract_all(t) + [x for x in skills.infer_soft(t) if x not in skills.extract_all(t)], "years": years,
        "years_from_dates": ranged, "jobs": hist["jobs"], "gaps": hist["gaps"], "skill_years": hist["skill_years"], "years_source": "stated" if stated else ("dates" if ranged else None),
        "notice_days": notice, "name_guess": _guess_name(t, emails[0] if emails else ""), "chars": len(t), "parsed_at": time.time(),
        **details(own),
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


def tenures(text: str, profile: dict | None = None) -> list[dict]:
    """Jobs with start/end dates, newest first: from the structured profile when present, else date ranges in the text."""
    out = []
    today = date.today()

    def parse_d(v: str):
        v = (v or "").strip().lower()
        if not v or v.startswith(("present", "current", "now", "till")):
            return today
        m = re.match(r"([a-z]{3})[a-z]*\.?\s*(\d{4})", v)
        if m and m.group(1) in MONTHS:
            return date(int(m.group(2)), MONTHS[m.group(1)], 1)
        m = re.match(r"(\d{1,2})[/-](\d{4})", v)
        if m:
            return date(int(m.group(2)), max(1, min(12, int(m.group(1)))), 1)
        m = re.match(r"(\d{4})", v)
        return date(int(m.group(1)), 1, 1) if m else None

    for e in (profile or {}).get("experience") or []:
        if not isinstance(e, dict):
            continue
        a, b = parse_d(e.get("start", "")), parse_d(e.get("end", "") or "present")
        if a and b and a <= b:
            out.append({"title": e.get("title", ""), "company": e.get("company", ""), "start": a, "end": b})
    if not out:
        for m in RANGE.finditer(text or ""):
            try:
                a = date(int(m.group(2)), MONTHS[m.group(1)[:3].lower()], 1)
                b = parse_d(m.group(3))
                if b and 1970 < a.year <= today.year and a <= b:
                    out.append({"title": "", "company": "", "start": a, "end": b})
            except (KeyError, ValueError):
                continue
    out.sort(key=lambda x: x["start"], reverse=True)
    return out


def stability(text: str, profile: dict | None = None) -> dict:
    """Job-stability indicator from tenure history: average tenure, short stints, moves in the last 3 years."""
    jobs = tenures(text, profile)
    if len(jobs) < 2:
        return {"level": "unknown", "label": "Not enough history", "jobs": len(jobs), "avg_months": None, "short_stints": 0, "moves_3y": 0}
    months = [max(1, (j["end"].year - j["start"].year) * 12 + j["end"].month - j["start"].month) for j in jobs]
    past = months[1:] if len(months) > 1 else months        # the current job is still running
    avg = sum(past) / len(past)
    short = sum(1 for m in past if m < 12)
    cutoff = date.today().replace(year=date.today().year - 3)
    moves = sum(1 for j in jobs[1:] if j["end"] >= cutoff)
    if short >= 3 or (avg < 14 and len(past) >= 2):
        level, label = "low", "Frequent job changes"
    elif short >= 1 or avg < 24:
        level, label = "medium", "Some short stints"
    else:
        level, label = "high", "Stable"
    return {"level": level, "label": label, "jobs": len(jobs), "avg_months": round(avg, 1), "short_stints": short, "moves_3y": moves,
            "history": [{"title": j["title"], "company": j["company"], "start": j["start"].isoformat()[:7],
                         "end": "present" if j["end"] >= date.today().replace(day=1) else j["end"].isoformat()[:7], "months": m}
                        for j, m in zip(jobs, months)][:8]}


# --- work history: total experience, gaps and years per skill, worked out from the dates in the resume ---------------------------
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE = rf"(?:{_MON}\s*['’]?\s*(\d{{4}}|\d{{2}})|(\d{{1,2}})\s*[/.-]\s*(\d{{4}})|(\d{{4}})\s*[/.-]\s*(\d{{1,2}})(?!\d)|((?:19|20)\d{{2}}))"
_END = r"(present|current(?:ly)?|now|till\s*date|to\s*date|ongoing|today)"
SPAN = re.compile(rf"{_DATE}\s*(?:-|–|—|to|till|until)\s*(?:{_DATE}|{_END})", re.I)
_EDU_HEAD = re.compile(r"^\s*(?:education(?:al)?(?:\s+(?:details|qualifications?|background))?|academic(?:s| details| qualifications?| background)?|qualifications?|"
                       r"certifications?|courses|training)\s*[:\-–]?\s*$", re.I)
_WORK_HEAD = re.compile(r"^\s*(?:(?:work|professional|employment|career|relevant|internship)\s+)?(?:experience|history|employment|internships?)(?:\s+details)?\s*[:\-–]?\s*$|"
                        r"^\s*(?:projects?|skills?|technical skills|summary|profile|achievements|awards)\s*[:\-–]?\s*$", re.I)
_EDU_WORDS = re.compile(r"\b(?:b\.?\s?tech|b\.?e\b|m\.?\s?tech|bachelor|master|mba|bca|mca|b\.?sc|m\.?sc|b\.?com|m\.?com|ph\.?d|diploma|hsc|ssc|"
                        r"class\s*(?:x|xii|10|12)|cbse|icse|university|college|school|institute|cgpa|gpa|percentage)\b", re.I)


def _ym(groups: tuple, today: date) -> date | None:
    mon, y2, m1, y1, y3, m3, yonly = groups
    try:
        if mon:
            y = int(y2) + (2000 if len(y2) == 2 and int(y2) < 50 else 1900 if len(y2) == 2 else 0)
            return date(y, MONTHS[mon[:3].lower()], 1)
        if m1:
            return date(int(y1), max(1, min(12, int(m1))), 1)
        if y3:
            return date(int(y3), max(1, min(12, int(m3))), 1)
        if yonly:
            return date(int(yonly), 1, 1)
    except (ValueError, KeyError):
        return None
    return None


def _months(a: date, b: date) -> int:
    return max(0, (b.year - a.year) * 12 + b.month - a.month)


def history(text: str) -> dict:
    """Jobs found from date ranges outside the education section, with total experience (overlaps merged), gaps of 3+ months
    between jobs or since the last job, and the years each skill was used (the jobs whose description mentions it)."""
    from . import skills as sk
    today = date.today()
    lines = (text or "").splitlines()
    in_edu, spans = False, []
    for i, ln in enumerate(lines):
        if _EDU_HEAD.match(ln):
            in_edu = True
            continue
        if _WORK_HEAD.match(ln):
            in_edu = False
            continue
        for m in SPAN.finditer(ln):
            g = m.groups()
            a = _ym(g[0:7], today)
            b = today if g[14] else _ym(g[7:14], today)
            if not a or not b or a > b or a.year < 1970 or (not g[14] and b > today):
                continue
            ctx = " ".join(lines[max(0, i - 1):i + 2])
            year_only = bool(g[6]) and not g[14] and bool(g[13])
            if in_edu or (_EDU_WORDS.search(ctx) and (year_only or _months(a, b) in (24, 36, 48, 60))):
                continue                                        # a degree, not a job
            spans.append({"start": a, "end": min(b, today), "line": i, "current": bool(g[14])})
    spans.sort(key=lambda s: s["line"])
    # each job's description runs from its date line to the next job's date line
    for k, s in enumerate(spans):
        nxt = spans[k + 1]["line"] if k + 1 < len(spans) else min(len(lines), s["line"] + 25)
        prev = spans[k - 1]["line"] + 1 if k else 0
        bullet = re.compile(r"^\s*[-•*▪●◦]")
        above = [x for x in lines[max(prev, s["line"] - 2):s["line"]] if x.strip() and not bullet.match(x) and len(x.strip()) < 80
                 and not _WORK_HEAD.match(x) and not _EDU_HEAD.match(x)]
        if k:   # lines just after the previous job's dates belong to that job unless they look like a title
            above = above[-2:]
        body = lines[s["line"]:nxt]
        if len(body) > 1 and k + 1 < len(spans):
            for _ in range(2):                                  # the next job's title lines (at most two) sit just above its dates
                if len(body) > 2 and body[-1].strip() and len(body[-1].strip()) < 60 and not bullet.match(body[-1]):
                    body = body[:-1]
        s["text"] = "\n".join(above + body)
        own = re.sub(SPAN, "", lines[s["line"]]).strip(" |•-–,()")
        s["title"] = own if len(own) > 2 else " | ".join(x.strip(" |•-–,") for x in above)
    jobs = sorted(spans, key=lambda s: s["start"])
    total, gaps, merged = 0, [], []
    for s in jobs:
        if merged and s["start"] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], s["end"])
        else:
            merged.append([s["start"], s["end"]])
    for a, b in merged:
        total += _months(a, b)
    for (a1, b1), (a2, b2) in zip(merged, merged[1:]):
        if _months(b1, a2) >= 3:
            gaps.append({"from": b1.isoformat()[:7], "to": a2.isoformat()[:7], "months": _months(b1, a2), "kind": "between jobs"})
    if merged and not any(s["current"] for s in jobs) and _months(merged[-1][1], today) >= 3:
        gaps.append({"from": merged[-1][1].isoformat()[:7], "to": "now", "months": _months(merged[-1][1], today), "kind": "since last job"})
    skill_months: dict[str, int] = {}
    for s in jobs:
        for name in set(sk.extract_all(s["text"])) | set(sk.infer_soft(s["text"])):
            skill_months[name] = skill_months.get(name, 0) + _months(s["start"], s["end"])
    return {
        "years": round(total / 12, 1) if jobs else None,
        "jobs": [{"title": s["title"][:120], "start": s["start"].isoformat()[:7], "end": "present" if s["current"] else s["end"].isoformat()[:7],
                  "months": _months(s["start"], s["end"])} for s in sorted(jobs, key=lambda s: s["start"], reverse=True)][:15],
        "gaps": gaps,
        "skill_years": {k: round(v / 12, 1) for k, v in sorted(skill_months.items(), key=lambda kv: -kv[1]) if v >= 3},
    }


# --- everything else a resume says: the fields of the application form and the candidate profile -------------------------------
_SECTIONS = {
    "summary": r"(?:professional\s+|career\s+|profile\s+)?(?:summary|profile|objective|career objective|about me|overview)",
    "education": r"education(?:al)?(?:\s+(?:details|qualifications?|background))?|academic(?:s| details| qualifications?| background)?|qualifications?",
    "certifications": r"certifications?(?:\s*(?:&|and)\s*(?:courses|trainings?|licenses?))?|licenses?(?:\s*(?:&|and)\s*certifications?)?|courses|trainings?",
    "projects": r"(?:academic\s+|personal\s+|key\s+|major\s+|college\s+|internship\s+)?projects?(?:\s+(?:during|in|at|undertaken|done)\b[\w\s]{0,30})?",
    "achievements": r"achievements?|awards?(?:\s*(?:&|and)\s*(?:achievements?|recognitions?|honou?rs))?|honou?rs|recognitions?|accomplishments?",
    "languages": r"languages?(?:\s+known|\s+spoken)?|linguistic\s+proficiency",
}
_SEC_RX = {k: re.compile(rf"^\s*(?:{v})\s*[:\-–]?\s*$", re.I) for k, v in _SECTIONS.items()}
_ANY_HEAD = re.compile(r"^\s*[A-Z][A-Za-z &/]{2,40}\s*:?\s*$")
_DEGREE = re.compile(r"\b(?:b\.?\s?tech|b\.?\s?e\.?|m\.?\s?tech|m\.?\s?e\.?|bachelor[a-z']*|master[a-z']*|mba|pgdm|bca|mca|b\.?\s?sc|m\.?\s?sc|b\.?\s?com|m\.?\s?com|"
                     r"b\.?\s?a\.?|m\.?\s?a\.?|ph\.?\s?d|diploma|hsc|ssc|12th|10th|class\s*(?:xii|x|12|10)|intermediate|matriculation|ca\b|cs\b|llb|mbbs|b\.?\s?pharm|m\.?\s?pharm)\b", re.I)
_GRADE = re.compile(r"\b(?:cgpa|gpa|cpi|sgpa|percentage|marks|grade)\s*[:\-]?\s*([\d.]+\s*(?:/\s*\d+|%)?)|\b(\d{2}(?:\.\d+)?\s*%)", re.I)
_LANG_NAMES = ["English", "Hindi", "Bengali", "Marathi", "Telugu", "Tamil", "Gujarati", "Urdu", "Kannada", "Odia", "Oriya", "Malayalam", "Punjabi",
               "Assamese", "Maithili", "Konkani", "Sindhi", "Nepali", "Kashmiri", "Sanskrit", "French", "German", "Spanish", "Japanese", "Mandarin",
               "Chinese", "Arabic", "Russian", "Portuguese", "Italian", "Korean"]
_LANG_RX = re.compile(r"\b(" + "|".join(_LANG_NAMES) + r")\b(?:\s*[\(\-:]\s*(native|fluent|proficient|professional|intermediate|basic|beginner|conversational|mother tongue)\)?)?", re.I)
_MONEY = re.compile(r"(?:inr|rs\.?|₹)?\s*([\d][\d,]*(?:\.\d+)?)\s*(lpa|lakhs?|lacs?|l\b|cr(?:ores?)?|k\b|thousand)?", re.I)


def _section_lines(lines: list[str], key: str, limit: int = 30) -> list[str]:
    out, on = [], False
    for ln in lines:
        s = ln.strip()
        if _SEC_RX[key].match(s):
            on, out = True, out
            continue
        if on:
            if s and (any(rx.match(s) for k, rx in _SEC_RX.items() if k != key) or _WORK_HEAD.match(s) or (_ANY_HEAD.match(s) and s.isupper())):
                break
            if s:
                out.append(s.lstrip("-•*▪●◦➢✓ ").strip())
            if len(out) >= limit:
                break
    return out


def _rupees(num: str, unit: str | None) -> float | None:
    try:
        n = float(num.replace(",", ""))
    except ValueError:
        return None
    u = (unit or "").lower()
    if u.startswith(("lpa", "lakh", "lac", "l")):
        n *= 100000
    elif u.startswith("cr"):
        n *= 10000000
    elif u.startswith(("k", "thousand")):
        n *= 1000
    return n if 10000 <= n <= 100000000 else None


def details(text: str) -> dict:
    """Headline, current role, summary, education, certifications, projects, achievements, spoken languages, salaries, links, preferred
    location and work authorisation, read from the resume's sections. Personal details that must not affect hiring (date of birth,
    gender, marital status, religion, caste, photo) are deliberately not read."""
    t = text or ""
    lines = t.splitlines()
    out: dict = {}
    summ = _section_lines(lines, "summary", 20)
    if summ:
        out["summary"] = " ".join(summ)[:1200]
    edu: list[dict] = []
    for ln in _section_lines(lines, "education", 30):
        ln = re.sub(r"\s{3,}", "  ", ln).strip()
        yr = re.findall(r"\b(?:19|20)\d{2}\b", ln)
        g = _GRADE.search(ln)
        grade = (g.group(1) or g.group(2) or "").strip() if g else ""
        if _DEGREE.search(ln):
            edu.append({"text": ln[:200], "year": yr[-1] if yr else "", "grade": grade})
        elif edu and re.search(r"\b(university|college|institute|school|vidyalaya|vidhyalay|academy|iit|nit|iiit|iim|board|affiliated)\b", ln, re.I) \
                and len(edu[-1]["text"]) + len(ln) < 300:
            edu[-1]["text"] += ", " + ln                       # the institution under its degree
            edu[-1]["year"] = edu[-1]["year"] or (yr[-1] if yr else "")
        elif re.search(r"\b(university|college|institute|school|iit|nit|iiit|iim)\b", ln, re.I):
            edu.append({"text": ln[:200], "year": yr[-1] if yr else "", "grade": grade})
        elif edu and grade and not edu[-1]["grade"]:           # "Result : 81.14 %" / "CGPA: 8.1" on its own line
            edu[-1]["grade"] = grade
        elif edu and yr and not edu[-1]["year"]:
            edu[-1]["year"] = yr[-1]
    if edu:
        out["education"] = [{**e, "text": e["text"][:300]} for e in edu][:8]
    for key in ("certifications", "projects", "achievements"):
        raw = [x for x in _section_lines(lines, key, 40) if x]
        start = re.compile(r"^\s*(?:\d{1,2}\s*[).:]|[-•*▪●◦➢✓])\s*")
        if key == "projects" and sum(bool(start.match(x)) for x in raw) >= 2:    # numbered projects: each with its link and description
            items, cur, pending = [], "", ""
            for x in raw:
                if start.match(x):
                    if cur:
                        items.append(cur)
                    cur = start.sub("", x).strip() + (f" ({pending})" if pending else "")
                    pending = ""
                elif re.fullmatch(r"(?:[A-Za-z]{3,9}\.?\s*[-–/']?\s*)?(?:19|20)\d{2}(?:\s*[-–]\s*(?:[A-Za-z]{3,9}\.?\s*)?(?:(?:19|20)\d{2}|present))?", x, re.I):
                    pending = x                               # a date line above the next project
                elif cur:
                    cur += (" - " if " - " not in cur else " ") + x
            if cur:
                items.append(cur)
            items = [i[:500] for i in items if len(i) >= 3]
        else:
            items = [x for x in raw if 3 <= len(x) <= 300][:20]
        if items:
            out[key] = items[:15]
    langs = {}
    for ln in _section_lines(lines, "languages", 6) or [ln for ln in lines if re.match(r"^\s*languages?\s*(?:known|spoken)?\s*[:\-]", ln, re.I)]:
        for m in _LANG_RX.finditer(ln):
            name = "Odia" if m.group(1).lower() == "oriya" else m.group(1).title()
            langs[name] = (m.group(2) or "").lower()
    if langs:
        out["languages"] = [f"{k} ({v})" if v else k for k, v in langs.items()]
    for kind in ("current", "expected"):
        m = re.search(rf"{kind}\s*(?:ctc|salary|package|compensation)\s*[:\-]?\s*(.{{0,40}})", t, re.I)
        if m:
            mm = _MONEY.search(m.group(1))
            v = _rupees(mm.group(1), mm.group(2)) if mm else None
            if v:
                out[f"{kind}_salary"] = v
    for ln in lines:
        low = ln.lower()
        if "linkedin.com/" in low and "linkedin" not in out:
            out["linkedin"] = re.search(r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/[^\s|,;)]+", ln, re.I).group(0)
        if "github.com/" in low and "github" not in out:
            out["github"] = re.search(r"(?:https?://)?github\.com/[^\s|,;)]+", ln, re.I).group(0)
        m = re.search(r"\b(?:portfolio|website|blog|behance|dribbble)\s*[:\-]\s*(\S+)", ln, re.I) or re.search(r"(?:https?://)?(?:www\.)?(?:behance\.net|dribbble\.com)/\S+", ln, re.I)
        if m and "portfolio" not in out:
            out["portfolio"] = (m.group(1) if m.lastindex else m.group(0)).strip(" |,;")
        m = re.match(r"^\s*(?:preferred|desired)\s+(?:job\s+)?locations?\s*[:\-]\s*(.+)$", ln, re.I)
        if m:
            out["preferred_location"] = m.group(1).strip()[:200]
        m = re.search(r"\b(?:work\s+authori[sz]ation|visa(?:\s+status)?|work\s+permit|citizenship)\s*[:\-]\s*(.+)$", ln, re.I)
        if m:
            out["work_authorization"] = m.group(1).strip()[:200]
        if re.search(r"\b(?:willing|open|ready)\s+to\s+relocate\b", low):
            out["willing_to_relocate"] = not re.search(r"\bnot\s+(?:willing|open|ready)\b", low)
    if "portfolio" not in out:                              # a personal site (github.io, vercel...) is the portfolio
        site = next((u for u in URL.findall(t) if re.search(r"github\.io|vercel\.app|netlify\.app|wixsite|carrd\.co|framer\.website|portfolio", u, re.I)
                     and not re.search(r"(?:linkedin|github)\.com/", u, re.I)), "")
        if site:
            out["portfolio"] = re.sub(r"(\.github\.io/)[^/]+/?$", r"\1", site) if "portfolio" not in site.lower() else site.rstrip(".")
    h = history(t)
    if h["jobs"]:
        latest = h["jobs"][0]
        parts = [p.strip() for p in re.split(r"\s*(?:\||,|\bat\b|@|–|-)\s*", latest["title"]) if p.strip()]
        if parts:
            out["current_title"] = parts[0][:120]
            if len(parts) > 1:
                out["current_company"] = parts[1][:120]
    elif (m := _INTERN_AT.search(t)):                     # an internship written as a sentence, with no dates
        out["current_title"], out["current_company"] = "Intern", m.group(1).strip(" .,")[:120]
    top = []
    for ln in lines[1:8]:                                   # the line under the name, before the first section heading
        s_ = ln.strip()
        if s_ and (any(rx.match(s_) for rx in _SEC_RX.values()) or _WORK_HEAD.match(s_) or _EDU_HEAD.match(s_) or _REF_HEAD.match(s_)):
            break
        top.append(s_)
    first = next((ln for ln in top if ln and 3 < len(ln) < 90 and not EMAIL.search(ln) and not re.search(r"\d{5,}", ln) and not ln[:1].islower()
                  and not re.search(r"\b(?:with|and|of|to|in|for)$", ln, re.I)
                  and re.search(r"\b(engineer|developer|manager|analyst|designer|consultant|executive|specialist|lead|architect|scientist|officer|associate|"
                                r"administrator|recruiter|accountant|intern|student|graduate|fresher)\b", ln, re.I)), "")
    if first:
        out["headline"] = first[:200]
    elif out.get("current_title"):
        out["headline"] = out["current_title"]
    return out
