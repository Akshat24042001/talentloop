"""The job description: every field HR (or an assigned hiring manager) can fill in, in one place.

The web form is generated from SECTIONS (served by /api/meta/job-fields), the server validates against it, and the
careers page, the PDF and the matching engine read the same fields. Only a handful are required to publish.
"""
DEPARTMENTS = ["Engineering", "Product", "Design", "Data & Analytics", "Sales", "Marketing", "Customer Support", "Customer Success",
               "Operations", "Human Resources", "Finance & Accounting", "Legal", "IT & Security", "Administration", "Other"]
SENIORITY = ["Intern", "Entry level", "Associate", "Mid level", "Senior", "Lead / Principal", "Manager", "Senior manager", "Director", "VP", "C-level"]
EMPLOYMENT = ["Full-time", "Part-time", "Contract", "Internship", "Temporary", "Freelance"]
WORKPLACE = ["On-site", "Hybrid", "Remote"]
CURRENCIES = ["INR", "USD", "EUR", "GBP", "AED", "SGD", "AUD", "CAD"]
EDUCATION = ["No requirement", "High school", "Diploma", "Bachelor's degree", "Master's degree", "MBA", "PhD", "Professional certification (CA, CS, etc.)"]
STAGES = ["Application review", "AI screening interview", "Technical / skills round", "Hiring manager round", "HR & offer"]

F = dict  # readability


