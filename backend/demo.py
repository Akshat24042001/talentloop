"""Sample data so a new workspace can try everything at once: 6 jobs and 40 synthetic candidates.

Every name, email and phone number here is made up (emails use the reserved example.com domain). Sample records
are marked (jobs: fields["_sample"], candidates: source "demo") so they can be removed in one click."""
import random
import time

from . import db, docs_pdf, flows, jd_schema, matching, resumes

FIRST = ["Aarav", "Ananya", "Rohan", "Priya", "Vikram", "Sneha", "Arjun", "Kavya", "Rahul", "Meera", "Karan", "Isha", "Aditya", "Neha",
         "Siddharth", "Pooja", "Nikhil", "Divya", "Manish", "Riya", "Farhan", "Zoya", "Harpreet", "Lakshmi", "Tenzin", "Joseph", "Fatima",
         "Gaurav", "Shreya", "Amit", "Nandini", "Varun", "Tanvi", "Imran", "Deepa", "Suresh", "Ayesha", "Kunal", "Bhavna", "Rajesh"]
LAST = ["Sharma", "Iyer", "Mehta", "Reddy", "Singh", "Nair", "Gupta", "Rao", "Kapoor", "Das", "Patel", "Menon", "Joshi", "Khan", "Bose",
        "Pillai", "Verma", "Chatterjee", "Kulkarni", "Fernandes"]
CITIES = ["Bengaluru", "Mumbai", "Pune", "Hyderabad", "Chennai", "New Delhi", "Gurugram", "Noida", "Kolkata", "Ahmedabad"]
COMPANIES = ["Northwind Labs", "Bluepeak Systems", "Quantra Retail", "Finlytics", "Orbit Logistics", "Helio Health", "Cobalt Commerce",
             "Kestrel Software", "Saffron Foods", "Meridian Bank", "Vertex Telecom", "Nimbus Cloud"]

PROFILES = {
    "backend": dict(titles=["Backend Engineer", "Senior Software Engineer", "Java Developer", "Software Engineer II"],
                    core=["Java", "Spring Boot", "PostgreSQL", "Microservices", "REST API", "Docker"], extra=["Kafka", "Kubernetes", "AWS", "Redis", "MySQL", "Go", "Python", "CI/CD", "System Design"],
                    lines=["Built and scaled REST APIs serving {n} requests per day", "Designed microservices for payments and order processing",
                           "Cut p95 latency by {p}% by adding caching and query tuning", "Led migration from a monolith to services on Kubernetes",
                           "Owned on-call and incident reviews for core services"]),
    "frontend": dict(titles=["Frontend Developer", "Senior Frontend Engineer", "React Developer", "UI Engineer"],
                     core=["React", "TypeScript", "JavaScript", "HTML", "CSS"], extra=["Next.js", "Redux", "Tailwind CSS", "Jest", "Figma", "Node.js", "GraphQL", "Accessibility", "Webpack"],
                     lines=["Rebuilt the checkout flow in React, lifting conversion by {p}%", "Created a shared component library used by {k} teams",
                            "Improved Lighthouse performance score from 52 to 94", "Worked closely with designers in Figma to ship pixel-accurate UI",
                            "Introduced end-to-end tests that cut regressions"]),
    "sales": dict(titles=["Account Executive", "Senior Account Executive", "Business Development Manager", "Enterprise Sales Manager"],
                  core=["B2B Sales", "Salesforce", "Negotiation", "Lead Generation", "Pipeline Management"], extra=["SaaS", "Cold Calling", "Account Management", "HubSpot", "CRM", "Key Account Management", "Presentation Skills"],
                  lines=["Closed {k} enterprise deals worth INR {n} crore in FY24", "Achieved {p}% of annual quota for three straight years",
                         "Built outbound pipeline from scratch for a new region", "Managed a book of {k}0 mid-market accounts",
                         "Ran demos and negotiated multi-year contracts with CXOs"]),
    "support": dict(titles=["Customer Support Executive", "Customer Support Specialist", "Senior Support Associate", "Customer Success Associate"],
                    core=["Customer Support", "Zendesk", "Communication", "Ticketing", "Problem Solving"], extra=["Freshdesk", "Live Chat", "Email Support", "CRM", "Hindi", "Customer Success", "SLA Management"],
                    lines=["Resolved {n} tickets a month with a {p}% CSAT score", "Handled chat, email and phone support for a consumer app",
                           "Wrote {k}0 help-centre articles that cut repeat tickets", "Trained new joiners on tools and tone of voice",
                           "Escalated product bugs with clear reproduction steps"]),
    "hr": dict(titles=["Talent Acquisition Specialist", "HR Recruiter", "Senior Recruiter", "HR Executive"],
               core=["Recruitment", "Sourcing", "Interviewing", "Stakeholder Management", "Onboarding"], extra=["LinkedIn Recruiter", "Naukri", "ATS", "Employer Branding", "Payroll", "HR Operations", "Campus Hiring"],
               lines=["Closed {k}0 tech and non-tech positions in a year", "Cut time-to-hire from 45 to {k}0 days", "Ran campus hiring drives across {k} colleges",
                      "Partnered with hiring managers to define role scorecards", "Managed offers, negotiation and onboarding end to end"]),
    "data": dict(titles=["Data Analyst", "Senior Data Analyst", "Business Analyst", "Product Analyst"],
                 core=["SQL", "Excel", "Power BI", "Python", "Data Analysis"], extra=["Tableau", "Pandas", "Statistics", "A/B Testing", "Looker", "Google Analytics", "BigQuery", "Dashboards"],
                 lines=["Built Power BI dashboards used daily by {k}0 managers", "Automated weekly reporting with SQL and Python, saving {k} hours a week",
                        "Ran A/B tests that lifted retention by {p}%", "Modelled churn drivers for the leadership team",
                        "Cleaned and joined data from {k} sources into one warehouse"]),
}

