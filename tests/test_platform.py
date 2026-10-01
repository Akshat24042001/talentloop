"""Accounts, roles, companies, jobs, candidates, applications and matching: python -m tests.test_platform

Runs against the real app with a fresh SQLite database and the fake LLM."""
import io
import os
import tempfile

os.environ.update({"LLM_MOCK": "1", "PUBLIC_URL": "https://example.trycloudflare.com", "VAPI_PUBLIC_KEY": "pk_test",
                   "ADMIN_KEY": "", "DATA_DIR": tempfile.mkdtemp(), "DATABASE_URL": os.getenv("TEST_DATABASE_URL", ""), "FINISH_DELAY_SEC": "0",
                   "PLATFORM_ADMIN_EMAILS": "founder@talentloop.test"})

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402


def client() -> TestClient:
    return TestClient(app)


def ok(r, code=200):
    assert r.status_code == code, f"{r.request.method} {r.request.url.path}: {r.status_code} {r.text[:300]}"
    return r.json() if r.headers.get("content-type", "").startswith("application/json") else r


def signup(c, email, company, name="Test User", pw="correct-horse-1"):
    return ok(c.post("/api/auth/signup", json={"email": email, "password": pw, "name": name, "company": company}))


def accounts():
    anon = client()
    assert anon.get("/api/auth/me").status_code == 401
    assert anon.get("/api/interviews").status_code == 401, "interviews must need sign-in"

    # sign-up creates a company with the person as its owner
    owner = client()
    me = signup(owner, "Priya@Acme.test", "Acme Corp", "Priya Owner")
    assert me["role"] == "owner" and me["org"]["slug"] == "acme-corp" and me["user"]["email"] == "priya@acme.test"
    assert me["can"]["manage_team"] and not me["platform_admin"]
    assert ok(owner.get("/api/auth/me"))["org"]["name"] == "Acme Corp"
    # duplicate email, weak password, bad email
    assert client().post("/api/auth/signup", json={"email": "priya@acme.test", "password": "x" * 9, "name": "a", "company": "b"}).status_code == 409
    assert client().post("/api/auth/signup", json={"email": "new@acme.test", "password": "short", "name": "a", "company": "b"}).status_code == 400
    assert client().post("/api/auth/signup", json={"email": "nope", "password": "x" * 9, "name": "a", "company": "b"}).status_code == 400
    # same company name gets a unique careers slug
    other = client()
    assert signup(other, "boss@acme2.test", "Acme Corp")["org"]["slug"] == "acme-corp-2"

    # login / logout
    c2 = client()
    assert c2.post("/api/auth/login", json={"email": "priya@acme.test", "password": "wrong-pass"}).status_code == 401
    ok(c2.post("/api/auth/login", json={"email": "PRIYA@acme.test", "password": "correct-horse-1"}))
    assert ok(c2.get("/api/auth/me"))["role"] == "owner"
    ok(c2.post("/api/auth/logout"))
    assert c2.get("/api/auth/me").status_code == 401

    # invites: HR (recruiter) and a sales manager (hiring manager) join
    inv = ok(owner.post("/api/team/invites", json={"email": "hr@acme.test", "role": "recruiter", "title": "HR Lead"}))
    tok = inv["path"].rsplit("/", 1)[1]
    info = ok(client().get(f"/api/invites/{tok}"))
    assert info["org"] == "Acme Corp" and info["role"] == "recruiter" and not info["has_account"]
    hr = client()
    assert ok(hr.post(f"/api/invites/{tok}/accept", json={"name": "Harsh HR", "password": "hr-password-1"}))["role"] == "recruiter"
    assert client().get(f"/api/invites/{tok}").status_code == 404, "invite links are single use"
    inv2 = ok(owner.post("/api/team/invites", json={"email": "sales.mgr@acme.test", "role": "hiring_manager", "title": "Sales Manager"}))
    mgr = client()
    ok(mgr.post(f"/api/invites/{inv2['path'].rsplit('/', 1)[1]}/accept", json={"name": "Sam Sales", "password": "mgr-password-1"}))
    inv3 = ok(owner.post("/api/team/invites", json={"email": "viewer@acme.test", "role": "viewer"}))
    viewer = client()
    ok(viewer.post(f"/api/invites/{inv3['path'].rsplit('/', 1)[1]}/accept", json={"name": "Vee", "password": "viewer-pass-1"}))

    team = ok(owner.get("/api/team"))
    assert {m["role"] for m in team["members"]} == {"owner", "recruiter", "hiring_manager", "viewer"}
    # role limits
    assert hr.post("/api/team/invites", json={"email": "x@acme.test", "role": "viewer"}).status_code == 403, "HR can't manage the team"
    assert mgr.patch("/api/org", json={"name": "Hacked"}).status_code == 403
    owner_m = next(m for m in team["members"] if m["role"] == "owner")
    assert owner.patch(f"/api/team/members/{owner_m['id']}", json={"role": "admin"}).status_code == 400, "last owner can't be demoted"
    assert owner.delete(f"/api/team/members/{owner_m['id']}").status_code == 400

    # settings
    st = ok(owner.patch("/api/org", json={"settings": {"match_top_n": 7, "about": "We build things.", "bogus": 1}}))
    assert st["settings"]["match_top_n"] == 7 and "bogus" not in st["settings"]

    # companies are isolated: Acme 2 can't see Acme's team or interviews
    assert all(m["email"] != "priya@acme.test" for m in ok(other.get("/api/team"))["members"])

    # platform admin console: only for PLATFORM_ADMIN_EMAILS
    assert owner.get("/api/admin/overview").status_code == 403
    founder = client()
    me_f = signup(founder, "founder@talentloop.test", "TalentLoop HQ")
    assert me_f["platform_admin"]
    ov = ok(founder.get("/api/admin/overview"))
    assert ov["orgs"] == 3 and ov["users"] == 6, ov
    orgs = ok(founder.get("/api/admin/orgs"))
    acme = next(o for o in orgs if o["slug"] == "acme-corp")
    assert acme["members"] == 4 and acme["owner"] == "priya@acme.test"
    users = ok(founder.get("/api/admin/users"))
    assert next(u for u in users if u["email"] == "priya@acme.test")["login_count"] >= 2
    # disabling a user signs them out everywhere
    vid = next(u["id"] for u in users if u["email"] == "viewer@acme.test")
    ok(founder.patch(f"/api/admin/users/{vid}", json={"disabled": True}))
    assert viewer.get("/api/auth/me").status_code == 401
    print("ACCOUNTS AND ROLES: OK")
    return {"owner": owner, "hr": hr, "mgr": mgr, "other": other, "founder": founder}