SECTIONS = [
    F(id="basics", title="Role basics", description="What the role is and who it's for.", fields=[
        F(key="title", label="Job title", type="text", required=True, placeholder="Senior Backend Engineer", max=120),
        F(key="department", label="Department", type="select", required=True, options=DEPARTMENTS),
        F(key="team", label="Team", type="text", placeholder="Payments platform"),
        F(key="seniority", label="Seniority", type="select", options=SENIORITY),
        F(key="employment_type", label="Employment type", type="select", required=True, options=EMPLOYMENT, default="Full-time"),
        F(key="openings", label="Number of openings", type="number", min=1, max=500, default=1),
        F(key="requisition_id", label="Requisition / job code", type="text", placeholder="ENG-2026-014"),
        F(key="reports_to", label="Reports to", type="text", placeholder="Engineering Manager"),
        F(key="hire_reason", label="Reason for hiring", type="select", options=["New role", "Backfill", "Team expansion", "Confidential"]),
        F(key="priority", label="Priority", type="select", options=["Low", "Normal", "High", "Urgent"], default="Normal"),
        F(key="target_start", label="Target start date", type="date"),
        F(key="deadline", label="Application deadline", type="date"),
    ]),
    F(id="location", title="Location & work model", description="Where and how the person works.", fields=[
        F(key="workplace_type", label="Workplace type", type="select", required=True, options=WORKPLACE, default="Hybrid"),
        F(key="locations", label="Office location(s)", type="tags", placeholder="Bengaluru, India", help="Required unless the role is remote.",
          required_unless={"workplace_type": "Remote"}),
        F(key="office_days", label="Days in office per week", type="number", min=1, max=6, show_if={"workplace_type": "Hybrid"}),
        F(key="remote_regions", label="Remote: eligible countries or regions", type="text", show_if={"workplace_type": "Remote"}, placeholder="India only"),
        F(key="timezone", label="Working hours / time zone overlap", type="text", placeholder="IST, overlap until 6 pm"),
        F(key="shift", label="Shift", type="select", options=["Day", "Night", "Rotational", "Flexible"]),
        F(key="travel", label="Travel required", type="select", options=["None", "Occasional (under 25%)", "Frequent (25-50%)", "Mostly travel (over 50%)"]),
        F(key="relocation", label="Relocation support", type="select", options=["Not offered", "Offered", "Case by case"]),
        F(key="visa_sponsorship", label="Visa sponsorship", type="select", options=["Not available", "Available"]),
    ]),
    F(id="compensation", title="Compensation & benefits", description="Posting a salary range gets more and better-fit applicants.", fields=[
        F(key="currency", label="Currency", type="select", options=CURRENCIES, default="INR"),
        F(key="salary_min", label="Salary from", type="number", min=0),
        F(key="salary_max", label="Salary to", type="number", min=0),
        F(key="pay_period", label="Per", type="select", options=["Year", "Month", "Hour"], default="Year"),
        F(key="show_salary", label="Show the salary range on the job post", type="toggle", default=True),
        F(key="variable_pay", label="Variable pay / incentives", type="text", placeholder="Up to 15% annual bonus"),
        F(key="equity", label="Equity", type="select", options=["None", "Stock options (ESOP)", "RSUs", "Phantom stock"]),
        F(key="benefits", label="Benefits", type="benefits",
          help="Your company's benefits list. Add the ones you offer; they're saved for your other jobs too."),
        F(key="perks", label="Other perks", type="textarea", rows=2),
    ]),
    F(id="role", title="About the role", description="What the person will actually do.", fields=[
        F(key="summary", label="Role summary", type="textarea", rows=4, placeholder="Two or three sentences on why this role exists and its impact."),
        F(key="responsibilities", label="Key responsibilities", type="list", placeholder="Own the design and delivery of ..."),
        F(key="first_90_days", label="What success looks like (first 90 days)", type="list"),
        F(key="day_in_life", label="A typical day", type="textarea", rows=3),
        F(key="team_overview", label="The team", type="textarea", rows=2),
        F(key="tools", label="Tools & tech stack", type="tags", placeholder="Java, Spring Boot, PostgreSQL"),
    ]),
    F(id="requirements", title="Requirements", description="Used for matching. Keep must-haves to the real non-negotiables.", fields=[
        F(key="experience_min", label="Minimum experience (years)", type="number", required=True, min=0, max=40, default=0),
        F(key="experience_max", label="Maximum experience (years)", type="number", min=0, max=50),
        F(key="must_have_skills", label="Must-have skills", type="skills", required=True, help="Candidates are ranked mainly on these."),
        F(key="nice_to_have_skills", label="Nice-to-have skills", type="skills"),
        F(key="education", label="Minimum education", type="select", options=EDUCATION, default="No requirement"),
        F(key="field_of_study", label="Field of study", type="text", placeholder="Computer Science or related"),
        F(key="certifications", label="Certifications", type="tags"),
        F(key="languages", label="Languages", type="tags", placeholder="English (fluent), Hindi"),
        F(key="industry_experience", label="Industry / domain experience", type="text", placeholder="Fintech or e-commerce preferred"),
        F(key="soft_skills", label="Soft skills", type="tags", placeholder="Stakeholder management"),
        F(key="max_notice_days", label="Maximum notice period (days)", type="number", min=0, max=180),
    ]),
    F(id="process", title="Hiring process & screening", description="What candidates go through, and questions asked when they apply.", fields=[
        F(key="interview_stages", label="Interview stages", type="list", default=STAGES),
        F(key="screening_questions", label="Screening questions", type="questions",
          help="Asked on the application form. Mark a required answer to screen out automatically (for example work authorisation)."),
        F(key="ai_interview", label="Invite shortlisted candidates to an AI first-round interview", type="toggle", default=True),
        F(key="ai_interview_questions", label="Questions the AI interviewer must ask", type="list", show_if={"ai_interview": True}),
        F(key="assessment", label="Assessment / assignment", type="text", placeholder="Take-home task, 3 hours"),
    ]),
    F(id="posting", title="Posting & company", description="How the job appears on your careers page.", fields=[
        F(key="about_company", label="About the company", type="textarea", rows=3, help="Leave empty to use the text from Settings."),
        F(key="eeo", label="Equal opportunity statement", type="textarea", rows=2, help="Leave empty to use the text from Settings."),
        F(key="application_instructions", label="Application instructions", type="textarea", rows=2),
        F(key="recruiter_contact", label="Recruiter contact (shown to candidates)", type="text", placeholder="careers@company.com"),
        F(key="confidential", label="Confidential: hide the company name on the post", type="toggle", default=False),
        F(key="internal_only", label="Internal only: don't list on the public careers page", type="toggle", default=False),
    ]),
    F(id="matching", title="Matching", description="How candidates are shortlisted for this job.", fields=[
        F(key="top_n", label="Candidates to shortlist", type="number", min=1, max=50, help="The AI writes match reports only for this many."),
        F(key="strict_must_have", label="Screen out candidates missing any must-have skill", type="toggle", default=False),
        F(key="strict_experience", label="Screen out candidates below the minimum experience", type="toggle", default=False),
        F(key="strict_location", label="Screen out candidates outside the job locations (not for remote roles)", type="toggle", default=False),
        F(key="strict_notice", label="Screen out candidates above the maximum notice period", type="toggle", default=False),
    ]),
]
FIELDS = {f["key"]: f for sec in SECTIONS for f in sec["fields"]}
REQUIRED_TO_PUBLISH = [k for k, f in FIELDS.items() if f.get("required") or f.get("required_unless")]
LIST_TYPES = ("tags", "skills", "list", "multiselect", "benefits")