JOBS = [
    dict(kind="backend", title="Senior Backend Engineer", department="Engineering", team="Payments platform", seniority="Senior", workplace_type="Hybrid",
         locations=["Bengaluru"], office_days=3, experience_min=4, experience_max=9, salary_min=2800000, salary_max=4500000,
         must_have_skills=["Java", "Spring Boot", "PostgreSQL", "Microservices"], nice_to_have_skills=["Kafka", "Kubernetes", "AWS"],
         summary="Own the services that move money for millions of customers. You will design, build and run high-throughput APIs with a small senior team.",
         responsibilities=["Design and build reliable, well-tested backend services", "Own services in production, including on-call", "Review code and raise the bar on design",
                           "Work with product to shape the roadmap", "Mentor engineers on the team"], max_notice_days=60, priority="High", openings=2),
    dict(kind="frontend", title="Frontend Developer (React)", department="Engineering", team="Growth", seniority="Mid level", workplace_type="Remote",
         remote_regions="India", experience_min=2, experience_max=6, salary_min=1500000, salary_max=2600000,
         must_have_skills=["React", "TypeScript", "CSS"], nice_to_have_skills=["Next.js", "Jest", "Figma"],
         summary="Build fast, accessible product experiences that customers love, working closely with design and growth.",
         responsibilities=["Ship features end to end in React and TypeScript", "Keep the UI fast and accessible", "Build reusable components", "Write tests"], max_notice_days=45),
    dict(kind="sales", title="Enterprise Account Executive", department="Sales", seniority="Senior", workplace_type="On-site", locations=["Mumbai", "New Delhi"],
         experience_min=5, experience_max=12, salary_min=2400000, salary_max=3600000, variable_pay="Up to 40% on target",
         must_have_skills=["B2B Sales", "Salesforce", "Negotiation"], nice_to_have_skills=["SaaS", "Key Account Management"],
         summary="Win and grow our largest customers. You will run complex sales cycles with CXO stakeholders.",
         responsibilities=["Own a quota and a named account list", "Build pipeline through outbound and partners", "Run demos and negotiations", "Forecast accurately in Salesforce"], priority="Urgent"),
    dict(kind="support", title="Customer Support Specialist", department="Customer Support", seniority="Entry level", workplace_type="On-site", locations=["Hyderabad"],
         shift="Rotational", experience_min=0, experience_max=3, salary_min=350000, salary_max=550000,
         must_have_skills=["Customer Support", "Communication", "Zendesk"], nice_to_have_skills=["Hindi", "Live Chat"],
         summary="Be the friendly, fast voice of our product for customers across India.",
         responsibilities=["Resolve chat, email and phone tickets", "Meet response and resolution SLAs", "Spot and report product issues"], max_notice_days=30, openings=5),
    dict(kind="hr", title="Talent Acquisition Specialist", department="Human Resources", seniority="Associate", workplace_type="Hybrid", locations=["Pune"],
         experience_min=2, experience_max=6, salary_min=700000, salary_max=1200000,
         must_have_skills=["Recruitment", "Sourcing", "Stakeholder Management"], nice_to_have_skills=["LinkedIn Recruiter", "Campus Hiring"],
         summary="Help us hire great people quickly and fairly across tech and business roles.",
         responsibilities=["Run full-cycle hiring for 10-15 open roles", "Source on LinkedIn and job boards", "Partner with hiring managers on scorecards"]),
    dict(kind="data", title="Data Analyst", department="Data & Analytics", seniority="Mid level", workplace_type="Hybrid", locations=["Gurugram", "Noida"],
         experience_min=2, experience_max=5, salary_min=1000000, salary_max=1800000,
         must_have_skills=["SQL", "Power BI", "Excel"], nice_to_have_skills=["Python", "A/B Testing"],
         summary="Turn data into decisions for the product and operations teams.",
         responsibilities=["Build and maintain dashboards", "Answer business questions with SQL", "Design and read experiments"]),
]
SCREENING = [{"id": "auth", "question": "Are you legally authorised to work in India?", "kind": "yes_no", "required": True, "required_answer": "yes"},
             {"id": "notice", "question": "What is your notice period in days?", "kind": "number", "required": True}]


