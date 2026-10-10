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

# --- the AI reading: only what is in the document survives
async def fake(system, user, model, **kw):
    if "resume" in system.lower()[:40]:
        return {"name": "Name: Priya Sharma", "skills": ["Weaviate", "Quantum Gravity", "LangChain"], "location": "Mars", "total_experience_years": 99}
    return {"title": "Backend Wizard", "must_have_skills": ["Temporal", "Python", "Blockchain"], "nice_to_have_skills": ["Kubernetes"], "experience_min": 2}
llm.complete_json = fake; llm.MOCK = False; llm.FAST_MODEL = "m"
r = asyncio.run(extract_ai.read_resume(CV))
check("the AI invents a skill that is not in the resume", "Quantum Gravity" in r["skills"])
check("the AI skills are not added", "LangChain" not in r["skills"] or "Weaviate" not in r["skills"])
check("the AI name keeps its label", r["name_guess"] != "Priya Sharma")
check("the AI invents a location", r.get("location") == "Mars")
check("the AI invents experience", r.get("years") == 99)
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
