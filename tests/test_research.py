"""Public-web research on a candidate:  python -m tests.test_research
Fake GitHub, Gravatar, search and website servers stand in for the internet. A check passes when the problem does NOT happen:
wrong-person matches shown, personal social media or people-finder sites shown, the phone number searched, private
addresses fetched, or a lookup made when it shouldn't be."""
import asyncio, json, os, socket, tempfile, threading, time
os.environ.update({"LLM_MOCK": "0", "OPENROUTER_API_KEY": "sk-or-fake", "DATA_DIR": tempfile.mkdtemp(), "DATABASE_URL": "", "ALLOW_SAMPLE_DATA": "1",
                   "APP_ENV": "development", "SKIP_EMAIL_VERIFICATION": "1", "TAVILY_API_KEY": "tvly-fake", "SWEEP_EVERY_SEC": "0", "MESSAGES_EVERY_SEC": "0"})
import logging; logging.disable(logging.CRITICAL)
import hashlib
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.testclient import TestClient
from backend import db, media, research
from backend.main import app

RES = []
def check(name, bug_if, detail=""):
    RES.append((name, bool(bug_if))); print(("FAIL " if bug_if else "ok   ") + "no longer: " + name + (f"  [{detail}]" if detail and bug_if else ""))

# ---------------------------------------------------------------------------------- pure logic
nt = research.tokens("Asha K. Rao")
check("a name loses its initials", nt != {"asha", "rao"}, str(nt))
check("'Asha Rao' isn't found in 'Asha Rao | Senior Engineer'", not research.name_in(research.tokens("Asha Rao"), "Asha Rao | Senior Engineer"))
check("one name part counts as a full name", research.name_in(research.tokens("Asha"), "Asha Menon"))
check("accents break the match", not research.name_in(research.tokens("José Ramírez"), "Jose Ramirez"))
C = {"name": "Asha Rao", "phone": "+91 98765 43210", "email": "asha.rao@gmail.com", "company": "Meridian Bank", "location": "Pune, India", "skills": ["python", "java", "kafka"],
     "text": "Asha Rao. Backend engineer at Meridian Bank, Pune. Portfolio: https://asharao.dev  GitHub: github.com/asharao"}
pts, ev, conf = research.score_identity(C, {"name": "Asha Rao", "text": ""})
check("a name alone is enough to show a profile", research.classify(pts, conf) is not None, f"{pts}")
pts, ev, conf = research.score_identity(C, {"name": "Asha Rao", "company": "Meridian Bank", "location": "Pune", "text": ""})
check("name + employer + city isn't a possible match", research.classify(pts, conf) != "possible", f"{pts} {ev}")
pts, ev, conf = research.score_identity(C, {"name": "Someone", "email": "asha.rao@gmail.com"})
check("an email match isn't confirmed", research.classify(pts, conf) != "confirmed")
pts, ev, conf = research.score_identity(C, {"name": "A. Rao", "url": "https://asharao.dev/about"})
check("a page on the website written in the resume isn't confirmed", research.classify(pts, conf) != "confirmed", f"{pts} {ev}")
pts, ev, conf = research.score_identity(C, {"name": "Asha Rao", "company": "Another Corp", "location": "Delhi", "text": ""})
check("a namesake at another company in another city is shown", research.classify(pts, conf) is not None)
a = {"kind": "LinkedIn", "points": 6, "status": "possible"}; b = {"kind": "LinkedIn", "points": 6, "status": "possible"}
kept, notes = research.resolve_ties([a, b])
check("two equally good same-site profiles are both kept", len(kept) != 0 or not notes, str(kept))
kept, notes = research.resolve_ties([{"kind": "LinkedIn", "points": 9, "status": "possible"}, {"kind": "LinkedIn", "points": 6, "status": "possible"}])
check("a clear best profile is dropped", len(kept) != 1)
for url in ("https://www.facebook.com/asha.rao", "https://instagram.com/asha", "https://twitter.com/asha", "https://x.com/asha", "https://www.truecaller.com/search/in/9999",
            "https://www.spokeo.com/Asha-Rao", "https://rocketreach.co/asha"):
    check(f"personal social media or a people-finder is allowed: {url.split('/')[2]}", not research.excluded(url))