def defaults() -> dict:
    return {k: f["default"] for k, f in FIELDS.items() if "default" in f}


def clean(raw: dict) -> dict:
    """Coerce and bound every known field; unknown keys are dropped."""
    from . import skills
    out = {}
    for k, v in (raw or {}).items():
        f = FIELDS.get(k)
        if f is None or v is None:
            continue
        t = f["type"]
        if t in ("text", "date", "select"):
            v = str(v).strip()[: f.get("max", 300)]
            if t == "select" and v and v not in f["options"]:
                continue
        elif t == "textarea":
            v = str(v).strip()[:6000]
        elif t == "number":
            if v == "":
                continue
            try:
                v = float(v)
                v = int(v) if v == int(v) else v
            except (TypeError, ValueError):
                continue
            v = max(f.get("min", -1e12), min(f.get("max", 1e12), v))
        elif t == "toggle":
            v = bool(v)
        elif t in LIST_TYPES:
            items = v if isinstance(v, list) else str(v).split(",")
            items = [str(x).strip()[:200] for x in items if str(x).strip()]
            if t == "skills":
                items = [skills.canonical(x) for x in items]
            if t == "multiselect":
                items = [x for x in items if x in f["options"]]
            if t == "benefits":                     # free text from the company's own list
                items = [x[:80] for x in items][:40]
            v = list(dict.fromkeys(items))[:60]
        elif t == "questions":
            qs = []
            for q in (v if isinstance(v, list) else [])[:20]:
                if not isinstance(q, dict) or not str(q.get("question") or "").strip():
                    continue
                kind = q.get("kind") if q.get("kind") in ("yes_no", "text", "number") else "yes_no"
                must = q.get("required_answer")
                qs.append({"id": str(q.get("id") or len(qs) + 1)[:20], "question": str(q["question"]).strip()[:300], "kind": kind,
                           "required": bool(q.get("required", True)), "required_answer": must if kind == "yes_no" and must in ("yes", "no") else None,
                           "min_number": float(q["min_number"]) if kind == "number" and q.get("min_number") not in (None, "") else None})
            v = qs
        out[k] = v
    return out


def missing_to_publish(fields: dict) -> list[str]:
    miss = []
    for k in REQUIRED_TO_PUBLISH:
        f = FIELDS[k]
        cond = f.get("required_unless")
        if cond and all(fields.get(ck) == cv for ck, cv in cond.items()):
            continue
        v = fields.get(k)
        if v in (None, "", []) and not (f["type"] == "number" and v == 0):
            miss.append(f["label"])
    return miss


def money(v, cur: str) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return ""
    if cur == "INR" and v >= 100000:
        return f"₹{v / 100000:.1f} L".replace(".0 L", " L")
    sym = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}.get(cur, cur + " ")
    return f"{sym}{v:,.0f}"


def salary_text(f: dict) -> str:
    lo, hi, cur, per = f.get("salary_min"), f.get("salary_max"), f.get("currency", "INR"), (f.get("pay_period") or "Year").lower()
    if lo in (None, "") and hi in (None, ""):
        return ""
    if lo not in (None, "") and hi not in (None, ""):
        return f"{money(lo, cur)} - {money(hi, cur)} per {per}"
    return f"{'From ' + money(lo, cur) if lo not in (None, '') else 'Up to ' + money(hi, cur)} per {per}"


def experience_text(f: dict) -> str:
    lo, hi = f.get("experience_min"), f.get("experience_max")
    if lo in (None, "") and hi in (None, ""):
        return ""
    if hi not in (None, "") and lo not in (None, ""):
        return f"{lo}-{hi} years"
    return f"{lo}+ years" if lo not in (None, "") else f"Up to {hi} years"