def interviews_scoped(cs):
    owner, other = cs["owner"], cs["other"]
    inp = {"company": "Acme", "role": "Backend Developer", "candidate_name": "Rohan", "duration_min": 15,
           "jd": "Java Spring Boot developer " * 10, "resume": "Java Spring Boot SQL " * 10, "questions": ["Notice period?"]}
    plan = ok(owner.post("/api/plan", json=inp))["plan"]
    made = ok(owner.post("/api/interviews", json={"plan": plan, "inputs": inp}))
    assert made["report_path"] == f"/app/interviews/{made['id']}"
    assert [r["id"] for r in ok(owner.get("/api/interviews"))] == [made["id"]]
    assert ok(other.get("/api/interviews")) == [], "another company must not see this interview"
    assert other.get(f"/api/interviews/{made['id']}").status_code == 404
    assert cs["mgr"].post("/api/interviews", json={"plan": plan, "inputs": inp}).status_code == 403, "hiring managers need a job assignment"
    print("INTERVIEWS SCOPED TO COMPANY: OK")
    return made["id"]


RESUMES = {
    "anita.txt": """Anita Sharma
anita.sharma@mail.test | +91 98765 43210 | Bengaluru
Senior Backend Engineer
Experience: 6 years
Backend engineer building payment APIs with Java, Spring Boot, Microservices, PostgreSQL, Kafka, Docker and Kubernetes on AWS.
Notice period: 30 days""",
    "vikram.txt": """Vikram Rao
vikram.rao@mail.test | Pune
Java Developer, 3 years of experience with Java, Spring Boot, MySQL and REST APIs. Some Docker.
Notice period: 60 days""",
    "meera.txt": """Meera Iyer
meera@mail.test | Mumbai
Enterprise Account Executive with 7 years of experience in B2B SaaS sales, Salesforce CRM, lead generation,
negotiation, pipeline management and closing enterprise deals. Exceeded quota every year.""",
    "karan.txt": """Karan Singh
karan.singh@mail.test | Bangalore
Full stack developer, 4 years. React, TypeScript, Node.js, Java, Spring Boot, PostgreSQL, Docker.""",
}

