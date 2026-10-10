"""Resume and job description reading:  python -m tests.test_parsing
Names without labels, skills outside the dictionary, required vs preferred skills, and an AI answer that invents things.
A check passes when the problem does NOT happen."""
import asyncio, json, os, tempfile
os.environ.update({"LLM_MOCK": "0", "OPENROUTER_API_KEY": "sk-or-fake", "DATA_DIR": tempfile.mkdtemp(), "DATABASE_URL": os.getenv("TEST_DATABASE_URL", "")})
from backend import extract_ai, jdparse, llm, resumes, skills

RES = []
def check(name, bug_if, detail=""):
    RES.append((name, bool(bug_if))); print(("FAIL " if bug_if else "ok   ") + "no longer: " + name + (f"  [{detail}]" if detail and bug_if else ""))

# --- names
for text, email, want in [
    ("Name: John Doe\nEmail: j@x.com", "j@x.com", "John Doe"),
    ("RESUME OF PRIYA SHARMA\n+91 98765 43210", "p@x.com", "Priya Sharma"),
    ("Curriculum Vitae\nDr. Priya Sharma, MBA | Pune", "x@y.com", "Priya Sharma"),
    ("RESUME\nSOFTWARE ENGINEER\nRahul Verma\nrahul.verma@gmail.com", "rahul.verma@gmail.com", "Rahul Verma"),
    ("Full Name - ARJUN K. NAIR", "a@b.com", "Arjun K. Nair"),
    ("Senior Data Analyst\nPhone: 9876543210", "amit.shah92@gmail.com", "Amit Shah"),
    ("Candidate Name : Aarti Joshi (Ms.)", "q@q.com", "Aarti Joshi"),
    ("Name:\nMeera Iyer", "m@x.com", "Meera Iyer"),
]:
    got = resumes._guess_name(text, email)
    check(f"the name is read as {got!r} instead of {want!r}", got != want)
for bad in ["Sales Manager", "Page 1", "Contact Details", "Curriculum Vitae"]:
    check(f"{bad!r} is taken for a person's name", resumes.clean_name(bad) != "")
check("a typed 'Name: X' keeps its label", resumes.safe_name("Name: Kiran Rao") != "Kiran Rao")
check("a single-word name is thrown away", resumes.safe_name("Name: Madonna") != "Madonna")

# --- skills outside the dictionary
CV = """Priya Sharma
TECHNICAL SKILLS
Languages: Python, Java, Rust (basic)
Frameworks: Django, FastAPI, LangChain
Vector databases - Pinecone, Weaviate

EXPERIENCE
Key Skills: Prompt engineering; Figma
"""
got = set(skills.extract_all(CV))
for s in ["LangChain", "Pinecone", "Weaviate", "Prompt engineering", "Rust", "Figma", "Python"]:
    check(f"the skill {s} is missing from the resume", s not in got)
check("a level in brackets ends up in a skill", any("basic" in x.lower() or "(" in x for x in got))
check("parse() leaves out skills outside the dictionary", "Weaviate" not in resumes.parse(CV)["skills"])

# --- job description
JD = """Job Title: Senior Backend Engineer (Hybrid)
Acme Technologies Pvt Ltd | Bengaluru

About the role
We are building a payments platform used by millions of merchants and need an engineer to own its core services end to end.

Key Responsibilities
- Design and build scalable REST APIs
- Own the on-call rotation and
  improve reliability

Requirements
- 5-8 years of experience in backend development
- Strong in Python, Django and PostgreSQL
- Experience with Kafka and Redis

Nice to have
- Kubernetes, Terraform
"""
f = jdparse.parse(JD)
check("the job title keeps its label or '(Hybrid)'", f.get("title") != "Senior Backend Engineer", f.get("title"))
check("Python is not a must-have", "Python" not in f.get("must_have_skills", []))
check("Kubernetes is not a nice-to-have", "Kubernetes" not in f.get("nice_to_have_skills", []))
check("a nice-to-have sits in the must-haves", "Terraform" in f.get("must_have_skills", []))
check("experience 5-8 years is read wrongly", (f.get("experience_min"), f.get("experience_max")) != (5, 8))
check("a wrapped bullet is split in two", len(f.get("responsibilities", [])) != 2)
check("the summary is empty", not f.get("summary"))
check("the skills are listed alphabetically instead of as written", f.get("must_have_skills", [])[:1] != ["Python"])