def location_text(f: dict) -> str:
    wt = f.get("workplace_type") or ""
    locs = ", ".join(f.get("locations") or [])
    if wt == "Remote":
        return "Remote" + (f" ({f['remote_regions']})" if f.get("remote_regions") else "")
    if wt == "Hybrid":
        return f"Hybrid · {locs}" + (f" · {f['office_days']} days in office" if f.get("office_days") else "") if locs else "Hybrid"
    return f"{locs} (on-site)" if locs else wt


def compose(job_fields: dict, org_name: str, org_settings: dict, public: bool = True) -> dict:
    """Ready-to-render JD: headline facts and ordered sections (used by the careers page and the PDF)."""
    f = job_fields
    facts = [x for x in [f.get("department"), f.get("employment_type"), location_text(f), experience_text(f) and f"Experience: {experience_text(f)}",
                         f.get("seniority")] if x]
    show_pay = f.get("show_salary", True) or not public
    if show_pay and salary_text(f):
        facts.append(salary_text(f))
    sections = []
    def add(title, body=None, items=None):
        if body or items:
            sections.append({"title": title, "body": body or "", "items": items or []})
    add("About the role", f.get("summary"))
    add("What you'll do", items=f.get("responsibilities"))
    add("What success looks like in your first 90 days", items=f.get("first_90_days"))
    req = []
    if experience_text(f):
        req.append(f"{experience_text(f)} of relevant experience")
    if f.get("must_have_skills"):
        req.append("Hands-on skills in " + ", ".join(f["must_have_skills"]))
    if f.get("education") and f["education"] != "No requirement":
        req.append(f"{f['education']}" + (f" in {f['field_of_study']}" if f.get("field_of_study") else ""))
    if f.get("industry_experience"):
        req.append(f["industry_experience"])
    req += [f"Certification: {c}" for c in f.get("certifications") or []]
    if f.get("languages"):
        req.append("Languages: " + ", ".join(f["languages"]))
    add("What you'll need", items=req)
    add("Nice to have", items=f.get("nice_to_have_skills"))
    add("Tools & tech stack", ", ".join(f.get("tools") or []))
    add("A typical day", f.get("day_in_life"))
    add("The team", f.get("team_overview"))
    perks = list(f.get("benefits") or [])
    if f.get("variable_pay"):
        perks.append(f"Variable pay: {f['variable_pay']}")
    if f.get("equity") and f["equity"] != "None":
        perks.append(f["equity"])
    add("Benefits & perks", f.get("perks"), perks)
    add("Hiring process", items=f.get("interview_stages"))
    logistics = [x for x in [f.get("timezone") and f"Working hours: {f['timezone']}", f.get("shift") and f"Shift: {f['shift']}",
                             f.get("travel") and f.get("travel") != "None" and f"Travel: {f['travel']}",
                             f.get("relocation") and f.get("relocation") != "Not offered" and f"Relocation: {f['relocation']}",
                             f.get("visa_sponsorship") == "Available" and "Visa sponsorship available",
                             f.get("max_notice_days") not in (None, "") and f"Preferred notice period: up to {f['max_notice_days']} days",
                             f.get("deadline") and f"Apply by {f['deadline']}"] if x]
    add("Good to know", items=logistics)
    confidential = public and f.get("confidential")
    about = f.get("about_company") or org_settings.get("about")
    if not confidential:
        add(f"About {org_name}", about)
    add("How to apply", f.get("application_instructions"))
    add("Equal opportunity", f.get("eeo") or org_settings.get("eeo_statement"))
    return {"title": f.get("title", ""), "company": "Confidential company" if confidential else org_name, "facts": facts, "sections": sections,
            "contact": f.get("recruiter_contact", "")}


def matching_text(f: dict) -> str:
    """The text the keyword relevance score searches with."""
    parts = [f.get("title", ""), f.get("title", ""), f.get("seniority", ""), f.get("department", ""), f.get("summary", ""),
             " ".join(f.get("responsibilities") or []), " ".join(f.get("tools") or []), " ".join((f.get("must_have_skills") or []) * 2),
             " ".join(f.get("nice_to_have_skills") or []), f.get("industry_experience", ""), " ".join(f.get("certifications") or [])]
    return " ".join(p for p in parts if p)