check("GitHub is excluded", research.excluded("https://github.com/asharao"))
check("LinkedIn is excluded", research.excluded("https://www.linkedin.com/in/asha"))
check("a one-word name is searched", research.search_queries({"name": "Asha", "email": "a@b.com", "skills": []}, False) != [])
q = research.search_queries({**C}, False)
check("the phone number is in a search query", any("98" in x for x in q) or False)
check("the email isn't searched in quotes", '"asha.rao@gmail.com"' not in q, str(q))
check("a LinkedIn query isn't made when the link is known", any("linkedin" in x for x in research.search_queries(C, True)))
check("a fake email is searched", any("example" in x for x in research.search_queries({**C, "email": "a@example.com"}, True)))
pi = research.page_info('<html><head><title> Asha &amp; Co </title><meta property="og:description" content="Backend engineer"></head><body><script>x()</script><p>Hello world</p></body></html>')
check("a page's title isn't read", pi["title"] != "Asha & Co", str(pi))
check("a page's description isn't read", pi["description"] != "Backend engineer")
check("script text leaks into the page text", "x()" in pi["text"])

# ---------------------------------------------------------------------------------- fake internet
SEEN = []          # (host, path, query, body)
gh_users = {
    "asharao": {"login": "asharao", "html_url": "https://github.com/asharao", "name": "Asha Rao", "company": "Meridian Bank", "location": "Pune", "blog": "https://asharao.dev",
                "bio": "Backend engineer", "email": "asha.rao@gmail.com", "followers": 41, "created_at": "2016-03-01T00:00:00Z", "public_repos": 3},
    "arao1": {"login": "arao1", "html_url": "https://github.com/arao1", "name": "Asha Rao", "company": "Other Co", "location": "Texas", "blog": "", "bio": "", "email": None, "followers": 2, "created_at": "2020-01-01T00:00:00Z", "public_repos": 1},
    "ashar": {"login": "ashar", "html_url": "https://github.com/ashar", "name": "Asha Rao", "company": "Someone", "location": "Oslo", "blog": "", "bio": "", "email": None, "followers": 0, "created_at": "2021-01-01T00:00:00Z", "public_repos": 0},
}
gh_repos = {"asharao": [{"name": "ledger", "html_url": "https://github.com/asharao/ledger", "description": "Event-sourced ledger", "language": "Java", "stargazers_count": 52, "fork": False, "pushed_at": "2026-09-01T00:00:00Z"},
                        {"name": "kafka-tools", "html_url": "https://github.com/asharao/kafka-tools", "description": "Kafka utilities", "language": "Python", "stargazers_count": 7, "fork": False, "pushed_at": "2026-08-01T00:00:00Z"},
                        {"name": "fork-of-x", "html_url": "u", "description": "", "language": "Go", "stargazers_count": 999, "fork": True, "pushed_at": "2026-09-02T00:00:00Z"}]}
fake = FastAPI()
@fake.middleware("http")
async def rec(request: Request, call_next):
    body = (await request.body()).decode("utf-8", "ignore")
    SEEN.append((request.url.path, str(request.url.query), body)); return await call_next(request)
@fake.get("/gh/users/{login}")
async def gh_user(login: str):
    return gh_users.get(login) or JSONResponse({"message": "Not Found"}, status_code=404)
@fake.get("/gh/users/{login}/repos")
async def gh_user_repos(login: str):
    return gh_repos.get(login, [])