def _resume(rnd: random.Random, kind: str, i: int) -> tuple[dict, str]:
    p = PROFILES[kind]
    name = f"{FIRST[i % len(FIRST)]} {LAST[(i * 7) % len(LAST)]}"
    years = round(rnd.choice([0.5, 1, 2, 3, 4, 5, 6, 7, 8, 10, 12]) + rnd.choice([0, 0.5]), 1)
    city = rnd.choice(CITIES)
    sk = list(dict.fromkeys(rnd.sample(p["core"], k=max(2, len(p["core"]) - rnd.randint(0, 2))) + rnd.sample(p["extra"], k=rnd.randint(1, 4))))
    title = p["titles"][min(len(p["titles"]) - 1, int(years // 3))]
    notice = rnd.choice([15, 30, 30, 45, 60, 60, 90])
    now_y = time.gmtime().tm_year
    exp, start = [], now_y - int(years) if years >= 1 else now_y
    jobs_n = 1 if years < 3 else 2 if years < 7 else 3
    span = max(1, int(years) // jobs_n)
    fill = lambda s: s.format(n=rnd.choice(["2 million", "500K", "10 million"]) if "{n}" in s and kind in ("backend",) else rnd.randint(2, 40), p=rnd.randint(12, 45), k=rnd.randint(2, 9))  # noqa: E731
    for j in range(jobs_n):
        s_y = start + j * span
        e_y = "" if j == jobs_n - 1 else str(s_y + span)
        exp.append({"title": title if j == jobs_n - 1 else p["titles"][max(0, min(len(p["titles"]) - 1, j))], "company": rnd.choice(COMPANIES),
                    "start": f"Jun {s_y}", "end": f"May {e_y}" if e_y else "", "location": city,
                    "description": "\n".join(fill(x) for x in rnd.sample(p["lines"], 3))})
    exp.reverse()
    edu = [{"degree": "B.Tech" if kind in ("backend", "frontend", "data") else rnd.choice(["BBA", "B.Com", "BA", "MBA"]),
            "field": "Computer Science" if kind in ("backend", "frontend") else "", "school": rnd.choice(["Anna University", "Pune University", "VIT Vellore", "Delhi University", "Osmania University", "Mumbai University"]),
            "year": str(start - (1 if years >= 1 else 0))}]
    email = f"{name.lower().replace(' ', '.')}{i}@example.com"
    profile = {"name": name, "email": email, "phone": f"+91 90000 {10000 + i:05d}", "location": city, "headline": title,
               "current_company": exp[0]["company"], "summary": f"{title} with {years:g} years of experience in {', '.join(sk[:3])}.",
               "skills": sk, "experience": exp, "education": edu, "notice_days": notice, "total_experience_years": years,
               "willing_to_relocate": rnd.random() < 0.35}
    text = resumes.profile_text(profile) + f"\nNotice period: {notice} days\n{email}\n{profile['phone']}"
    return profile, text


def seed(s, org: db.Org, user_id: str | None) -> dict:
    rnd = random.Random(hash(org.id) & 0xFFFF)
    jobs = []
    for spec in JOBS:
        f = {**jd_schema.defaults(), **jd_schema.clean({k: v for k, v in spec.items() if k != "kind"}), "screening_questions": jd_schema.clean({"screening_questions": SCREENING})["screening_questions"],
             "top_n": 5, "_sample": True, "ai_interview_questions": ["What is your notice period?", "Why are you looking for a change?"]}
        j = db.Job(org_id=org.id, title=f["title"], department=f["department"], status="open", fields=f, top_n=5, created_by=user_id, published_at=time.time(),
                   number=db.next_number(s, org.id, "job"))
        s.add(j)
        jobs.append((spec["kind"], j))
    s.flush()
    kinds = [k for k in PROFILES for _ in range(7)][:40]
    cands = []
    for i, kind in enumerate(kinds):
        profile, text = _resume(rnd, kind, i)
        c = db.Candidate(org_id=org.id, name=profile["name"], email=profile["email"], phone=profile["phone"], location=profile["location"],
                         headline=profile["headline"], profile=profile, parsed=resumes.parse(text), resume_text=text, source="demo", tags=["sample"],
                         created_at=time.time() - rnd.randint(0, 20) * 86400, number=db.next_number(s, org.id, "candidate"))
        matching.compute_features(c)
        s.add(c); s.flush()
        from .api_hiring import _save_resume
        c.resume_file, c.resume_name = _save_resume(org.id, c.id, docs_pdf.resume_pdf(profile), f"{profile['name'].replace(' ', '-')}-resume.pdf")
        cands.append((kind, c))
    # a few applications so every pipeline has people in it
    stages = ["applied", "applied", "applied", "screening", "shortlisted", "interview", "rejected"]
    for kind, j in jobs:
        pool = [c for k, c in cands if k == kind]
        for n, c in enumerate(rnd.sample(pool, k=min(len(pool), 4))):
            a = db.Application(org_id=org.id, job_id=j.id, candidate_id=c.id, stage=stages[(n * 2) % len(stages)], source="careers",
                               answers={"auth": "yes", "notice": str((c.profile or {}).get("notice_days", 30))},
                               created_at=time.time() - rnd.randint(0, 13) * 86400)
            s.add(a); s.flush()
            flows.on_applied(s, a, j, notify=False)      # samples enter the job's flow like real applicants, without messages
            if a.stage != "rejected" and stages[(n * 2) % len(stages)] == "rejected":
                flows.reject(s, a, "Sample rejection", actor=None, notify=False)
    return {"jobs": len(jobs), "candidates": len(cands)}


def clear(s, org_id: str) -> dict:
    from . import store
    jobs = [j for j in s.query(db.Job).filter_by(org_id=org_id) if (j.fields or {}).get("_sample")]
    cands = s.query(db.Candidate).filter_by(org_id=org_id, source="demo").all()
    jids, cids = [j.id for j in jobs], [c.id for c in cands]
    for model, col, ids in ((db.Match, "job_id", jids), (db.RoundResult, "job_id", jids), (db.Slot, "job_id", jids),
                            (db.Message, "candidate_id", cids), (db.RoundResult, "candidate_id", cids),
                            (db.Application, "job_id", jids), (db.JobCollaborator, "job_id", jids),
                            (db.Match, "candidate_id", cids), (db.Application, "candidate_id", cids)):
        if ids:
            s.query(model).filter(getattr(model, col).in_(ids)).delete(synchronize_session=False)
    for j in jobs:
        s.delete(j)
    for c in cands:
        s.delete(c)
        store.delete_files(f"{org_id}/candidates/{c.id}")
    return {"jobs": len(jobs), "candidates": len(cands)}