# --- experience worked out from the dates, gaps, years per skill, soft skills shown by actions
H = """Rahul Verma
EXPERIENCE
Senior Engineer | Zeta | Mar 2022 - Present
- Led a team of 5 engineers, mentored 2 interns; delivered payments API with Kafka ahead of deadlines
Software Engineer, Infosys (06/2018 - 08/2021)
- Built Spring Boot services, presented designs to stakeholders, resolved production incidents

EDUCATION
B.Tech Computer Science, VIT University  2014 - 2018
"""
p = resumes.parse(H)
check("experience is not worked out from the job dates", p["years_source"] != "dates" or not p["years"] or p["years"] < 7)
check("the degree's years are counted as a job", any(j["start"].startswith("2014") for j in p["jobs"]))
check("the 7-month gap between jobs is not highlighted", not any(g["months"] == 7 and g["kind"] == "between jobs" for g in p["gaps"]), str(p["gaps"]))
check("Kafka's years are not tied to the job that used it", p["skill_years"].get("Kafka", 0) < 4, str(p["skill_years"]))
check("Spring Boot gets years from a job that did not use it", p["skill_years"].get("Spring Boot", 0) > 3.5)
for s in ["Leadership", "Mentoring", "Time Management", "Communication", "Stakeholder Management", "Problem Solving"]:
    check(f"the soft skill {s} shown by an action is missed", s not in p["skills"])
jd_soft = jdparse.parse("Data Analyst\nRequirements\n- SQL and Excel\n- Excellent communication skills\n- Work with cross-functional teams\n")
check("JD soft skills are not in their own field", "Communication" not in jd_soft.get("soft_skills", []) or "Teamwork" not in jd_soft.get("soft_skills", []))
check("a soft skill sits in the JD must-haves", "Communication" in jd_soft.get("must_have_skills", []))

# --- the AI reading: only what is in the document survives
async def fake(system, user, model, **kw):
    if "resume" in system.lower()[:80]:
        return {"name": "Name: Priya Sharma", "skills": ["Weaviate", "Quantum Gravity", "LangChain", {"name": "Leadership", "type": "soft", "evidence": "led a huge team"}],
                "location": "Mars", "stated_experience_years": 99,
                "experience": [{"title": "CEO", "company": "Fake", "dates_text": "2001 - 2009", "start": "2001-01", "end": "2009-01"}]}
    return {"title": "Backend Wizard", "must_have_skills": ["Temporal", "Python", "Blockchain"], "nice_to_have_skills": ["Kubernetes"], "experience_min": 2}
llm.complete_json = fake; llm.MOCK = False; llm.FAST_MODEL = "m"
r = asyncio.run(extract_ai.read_resume(CV))
check("the AI invents a skill that is not in the resume", "Quantum Gravity" in r["skills"])
check("the AI skills are not added", "LangChain" not in r["skills"] or "Weaviate" not in r["skills"])
check("the AI name keeps its label", r["name_guess"] != "Priya Sharma")
check("the AI invents a location", r.get("location") == "Mars")
check("the AI invents experience", r.get("years") == 99)
check("the AI invents a soft skill without a real quote", "Leadership" in r["skills"])
check("the AI invents a job", any("Fake" in j["title"] for j in r.get("jobs", [])))
j = asyncio.run(extract_ai.read_jd(JD + "\n- Working knowledge of Temporal workflows\n"))
check("the AI invents a JD title", j["fields"]["title"] == "Backend Wizard")
check("the AI invents a JD skill", "Blockchain" in j["fields"].get("must_have_skills", []))
check("a real JD skill outside the dictionary is lost", "Temporal" not in j["fields"].get("must_have_skills", []))
async def boom(*a, **k): raise RuntimeError("down")
llm.complete_json = boom
j = asyncio.run(extract_ai.read_jd(JD))
check("a failing AI breaks the JD upload", j["read_by"] != "rules" or "Python" not in j["fields"].get("must_have_skills", []))

bad = [n for n, b in RES if b]
print(f"\n{len(RES) - len(bad)}/{len(RES)} ok"); raise SystemExit(1 if bad else 0)