BACKEND_JD = {"title": "Senior Backend Engineer", "department": "Engineering", "employment_type": "Full-time", "workplace_type": "Hybrid",
              "locations": ["Bengaluru"], "experience_min": 4, "experience_max": 9, "must_have_skills": ["java", "spring boot", "postgres"],
              "nice_to_have_skills": ["kafka", "k8s"], "summary": "Build our payments platform.", "responsibilities": ["Design APIs", "Own services"],
              "salary_min": 2500000, "salary_max": 4000000, "max_notice_days": 60, "top_n": 2,
              "screening_questions": [{"id": "auth", "question": "Are you authorised to work in India?", "kind": "yes_no", "required_answer": "yes"}]}


def hiring(cs):
    owner, hr, mgr, other = cs["owner"], cs["hr"], cs["mgr"], cs["other"]
    meta = ok(owner.get("/api/meta/job-fields"))
    assert "title" in meta["required"] and "must_have_skills" in meta["required"] and len(meta["sections"]) >= 7

    # HR creates a draft; publishing needs the required fields
    draft = ok(hr.post("/api/jobs", json={"fields": {"title": "Senior Backend Engineer"}}))
    assert draft["status"] == "draft" and draft["fields"]["top_n"] == 7, "the company default shortlist size applies"
    assert "Department" in draft["missing_to_publish"]
    r = hr.patch(f"/api/jobs/{draft['id']}", json={"status": "open"})
    assert r.status_code == 400 and "Department" in r.text
    job = ok(hr.patch(f"/api/jobs/{draft['id']}", json={"fields": BACKEND_JD}))
    assert job["fields"]["must_have_skills"] == ["Java", "Spring Boot", "PostgreSQL"], job["fields"]["must_have_skills"]
    assert job["fields"]["nice_to_have_skills"] == ["Kafka", "Kubernetes"] and job["top_n"] == 2
    job = ok(hr.patch(f"/api/jobs/{job['id']}", json={"status": "open"}))
    assert job["status"] == "open" and job["published_at"]
    jid = job["id"]
    # remote roles don't need a location
    sales = ok(owner.post("/api/jobs", json={"status": "open", "fields": {
        "title": "Enterprise Account Executive", "department": "Sales", "employment_type": "Full-time", "workplace_type": "Remote",
        "experience_min": 5, "must_have_skills": ["b2b sales", "salesforce", "negotiation"]}}))
    assert sales["status"] == "open"
    assert mgr.post("/api/jobs", json={"fields": {"title": "x"}}).status_code == 403, "hiring managers can't create jobs"

    # JD views and PDF
    jd = ok(owner.get(f"/api/jobs/{jid}/jd"))
    assert jd["title"] == "Senior Backend Engineer" and any("Java" in it for sec in jd["sections"] for it in sec.get("items") or [])
    pdf = owner.get(f"/api/jobs/{jid}/jd.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert ok(owner.post(f"/api/jobs/{jid}/ai-write"))["responsibilities"]

    # the sales manager sees nothing until HR assigns them; editor can edit the JD but not publish
    assert ok(mgr.get("/api/jobs")) == []
    assert mgr.get(f"/api/jobs/{sales['id']}").status_code == 404
    mgr_uid = next(m["user_id"] for m in ok(owner.get("/api/team"))["members"] if m["role"] == "hiring_manager")
    assert ok(hr.post(f"/api/jobs/{sales['id']}/collaborators", json={"user_id": mgr_uid, "permission": "editor"}))["collaborators"][0]["permission"] == "editor"
    assert [j["id"] for j in ok(mgr.get("/api/jobs"))] == [sales["id"]]
    assert ok(mgr.get("/api/jobs"))[0]["permission"] == "edit"
    edited = ok(mgr.patch(f"/api/jobs/{sales['id']}", json={"fields": {"summary": "Own enterprise deals in India.", "nice_to_have_skills": ["hubspot"]}}))
    assert edited["fields"]["summary"] == "Own enterprise deals in India."
    assert mgr.patch(f"/api/jobs/{sales['id']}", json={"status": "closed"}).status_code == 403, "only HR changes the status"
    assert mgr.delete(f"/api/jobs/{sales['id']}").status_code == 403
    assert mgr.patch(f"/api/jobs/{jid}", json={"fields": {"summary": "x"}}).status_code == 404, "not assigned to the backend job"
    acts = ok(owner.get(f"/api/jobs/{sales['id']}/activity"))
    assert any(a["action"] == "job_edited" and a["user"] == "Sam Sales" for a in acts)
    assert other.get(f"/api/jobs/{jid}").status_code == 404, "other companies can't see the job"

    # bulk resume upload with parsing and de-duplication by email
    files = [("files", (n, t.encode(), "text/plain")) for n, t in RESUMES.items()] + [("files", ("bad.exe", b"MZ", "application/octet-stream"))]
    up = ok(hr.post("/api/candidates/upload", files=files))
    assert up["created"] == 4 and len(up["failed"]) == 1, up
    again = ok(hr.post("/api/candidates/upload", files=[("files", ("anita2.txt", RESUMES["anita.txt"].encode(), "text/plain"))]))
    assert again["updated"] == 1 and again["created"] == 0
    pool = ok(owner.get("/api/candidates"))
    assert pool["total"] == 4
    anita = next(c for c in pool["items"] if c["email"] == "anita.sharma@mail.test")
    assert anita["name"] == "Anita Sharma" and "Kafka" in anita["skills"] and anita["years"] == 6 and anita["notice_days"] == 30, anita
    assert ok(owner.get("/api/candidates?skill=salesforce"))["total"] == 1
    assert ok(owner.get("/api/candidates?min_years=5"))["total"] >= 2
    assert ok(other.get("/api/candidates"))["total"] == 0
    assert owner.get(f"/api/candidates/{anita['id']}/resume").status_code == 200

    # stage 1 matching: the right people rank first, and only the shortlist gets AI reports
    m = ok(owner.get(f"/api/jobs/{jid}/matches"))
    names = [r["candidate"]["name"] for r in m["items"]]
    assert names[0] == "Anita Sharma", names
    assert "Meera Iyer" not in names[:3], names
    assert m["top_n"] == 2 and m["ai_pending"] == 2
    sm = ok(owner.get(f"/api/jobs/{sales['id']}/matches"))
    assert sm["items"][0]["candidate"]["name"] == "Meera Iyer", [r["candidate"]["name"] for r in sm["items"]]
    rev = ok(owner.get(f"/api/candidates/{anita['id']}/jobs"))
    assert rev[0]["job_id"] == jid, "reverse view: Anita fits the backend job best"
    # AI reports: budget respected, then cached
    a1 = ok(owner.post("/api/match/ai-reports", json={"job_ids": [jid], "max": 1}))
    assert a1["generated"] == 1 and a1["skipped_over_budget"] == 1, a1
    a2 = ok(owner.post("/api/match/ai-reports", json={"job_ids": [jid]}))
    assert a2["generated"] == 1 and a2["pending_before"] == 1, a2
    a3 = ok(owner.post("/api/match/ai-reports", json={"job_ids": [jid]}))
    assert a3["generated"] == 0 and a3["pending_before"] == 0, "cached reports aren't regenerated"
    m = ok(owner.get(f"/api/jobs/{jid}/matches"))
    assert m["items"][0]["ai_report"]["verdict"] and m["ai_pending"] == 0
    assert mgr.post("/api/match/ai-reports", json={"job_ids": [sales["id"]]}).status_code == 403
    ov = ok(owner.get("/api/match/overview"))
    assert {j["id"] for j in ov["jobs"]} == {jid, sales["id"]} and ov["pool"] == 4
    assert ok(mgr.get("/api/match/overview"))["jobs"][0]["id"] == sales["id"] and len(ok(mgr.get("/api/match/overview"))["jobs"]) == 1

    # public careers page and applying
    org_slug = ok(owner.get("/api/auth/me"))["org"]["slug"]
    careers = ok(client().get(f"/api/public/orgs/{org_slug}"))
    assert {j["id"] for j in careers["jobs"]} == {jid, sales["id"]}
    pj = ok(client().get(f"/api/public/jobs/{jid}"))
    assert pj["questions"][0]["id"] == "auth" and "required_answer" not in pj["questions"][0], "the expected answer is never sent to candidates"
    assert client().get(f"/api/public/jobs/{draft['id']}x").status_code == 404
    cand = client()
    form = {"name": "Neha Gupta", "email": "neha@mail.test", "location": "Bengaluru", "consent": True, "answers": {"auth": "yes"}}
    res_file = ("neha.txt", b"Neha Gupta\nneha@mail.test\nBackend developer, 5 years: Java, Spring Boot, PostgreSQL, Kafka, AWS.", "text/plain")
    import json as _json
    assert cand.post(f"/api/public/jobs/{jid}/apply", data={"data": _json.dumps({**form, "answers": {}})}, files={"resume": res_file}).status_code == 400
    assert cand.post(f"/api/public/jobs/{jid}/apply", data={"data": _json.dumps({**form, "consent": False})}, files={"resume": res_file}).status_code == 400
    ok(cand.post(f"/api/public/jobs/{jid}/apply", data={"data": _json.dumps(form)}, files={"resume": res_file}))
    assert cand.post(f"/api/public/jobs/{jid}/apply", data={"data": _json.dumps(form)}, files={"resume": res_file}).status_code == 409
    # knockout: not authorised -> screened out, but still on file
    built = {"name": "Tom Builder", "email": "tom@mail.test", "consent": True, "answers": {"auth": "no"}, "skills": ["Java", "Spring Boot"],
             "experience": [{"title": "Developer", "company": "Acme", "start": "2020", "description": "Built APIs in Java"}], "total_experience_years": 4}
    ok(cand.post(f"/api/public/jobs/{jid}/apply", data={"data": _json.dumps(built)}))
    apps = ok(hr.get(f"/api/jobs/{jid}/applications"))["items"]
    by = {a["candidate"]["name"]: a for a in apps}
    assert by["Neha Gupta"]["stage"] == "applied" and by["Tom Builder"]["stage"] == "rejected" and by["Tom Builder"]["knockout_failed"]
    tom = by["Tom Builder"]["candidate"]
    assert tom["has_resume"], "a resume built in the form becomes a PDF"
    rp = hr.get(f"/api/candidates/{tom['id']}/resume")
    assert rp.status_code == 200 and rp.content.startswith(b"%PDF")
    ok(client().post(f"/api/public/orgs/{org_slug}/talent-pool", data={"data": _json.dumps(
        {"name": "Pooja Pool", "email": "pooja@mail.test", "consent": True, "summary": "Product designer, Figma, user research"})}))
    assert ok(owner.get("/api/candidates?source=talent_pool"))["total"] == 1
    parsed = ok(client().post("/api/public/parse-resume", files={"resume": ("a.txt", RESUMES["anita.txt"].encode(), "text/plain")}))
    assert parsed["email"] == "anita.sharma@mail.test" and "Java" in parsed["skills"]
    # the new applicant is matched straight away
    m = ok(owner.get(f"/api/jobs/{jid}/matches"))
    assert "Neha Gupta" in [r["candidate"]["name"] for r in m["items"][:3]]

    # pipeline: HR moves, a reviewer can only rate and comment
    neha_app = by["Neha Gupta"]["id"]
    ok(hr.patch(f"/api/applications/{neha_app}", json={"stage": "shortlisted"}))
    ok(hr.post(f"/api/jobs/{jid}/collaborators", json={"user_id": mgr_uid, "permission": "reviewer"}))
    assert ok(mgr.get(f"/api/jobs/{jid}"))["permission"] == "view"
    assert mgr.patch(f"/api/applications/{neha_app}", json={"stage": "offer"}).status_code == 403
    ok(mgr.patch(f"/api/applications/{neha_app}", json={"rating": 4, "notes": "Strong on Kafka"}))
    assert any(c["name"] == "Neha Gupta" for c in ok(mgr.get("/api/candidates"))["items"]), "managers see candidates of their jobs"
    added = ok(hr.post(f"/api/jobs/{jid}/applications", json={"candidate_id": anita["id"]}))
    assert added["stage"] == "shortlisted" and added["source"] == "sourced"
    det = ok(owner.get(f"/api/candidates/{anita['id']}"))
    assert det["applications"][0]["job_id"] == jid and det["best_jobs"][0]["ai_report"]

    dash = ok(owner.get("/api/dashboard"))
    assert dash["jobs"]["open"] == 2 and dash["candidates"] == 7 and dash["applications"] == 3 and dash["ai_reports"] == 2, dash
    assert ok(mgr.get("/api/dashboard"))["jobs"]["open"] == 2, "assigned to both jobs now"

    # duplicate, close, delete
    dup = ok(owner.post(f"/api/jobs/{jid}/duplicate"))
    assert ok(owner.get(f"/api/jobs/{dup['id']}"))["status"] == "draft"
    ok(owner.delete(f"/api/jobs/{dup['id']}"))
    ok(owner.patch(f"/api/jobs/{sales['id']}", json={"status": "closed"}))
    assert client().get(f"/api/public/jobs/{sales['id']}").status_code == 404

    # platform admin counts
    acme = next(o for o in ok(cs["founder"].get("/api/admin/orgs")) if o["slug"] == org_slug)
    assert acme["candidates"] == 7 and acme["jobs"] == 2, acme
    print("JOBS, CANDIDATES, APPLICATIONS, MATCHING: OK")
    return jid


def demo_and_import():
    c = client()
    signup(c, "demo@demo.test", "Demo Co")
    out = ok(c.post("/api/demo/seed"))
    assert out == {"jobs": 6, "candidates": 40}, out
    assert c.post("/api/demo/seed").status_code == 409
    jobs = ok(c.get("/api/jobs"))
    assert len(jobs) == 6 and all(j["status"] == "open" for j in jobs)
    ov = ok(c.get("/api/match/overview"))
    for j in ov["jobs"]:
        assert len(j["shortlist"]) == 5, (j["title"], j["shortlist"])
    # each sample job's shortlist is led by people from the matching profession
    be = next(j for j in ov["jobs"] if j["title"] == "Senior Backend Engineer")
    top = ok(c.get(f"/api/jobs/{be['id']}/matches"))["items"][0]["candidate"]
    assert {"Java", "Spring Boot"} <= set(top["skills"]), top
    sales = next(j for j in ov["jobs"] if j["title"] == "Enterprise Account Executive")
    top = ok(c.get(f"/api/jobs/{sales['id']}/matches"))["items"][0]["candidate"]
    assert "Salesforce" in top["skills"] or "B2B Sales" in top["skills"], top
    cand = ok(c.get("/api/candidates?limit=1"))["items"][0]
    r = c.get(f"/api/candidates/{cand['id']}/resume")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    d = ok(c.get("/api/dashboard"))
    assert d["applications"] == 24 and d["candidates"] == 40
    # JD import from a file
    jd = b"""Senior Data Engineer
We are looking for a data engineer to build our pipelines and own the warehouse used across the company for reporting and machine learning work.
Responsibilities:
- Build batch and streaming pipelines
- Own data quality checks
Requirements: 3-6 years with Python, SQL, Spark, Airflow and AWS."""
    f = ok(c.post("/api/jobs/parse-jd", files={"file": ("jd.txt", jd, "text/plain")}))["fields"]
    assert f["title"] == "Senior Data Engineer" and f["experience_min"] == 3 and f["experience_max"] == 6, f
    assert "Python" in f["must_have_skills"] + f["nice_to_have_skills"] and f["responsibilities"][0] == "Build batch and streaming pipelines", f
    cleared = ok(c.post("/api/demo/clear"))
    assert cleared == {"jobs": 6, "candidates": 40}
    assert ok(c.get("/api/jobs")) == [] and ok(c.get("/api/candidates"))["total"] == 0
    print("SAMPLE DATA + JD IMPORT: OK")


def api_key_org():
    """The ADMIN_KEY API needs an X-Org header for company endpoints."""
    import backend.auth as a
    old = a.ADMIN_KEY
    a.ADMIN_KEY = "k" * 20
    try:
        c = TestClient(app, headers={"X-Admin-Key": "k" * 20})
        assert c.get("/api/jobs").status_code == 400
        assert ok(c.get("/api/jobs", headers={"X-Org": "acme-corp"}))
    finally:
        a.ADMIN_KEY = old
    print("API KEY + X-Org: OK")


def scale():
    """Matching stays fast: 2,000 resumes x 120 jobs."""
    import random
    import time
    from backend import db, matching
    rnd = random.Random(7)
    pool = ["Java", "Spring Boot", "PostgreSQL", "Kafka", "React", "TypeScript", "Node.js", "Python", "Django", "AWS", "Docker", "Kubernetes",
            "Salesforce", "B2B Sales", "Negotiation", "Lead Generation", "Excel", "SQL", "Power BI", "Tableau", "Figma", "Recruitment", "Payroll",
            "Customer Support", "Zendesk", "Go", "Rust", "C++", "Machine Learning", "Pandas", "Accounting", "Tally", "GST", "SEO", "Content Writing"]
    cities = ["Bengaluru", "Mumbai", "Pune", "Delhi", "Hyderabad", "Chennai", "Kolkata", "Noida"]
    with db.session() as s:
        org = db.Org(name="Scale Co", slug="scale-co")
        s.add(org); s.flush()
        for i in range(2000):
            sk = rnd.sample(pool, rnd.randint(4, 9))
            text = f"Candidate {i}\ncand{i}@scale.test | {rnd.choice(cities)}\n{rnd.randint(0, 15)} years of experience. Skills: {', '.join(sk)}."
            s.add(db.Candidate(org_id=org.id, name=f"Candidate {i}", email=f"cand{i}@scale.test", location=rnd.choice(cities), resume_text=text,
                               parsed={"skills": sk, "years": rnd.randint(0, 15)}, source="bulk"))
        for k in range(120):
            sk = rnd.sample(pool, 4)
            s.add(db.Job(org_id=org.id, title=f"Role {k} {sk[0]} specialist", department="Engineering", status="open", top_n=5,
                         fields={"title": f"Role {k} {sk[0]} specialist", "must_have_skills": sk[:3], "nice_to_have_skills": sk[3:],
                                 "experience_min": rnd.randint(0, 6), "workplace_type": "Hybrid", "locations": [rnd.choice(cities)], "top_n": 5}))
        s.flush()
        t0 = time.time()
        stats = matching.run(s, org.id, {"skills": 45, "experience": 20, "relevance": 20, "location": 10, "logistics": 5}, 5)
        dt = time.time() - t0
        assert stats["jobs"] == 120 and stats["candidates"] == 2000
        assert stats["stored"] <= 120 * 30 + 10, "only the top K per job are stored"
        pend = matching.pending_reports(s, org.id, [j.id for j in s.query(db.Job).filter_by(org_id=org.id)])
        assert len(pend) <= 120 * 5, "AI reports only for each job's shortlist"
    print(f"SCALE: 2000 resumes x 120 jobs matched in {dt:.1f}s, {stats['stored']} matches stored, {len(pend)} AI reports would be needed: OK")
    assert dt < 60, f"matching too slow: {dt:.1f}s"


def main():
    cs = accounts()
    interviews_scoped(cs)
    hiring(cs)
    demo_and_import()
    api_key_org()
    scale()
    print("\nPLATFORM CHECKS PASSED")


if __name__ == "__main__":
    main()