MODE = {"search": "email_hit"}
@fake.get("/gh/search/users")
async def gh_search(q: str):
    if "in:email" in q:
        return {"items": [{"login": "asharao"}]} if "asha.rao@gmail.com" in q and MODE["search"] == "email_hit" else {"items": []}
    return {"items": [{"login": "arao1"}, {"login": "ashar"}]}
@fake.get("/gr/profiles/{h}")
async def gr(h: str):
    if h == hashlib.sha256(b"asha.rao@gmail.com").hexdigest():
        return {"display_name": "Asha Rao", "profile_url": "https://gravatar.com/asharao", "job_title": "Backend engineer", "company": "Meridian Bank",
                "verified_accounts": [{"service_label": "Mastodon", "url": "https://hachyderm.io/@asha"}, {"service_label": "Instagram", "url": "https://instagram.com/asha"}]}
    return JSONResponse({"error": "Not found"}, status_code=404)
@fake.post("/tv/search")
async def tavily(req: Request):
    b = await req.json()
    q = b["query"]
    if "site:linkedin.com/in" in q:
        return {"results": [{"title": "Asha Rao - Backend Engineer - Meridian Bank | LinkedIn", "url": "https://in.linkedin.com/in/asha-rao-pune", "content": "Pune, Maharashtra. Meridian Bank."},
                            {"title": "Asha Rao - Photographer | LinkedIn", "url": "https://www.linkedin.com/in/asha-rao-photo", "content": "Oslo. Photography."}]}
    if "asha.rao@gmail.com" in q:
        return {"results": [{"title": "Conference speakers", "url": "https://confs.example.org/speakers", "content": "Asha Rao (asha.rao@gmail.com) talks about Kafka at scale."},
                            {"title": "Asha Rao on Spokeo", "url": "https://www.spokeo.com/Asha-Rao", "content": "Asha Rao asha.rao@gmail.com age 34"}]}
    return {"results": [{"title": "Asha Rao | Facebook", "url": "https://facebook.com/asha.rao", "content": "Asha Rao Pune"},
                        {"title": "Asha Rao wins local race", "url": "https://news.example.org/race", "content": "Asha Rao, 29, finished first."}]}
@fake.get("/site/{p:path}")
async def site(p: str):
    return HTMLResponse('<html><head><title>Asha Rao - Portfolio</title><meta name="description" content="Backend engineer building ledgers"></head><body>Projects</body></html>')

def serve(a):
    port = (lambda s: (s.bind(("127.0.0.1", 0)), s.getsockname()[1], s.close())[1])(socket.socket())
    threading.Thread(target=uvicorn.Server(uvicorn.Config(a, port=port, log_level="error")).run, daemon=True).start(); return port
P = serve(fake); time.sleep(1.5)
research.GITHUB_API, research.GRAVATAR_API = f"http://127.0.0.1:{P}/gh", f"http://127.0.0.1:{P}/gr"
research.TAVILY_URL = f"http://127.0.0.1:{P}/tv/search"
LOOP = asyncio.new_event_loop()
def run(c, links, **kw):
    SEEN.clear()
    return LOOP.run_until_complete(research.lookup(c, links))

# fetch_page: the SSRF guard (real guard, no patching)
import httpx
async def fetch(u):
    async with httpx.AsyncClient(timeout=5) as cl:
        return await research.fetch_page(u, cl)
for u in (f"http://127.0.0.1:{P}/site/a", "https://localhost/", "https://127.0.0.1/", "https://169.254.169.254/latest/meta-data/", "https://10.0.0.5/admin", "https://[::1]/"):
    r = LOOP.run_until_complete(fetch(u))
    check(f"a private address is fetched: {u[:40]}", r.get("ok") or any("/site/" in x[0] for x in SEEN), str(r))
# then with the guard relaxed for the fake site only (http on loopback), the page is read
real_guard = media.public_https_url
media.public_https_url = lambda url: url.startswith("https://") or url.startswith(f"https://127.0.0.1:{P}")
async def fetch_fake():
    async with httpx.AsyncClient(timeout=5, transport=httpx.AsyncHTTPTransport()) as cl:
        orig = cl.stream
        def rewrite(m, u, **kw):                       # the fake site speaks http: point https://asharao.dev/... at it
            return orig(m, u.replace("https://asharao.dev", f"http://127.0.0.1:{P}/site"), **kw)
        cl.stream = rewrite
        return await research.fetch_page("https://asharao.dev/about", cl)
r = LOOP.run_until_complete(fetch_fake())
check("a live portfolio page isn't read", not r.get("ok") or r.get("title") != "Asha Rao - Portfolio" or "ledgers" not in r.get("description", ""), str(r))
media.public_https_url = real_guard

# the whole lookup
links = {"linkedin": [], "github": ["https://github.com/asharao"], "other": ["https://asharao.dev", "https://dead.example.net/me"]}
orig_fetch = research.fetch_page
async def fake_fetch(url, client):
    return {"url": url, "ok": False, "why": "could not be reached (ConnectError)"} if "dead" in url else {"url": url, "ok": True, "title": "Asha Rao - Portfolio", "description": "Backend engineer building ledgers", "text": ""}
research.fetch_page = fake_fetch
out = run(C, links)
by = {i["url"]: i for i in out["items"]}
gh = by.get("https://github.com/asharao")
check("the GitHub link in the resume isn't loaded", not gh or not gh.get("github"), str(list(by)))
check("GitHub forks count as the candidate's work", gh and any(r["name"] == "fork-of-x" for r in gh["github"]["top_repos"]))
check("GitHub's top repo isn't the most starred own repo", gh and gh["github"]["top_repos"][0]["name"] != "ledger")
check("a GitHub link in the resume isn't confirmed", gh and gh["status"] != "confirmed")
check("the dead link isn't flagged", not by["https://dead.example.net/me"].get("dead"))
check("the live portfolio isn't described", "ledgers" not in json.dumps(out["items"]))
check("Gravatar's verified accounts aren't listed", "https://hachyderm.io/@asha" not in by)
check("Instagram from Gravatar is shown", "https://instagram.com/asha" in by)
check("the candidate's email isn't looked up on Gravatar", not any("/gr/profiles/" in x[0] for x in SEEN))
check("the phone number was sent to a server", any("98765" in (x[0] + x[1] + x[2]) for x in SEEN))
li = [i for i in out["items"] if i["kind"] == "LinkedIn"]
check("a LinkedIn profile that agrees on name, employer and city isn't found by search", not li, str([(i['url'], i['status']) for i in out["items"]]))
check("the photographer with the same name is shown", any("asha-rao-photo" in i["url"] for i in out["items"]))
check("a conference page with the candidate's email isn't confirmed", not any(i["url"] == "https://confs.example.org/speakers" and i["status"] == "confirmed" for i in out["items"]))
check("a name-only news story is shown", any("news.example.org" in i["url"] for i in out["items"]))
check("Facebook is shown", any("facebook.com" in i["url"] for i in out["items"]))
check("a people-finder page is shown", any("spokeo" in i["url"] for i in out["items"]))
check("the search queries aren't recorded", not out["queries"])
check("the notes don't say the phone wasn't searched", not any("phone" in n.lower() for n in out["notes"]))
check("the GitHub name search ran although the profile link is known", any("fullname" in x[1] for x in SEEN))
check("every item has an id", any(not i.get("id") for i in out["items"]))
ev_ids = [i["id"] for i in out["items"]]
check("ids repeat", len(ev_ids) != len(set(ev_ids)))

# no link, no email match: a name-only GitHub namesake must not appear; a tie is reported, not guessed
MODE["search"] = "none"
c2 = {**C, "email": "nobody@gmail.com", "text": "Asha Rao. Engineer.", "company": ""}
out2 = run(c2, {"linkedin": [], "github": [], "other": []})
check("a same-name GitHub profile with nothing else in common is shown", any(i["kind"] == "GitHub" for i in out2["items"]), str([(i["url"], i["status"]) for i in out2["items"]]))
# email match: one profile with that public email, found without any link
MODE["search"] = "email_hit"
out3 = run({**C, "text": "Asha Rao. Engineer."}, {"linkedin": [], "github": [], "other": []})
g3 = [i for i in out3["items"] if i["kind"] == "GitHub"]
check("a profile whose public email matches isn't found and confirmed", not g3 or g3[0]["status"] != "confirmed", str(out3["items"]))
# without a search key
os.environ.pop("TAVILY_API_KEY")
out4 = run(C, links)
check("with no search key the report doesn't say web search is off", not any("Web search is not set up" in n for n in out4["notes"]))
check("with no search key a search was made", any("/tv/" in x[0] for x in SEEN))
os.environ["TAVILY_API_KEY"] = "tvly-fake"
# a search failure doesn't lose the other sources
async def boom(q, client): raise httpx.ConnectError("down")
orig_ws = research.web_search; research.web_search = boom
out5 = run(C, links)
check("a failing search loses the GitHub result", not any(i["kind"] == "GitHub" for i in out5["items"]))
check("a failing search isn't reported", not out5["errors"])
research.web_search = orig_ws

# gather(): cache, company switch, sample candidates
research.fetch_page = fake_fetch
c = TestClient(app)
assert c.post("/api/auth/signup", json={"email": "o@a.test", "password": "password-123", "name": "O", "company": "Acme"}).status_code == 200
assert c.post("/api/demo/seed").status_code == 200
with db.session() as s:
    cand = s.query(db.Candidate).first()
    cid = cand.id
    sample_before = cand.source
check("the demo candidate isn't treated as a sample", sample_before != "demo")
r = LOOP.run_until_complete(research.gather(cid))
check("a sample candidate is looked up", not r.get("skipped"), str(r)[:120])
with db.session() as s:
    cand = s.get(db.Candidate, cid)
    cand.source, cand.tags, cand.name, cand.email, cand.resume_text = "upload", [], "Asha Rao", "asha.rao@gmail.com", C["text"]
MODE["search"] = "email_hit"
SEEN.clear()
r1 = LOOP.run_until_complete(research.gather(cid)); n1 = len(SEEN)
r2 = LOOP.run_until_complete(research.gather(cid)); n2 = len(SEEN)
check("the lookup isn't saved on the candidate", "research" not in (db.session().__enter__().get(db.Candidate, cid).parsed or {}))
check("a second lookup within a week asks the internet again", n2 != n1, f"{n1} -> {n2}")
LOOP.run_until_complete(research.gather(cid, force=True)); n3 = len(SEEN)
check("refresh doesn't ask the internet again", n3 == n2, f"{n2} -> {n3}")
with db.session() as s:
    org = s.query(db.Org).first(); st = dict(org.settings or {}); st["public_lookup"] = False; org.settings = st
    cd = s.get(db.Candidate, cid); cd.parsed = {k: v for k, v in (cd.parsed or {}).items() if k != "research"}
SEEN.clear()
r4 = LOOP.run_until_complete(research.gather(cid))
check("the company switch doesn't stop the lookup", not r4.get("skipped") or SEEN, str(r4)[:120])
with db.session() as s:
    org = s.query(db.Org).first(); st = dict(org.settings or {}); st["public_lookup"] = True; org.settings = st
    cd = s.get(db.Candidate, cid); cd.tags = ["sample"]
r5 = LOOP.run_until_complete(research.gather(cid))
check("a candidate tagged sample is looked up", not r5.get("skipped"))

bad = [n for n, f in RES if f]
assert not bad, f"{len(bad)} research check(s) failed: {bad}"
print(f"RESEARCH CHECKS PASSED ({len(RES)})")

