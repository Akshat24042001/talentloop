"""Public-web research on a candidate, for the AI match report.

What it looks at, and why each piece is trustworthy enough to show a recruiter:

1. Links the candidate gave (portfolio, blog, GitHub, Kaggle...): fetched safely (public https only), title and
   description read. LinkedIn is never fetched (sign-in wall, forbidden by its terms); its URL is just shown.
2. GitHub: the profile in the resume, else a profile whose PUBLIC email equals the candidate's email (that is strong
   evidence), else a profile with the same name that also agrees on at least two other things (employer, city,
   website listed in the resume, languages). Same-name-only matches are never shown.
3. Gravatar: the profile behind the candidate's email, if they made one (public, and the accounts on it were verified
   by the owner).
4. A web search, only when TAVILY_API_KEY or BRAVE_API_KEY is set: a few exact queries (name + employer, the email in
   quotes, "name site:linkedin.com/in"), every result scored against what the resume says. Results that don't agree on
   enough points are dropped; when several same-name profiles tie, none is shown (it says so instead of guessing).
5. A people-data provider when PEOPLE_DATA_API_KEY is set (existing).

Every item carries a status: "confirmed" (the candidate's own link, or matched on their email) or "possible" (agrees on
several details but could be a namesake: verify before relying on it), plus the evidence that produced it.

Deliberately NOT done, and shown to HR as not done: the phone number is not searched (numbers are reassigned and
searching them mostly finds other people); personal social media (Facebook, Instagram, TikTok, X, Reddit) and
people-finder sites (Spokeo, Truecaller, ...) are excluded: they add discrimination and privacy risk without telling
HR anything about the job. A company can turn the lookup off (Settings > Matching & AI); sample candidates are never
looked up.
"""
import asyncio
import hashlib
import html
import json
import logging
import os
import re
import time
import unicodedata
from urllib.parse import quote_plus, urljoin, urlparse

import httpx

from . import db, llm, media, skills

log = logging.getLogger("research")
VERSION = 2
TTL_SEC = 7 * 86400
UA = "TalentLoop-ProfileCheck/1.0"
PROFILE_HOSTS = {
    "github.com": "GitHub", "gitlab.com": "GitLab", "linkedin.com": "LinkedIn", "stackoverflow.com": "Stack Overflow",
    "stackexchange.com": "Stack Exchange", "kaggle.com": "Kaggle", "medium.com": "Medium", "dev.to": "DEV", "hashnode.dev": "Hashnode",
    "substack.com": "Substack", "huggingface.co": "Hugging Face", "leetcode.com": "LeetCode", "codeforces.com": "Codeforces",
    "hackerrank.com": "HackerRank", "codechef.com": "CodeChef", "behance.net": "Behance", "dribbble.com": "Dribbble",
    "orcid.org": "ORCID", "scholar.google.com": "Google Scholar", "researchgate.net": "ResearchGate", "semanticscholar.org": "Semantic Scholar",
    "arxiv.org": "arXiv", "npmjs.com": "npm", "pypi.org": "PyPI", "youtube.com": "YouTube", "speakerdeck.com": "Speaker Deck",
    "slideshare.net": "SlideShare", "producthunt.com": "Product Hunt", "wellfound.com": "Wellfound", "crunchbase.com": "Crunchbase",
}
# never searched, fetched or shown: personal social media and data-broker / people-finder sites
EXCLUDED = ("facebook.", "instagram.", "tiktok.", "twitter.", "x.com", "reddit.", "snapchat.", "spokeo.", "whitepages.", "truepeoplesearch.",
            "radaris.", "mylife.", "beenverified.", "intelius.", "peoplefinders.", "fastpeoplesearch.", "truecaller.", "zoominfo.", "rocketreach.",
            "contactout.", "signalhire.", "lusha.", "apollo.io", "pipl.", "sync.me", "getcontact", "social-searcher", "pimeyes", "clearbit.")


# ---------------------------------------------------------------------------
# small helpers (pure: unit-tested without a network)
# ---------------------------------------------------------------------------
def _fold(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(ch)).lower()


def tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", _fold(s)) if len(t) >= 2}


def fake_email(email: str) -> bool:
    d = (email or "").rsplit("@", 1)[-1].lower()
    return not d or d.split(".")[-1] in ("test", "example", "invalid", "localhost", "local") or d in ("example.com", "example.org", "example.net")


def host_of(url: str) -> str:
    try:
        h = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return h[4:] if h.startswith("www.") else h


def kind_of(url: str) -> str:
    h = host_of(url)
    for dom, label in PROFILE_HOSTS.items():
        if h == dom or h.endswith("." + dom):
            return label
    return "Website"


def excluded(url: str) -> bool:
    h = host_of(url)
    return any(x in h for x in EXCLUDED)


def norm_url(url: str) -> str:
    u = (url or "").strip().rstrip("/.,);")
    if u and not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    p = urlparse(u)
    return f"{p.scheme.lower()}://{host_of(u)}{p.path.rstrip('/')}" + (f"?{p.query}" if p.query and "linkedin" not in host_of(u) else "")


def name_in(name_tokens: set[str], text: str) -> bool:
    """Every part of the candidate's name (two or more parts) appears in the text."""
    return len(name_tokens) >= 2 and name_tokens <= tokens(text)


def in_resume(resume_folded: str, url: str) -> bool:
    """The address, or its own website, is written in the resume. On a shared platform (GitHub, Medium...) the profile's
    own path must be there; on any other site the host is enough, so every page of their website counts."""
    h = host_of(url if re.match(r"^https?://", url or "", re.I) else "https://" + (url or ""))
    if not h or "." not in h:
        return False
    seg = [x for x in urlparse(norm_url(url)).path.split("/") if x]
    platform = any(h == d or h.endswith("." + d) for d in PROFILE_HOSTS)
    needle = (h + "/" + seg[0]) if platform and seg else (None if platform else h)
    return bool(needle) and _fold(needle) in resume_folded


def score_identity(c: dict, found: dict) -> tuple[int, list[str], bool]:
    """How well a found profile or page agrees with the candidate. found: name, text (bio/snippet/title), url, email,
    location, company, site (their listed website), langs. Returns (points, evidence lines, confirmed)."""
    pts, ev, confirmed = 0, [], False
    nt = tokens(c["name"])
    if c.get("email") and c["email"] == (found.get("email") or "").strip().lower():
        pts += 6; confirmed = True; ev.append("the profile's public email is the candidate's email")
    if c.get("email") and c["email"] in (found.get("text") or "").lower():
        pts += 6; confirmed = True; ev.append("the candidate's email appears on the page")
    if name_in(nt, found.get("name") or "") or name_in(nt, found.get("text") or ""):
        pts += 3; ev.append("the full name matches")
    elif found.get("url") and len(nt) >= 2 and sum(1 for t in nt if t in _fold(found["url"])) >= 2:
        pts += 2; ev.append("the name is in the address")
    resume = _fold(c.get("text") or "").replace("https://", "").replace("http://", "").replace("www.", "")
    for url in (found.get("site") or "", found.get("url") or ""):
        if url and in_resume(resume, url):
            pts += 6; confirmed = True; ev.append("this address (or the site it is on) is written in the resume"); break
    comp = _fold(found.get("company") or "") + " " + _fold(found.get("text") or "")
    for co in {_fold(c.get("company") or "")}:
        words = [w for w in tokens(co) if w not in ("pvt", "ltd", "inc", "llc", "limited", "private", "technologies", "technology", "solutions", "the")]
        if words and all(w in comp for w in words[:2]):
            pts += 2; ev.append(f"employer matches ({c['company']})"); break
    loc = tokens(c.get("location") or "") - {"india", "state", "city"}
    if loc and loc & tokens(found.get("location") or ""):
        pts += 1; ev.append("same city")
    langs = {x.lower() for x in found.get("langs") or []}
    cs = {x.lower() for x in c.get("skills") or []}
    if len(langs & cs) >= 2:
        pts += 1; ev.append("works in the same languages: " + ", ".join(sorted(langs & cs)[:4]))
    return pts, ev, confirmed


def classify(pts: int, confirmed: bool) -> str | None:
    if confirmed:
        return "confirmed"
    return "possible" if pts >= 6 else None          # a name alone is 3; it takes the name plus real agreement


def resolve_ties(scored: list[dict]) -> tuple[list[dict], list[str]]:
    """Several profiles on the same site agreeing equally well: show none rather than guess. Returns (kept, notes)."""
    keep, notes = [], []
    by_kind: dict[str, list[dict]] = {}
    for it in scored:
        by_kind.setdefault(it["kind"], []).append(it)
    for kind, items in by_kind.items():
        items.sort(key=lambda x: -x["points"])
        sure = [x for x in items if x["status"] == "confirmed"]
        if sure:
            keep += sure
        elif len(items) == 1 or items[0]["points"] - items[1]["points"] >= 2:
            keep.append(items[0])
        else:
            notes.append(f"{len(items)} {kind} profiles fit the name equally well; none is shown because they can't be told apart. Ask for their {kind} link.")
    return keep, notes


def page_info(body: str) -> dict:
    title = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
    desc = None
    for m in re.finditer(r"<meta\s+[^>]*>", body, re.I):
        tag = m.group(0)
        if re.search(r"""(?:name|property)\s*=\s*["'](?:description|og:description)["']""", tag, re.I):
            c = re.search(r"""content\s*=\s*["'](.*?)["']""", tag, re.I | re.S)
            if c:
                desc = c.group(1); break
    clean = re.sub(r"(?is)<(script|style|noscript|svg|template)\b.*?</\1>", " ", body)
    text = html.unescape(re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", clean))).strip()
    return {"title": html.unescape(re.sub(r"\s+", " ", title.group(1))).strip()[:200] if title else "",
            "description": html.unescape(desc or "").strip()[:400], "text": text[:1500]}


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------
def search_provider() -> str:
    return "tavily" if os.getenv("TAVILY_API_KEY", "").strip() else "brave" if os.getenv("BRAVE_API_KEY", "").strip() else ""


GITHUB_API = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")
GRAVATAR_API = os.getenv("GRAVATAR_API_URL", "https://api.gravatar.com/v3").rstrip("/")
TAVILY_URL = os.getenv("TAVILY_API_URL", "https://api.tavily.com/search")
BRAVE_URL = os.getenv("BRAVE_API_URL", "https://api.search.brave.com/res/v1/web/search")


async def fetch_page(url: str, client: httpx.AsyncClient) -> dict:
    """GET a page the candidate linked to: https only, public addresses only (checked again on every redirect), small."""
    u = url if re.match(r"^https?://", url, re.I) else "https://" + url
    for _ in range(4):
        if u.lower().startswith("http://"):
            u = "https://" + u[7:]
        if not await asyncio.to_thread(media.public_https_url, u):
            return {"url": url, "ok": False, "why": "not a public https address"}
        try:
            async with client.stream("GET", u, headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.5"}, follow_redirects=False) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    u = urljoin(u, r.headers["location"]); continue
                if r.status_code >= 400:
                    return {"url": url, "ok": False, "status": r.status_code, "why": f"the page answered {r.status_code}"}
                if "html" not in r.headers.get("content-type", "") and "text" not in r.headers.get("content-type", ""):
                    return {"url": url, "final": u, "ok": True, "status": r.status_code, "title": "", "description": "", "text": ""}
                body = b""
                async for chunk in r.aiter_bytes():
                    body += chunk
                    if len(body) > 600_000:
                        break
        except (httpx.HTTPError, OSError) as e:
            return {"url": url, "ok": False, "why": f"could not be reached ({type(e).__name__})"}
        return {"url": url, "final": u, "ok": True, "status": 200, **page_info(body.decode("utf-8", "ignore"))}
    return {"url": url, "ok": False, "why": "too many redirects"}


def _gh_headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "User-Agent": UA}
    if os.getenv("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {os.getenv('GITHUB_TOKEN')}"
    return h


async def github_profile(login: str, client: httpx.AsyncClient) -> dict | None:
    r = await client.get(f"{GITHUB_API}/users/{login}", headers=_gh_headers())
    if r.status_code == 404:
        return None
    r.raise_for_status()
    u = r.json()
    rr = await client.get(f"{GITHUB_API}/users/{login}/repos", params={"per_page": 100, "sort": "pushed", "type": "owner"}, headers=_gh_headers())
    repos = [x for x in (rr.json() if rr.status_code == 200 else []) if isinstance(x, dict) and not x.get("fork")]
    langs: dict[str, int] = {}
    for x in repos:
        if x.get("language"):
            langs[x["language"].lower()] = langs.get(x["language"].lower(), 0) + 1
    top = sorted(repos, key=lambda x: (-(x.get("stargazers_count") or 0), x.get("pushed_at") or ""))[:5]
    return {"login": login, "url": u.get("html_url") or f"https://github.com/{login}", "name": u.get("name") or "", "company": u.get("company") or "",
            "location": u.get("location") or "", "site": u.get("blog") or "", "email": u.get("email") or "", "text": u.get("bio") or "",
            "followers": u.get("followers", 0), "since": (u.get("created_at") or "")[:10], "own_repos": len(repos),
            "langs": [k for k, _ in sorted(langs.items(), key=lambda kv: -kv[1])[:8]],
            "last_push": max((x.get("pushed_at") or "" for x in repos), default="")[:10],
            "top_repos": [{"name": x.get("name"), "url": x.get("html_url"), "about": (x.get("description") or "")[:140], "lang": x.get("language") or "",
                           "stars": x.get("stargazers_count") or 0} for x in top]}


async def github_by_email(email: str, client: httpx.AsyncClient) -> str | None:
    r = await client.get(f"{GITHUB_API}/search/users", params={"q": f"{email} in:email"}, headers=_gh_headers())
    if r.status_code != 200:
        return None
    items = r.json().get("items") or []
    return items[0]["login"] if len(items) == 1 else None          # exactly one profile with that public email


async def github_by_name(name: str, client: httpx.AsyncClient) -> list[str]:
    r = await client.get(f"{GITHUB_API}/search/users", params={"q": f'"{name}" in:fullname', "per_page": 5}, headers=_gh_headers())
    if r.status_code != 200:
        return []
    return [x["login"] for x in (r.json().get("items") or [])[:5] if x.get("login")]


async def gravatar(email: str, client: httpx.AsyncClient) -> dict | None:
    h = hashlib.sha256(email.strip().lower().encode()).hexdigest()
    r = await client.get(f"{GRAVATAR_API}/profiles/{h}", headers={"User-Agent": UA})
    if r.status_code != 200:
        return None
    p = r.json()
    accounts = [{"label": a.get("service_label") or a.get("service_type") or "", "url": a.get("url") or ""} for a in p.get("verified_accounts") or [] if a.get("url")]
    return {"name": p.get("display_name") or "", "url": p.get("profile_url") or "", "text": " ".join(filter(None, [p.get("job_title"), p.get("company"), p.get("description")])),
            "location": p.get("location") or "", "company": p.get("company") or "", "accounts": accounts[:8]}


async def web_search(query: str, client: httpx.AsyncClient) -> list[dict]:
    prov = search_provider()
    if prov == "tavily":
        key = os.getenv("TAVILY_API_KEY", "").strip()
        r = await client.post(TAVILY_URL, json={"api_key": key, "query": query, "max_results": 8, "search_depth": "basic", "include_answer": False},
                              headers={"Authorization": f"Bearer {key}", "User-Agent": UA})
        r.raise_for_status()
        return [{"title": x.get("title") or "", "url": x.get("url") or "", "snippet": (x.get("content") or "")[:500]} for x in r.json().get("results") or []]
    if prov == "brave":
        r = await client.get(BRAVE_URL, params={"q": query, "count": 8},
                             headers={"X-Subscription-Token": os.getenv("BRAVE_API_KEY", "").strip(), "Accept": "application/json", "User-Agent": UA})
        r.raise_for_status()
        return [{"title": x.get("title") or "", "url": x.get("url") or "", "snippet": html.unescape(re.sub(r"<[^>]+>", "", x.get("description") or ""))[:500]}
                for x in (r.json().get("web") or {}).get("results") or []]
    return []


def search_queries(c: dict, have_linkedin: bool) -> list[str]:
    q = []
    name = c["name"].strip()
    if len(tokens(name)) < 2:
        return q                                                    # one-word names can't be told apart on the open web
    anchor = c.get("company") or (c.get("headline") or "").split("|")[0].split(" at ")[-1].strip()
    q.append(f'"{name}" {anchor}'.strip())
    if c.get("email") and not fake_email(c["email"]):
        q.append(f'"{c["email"]}"')
    if not have_linkedin:
        q.append(f'"{name}" site:linkedin.com/in')
    top = [s for s in (c.get("skills") or [])[:2]]
    q.append(f'"{name}" ' + " ".join(top + [t for t in [c.get("location", "").split(",")[0].strip()] if t]))
    return list(dict.fromkeys(x for x in q if x))[:4]


# ---------------------------------------------------------------------------
# the whole lookup
# ---------------------------------------------------------------------------
def _item(kind: str, url: str, status: str, evidence: list[str], source: str, **extra) -> dict:
    return {"kind": kind, "url": url, "status": status, "evidence": evidence[:5], "source": source, **extra}


def _id(items: list[dict]) -> list[dict]:
    for i, it in enumerate(items, 1):
        it["id"] = f"W{i}"
    return items


async def lookup(c: dict, links: dict) -> dict:
    """c: the candidate as plain data (name, email, location, company, headline, text, skills). links: {linkedin, github, other}."""
    items: list[dict] = []
    notes: list[str] = []
    searched: list[str] = []
    used: dict = {"resume_links": 0, "github": False, "gravatar": False, "search": search_provider() or None, "people_data": False}
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        # 1. what the candidate gave us
        for u in links.get("linkedin") or []:
            items.append(_item("LinkedIn", u, "confirmed", ["the candidate's own link; LinkedIn pages can't be read automatically, open it to compare"], "resume"))
        gh_login = None
        for u in links.get("github") or []:
            m = re.search(r"github\.com/([A-Za-z0-9-]+)", u)
            if m:
                gh_login = gh_login or m.group(1)
        others = [u for u in links.get("other") or [] if not excluded(u)][:5]
        used["resume_links"] = len(others) + len(links.get("linkedin") or []) + (1 if gh_login else 0)

        async def one_page(u):
            try:
                return await fetch_page(u, client)
            except Exception as e:
                return {"url": u, "ok": False, "why": f"error ({type(e).__name__})"}
        pages = await asyncio.gather(*[one_page(u) for u in others])
        for p in pages:
            kind = kind_of(p["url"])
            if p.get("ok"):
                ev = ["the candidate's own link, and it is live"] + ([f"title: {p['title']}"] if p.get("title") else [])
                items.append(_item(kind, p["url"], "confirmed", ev, "resume", about=(p.get("description") or p.get("text") or "")[:300]))
            else:
                items.append(_item(kind, p["url"], "confirmed", [f"the candidate's own link, but {p.get('why', 'it did not load')}"], "resume", dead=True))

        # 2. GitHub: their link, else their email, else name plus real agreement
        gh = None
        try:
            if gh_login:
                gh = await github_profile(gh_login, client)
                if gh is None:
                    items.append(_item("GitHub", f"https://github.com/{gh_login}", "confirmed", ["the candidate's own link, but the profile doesn't exist"], "resume", dead=True))
                else:
                    pts, ev, _ = score_identity(c, gh)
                    items.append(_item("GitHub", gh["url"], "confirmed", ["the candidate's own link"] + ev, "resume", github=gh,
                                       name_differs=bool(gh["name"]) and not name_in(tokens(c["name"]), gh["name"]) and not (tokens(c["name"]) & tokens(gh["name"]))))
            elif c.get("email") and not fake_email(c["email"]):
                login = await github_by_email(c["email"], client)
                if login:
                    gh = await github_profile(login, client)
                    if gh:
                        pts, ev, conf = score_identity(c, gh)
                        items.append(_item("GitHub", gh["url"], "confirmed", ev or ["the profile's public email is the candidate's email"], "github search", github=gh))
            if gh is None and not gh_login and len(tokens(c["name"])) >= 2:
                cands = []
                for login in await github_by_name(c["name"], client):
                    p = await github_profile(login, client)
                    if p:
                        pts, ev, conf = score_identity(c, p)
                        st = classify(pts, conf)
                        if st:
                            cands.append(_item("GitHub", p["url"], st, ev, "github search", github=p, points=pts))
                kept, tie_notes = resolve_ties(cands)
                items += kept; notes += tie_notes
            used["github"] = any(i["kind"] == "GitHub" and i.get("github") for i in items)
        except Exception as e:
            errors.append(f"GitHub: {type(e).__name__}")
            log.warning("github lookup failed: %s", e)

        # 3. Gravatar (the person's own public profile for their email)
        if c.get("email"):
            try:
                g = await gravatar(c["email"], client)
                if g:
                    used["gravatar"] = True
                    pts, ev, conf = score_identity(c, g)
                    items.append(_item("Gravatar profile", g["url"], "confirmed", ["a public profile registered with the candidate's email"] + ev, "gravatar",
                                       about=g["text"][:300]))
                    for a in g["accounts"]:                          # accounts the owner verified themselves
                        if not excluded(a["url"]):
                            items.append(_item(kind_of(a["url"]) if kind_of(a["url"]) != "Website" else (a["label"] or "Website"), a["url"], "confirmed",
                                               ["verified by the owner on their Gravatar profile"], "gravatar"))
            except Exception as e:
                errors.append(f"Gravatar: {type(e).__name__}")

        # 4. web search, scored against the resume
        if search_provider():
            qs = search_queries(c, bool(links.get("linkedin")))
            results = await asyncio.gather(*[web_search(q, client) for q in qs], return_exceptions=True)
            scored = []
            for q, res in zip(qs, results):
                searched.append(q)
                if isinstance(res, Exception):
                    errors.append(f"search: {type(res).__name__}")
                    continue
                for r in res:
                    if not r["url"] or excluded(r["url"]):
                        continue
                    pts, ev, conf = score_identity(c, {"name": r["title"], "text": f"{r['title']} {r['snippet']}", "url": r["url"], "company": "", "location": r["snippet"]})
                    if kind_of(r["url"]) != "Website":
                        pts += 1
                    st = classify(pts, conf)
                    if st:
                        scored.append(_item(kind_of(r["url"]), r["url"], st, ev, "web search", about=r["snippet"][:300], points=pts, title=r["title"][:160]))
            have = {norm_url(i["url"]) for i in items}
            fresh = [s for s in scored if norm_url(s["url"]) not in have]
            by_url: dict[str, dict] = {}
            for s_ in fresh:
                by_url.setdefault(norm_url(s_["url"]), s_)
            kept, tie_notes = resolve_ties(list(by_url.values()))
            items += kept[:10]; notes += tie_notes
        else:
            notes.append("Web search is not set up (add TAVILY_API_KEY or BRAVE_API_KEY on the server): only the candidate's own links, GitHub and Gravatar were checked.")

    # 5. people-data provider (existing integration)
    try:
        from . import verify
        if os.getenv("PEOPLE_DATA_API_KEY", "").strip():
            ghost = db.Candidate(id="x", org_id="x", name=c["name"], email=c.get("email", ""), phone="", current_company=c.get("company", ""))
            _f, facts, info = await verify.people_data(ghost, c.get("text", ""), (links.get("linkedin") or [None])[0])
            if info.get("matched"):
                used["people_data"] = True
                if info.get("linkedin") and not any(i["kind"] == "LinkedIn" for i in items):
                    items.append(_item("LinkedIn", info["linkedin"] if info["linkedin"].startswith("http") else "https://" + info["linkedin"], "confirmed",
                                       [f"found by the people-data provider (match likelihood {info.get('likelihood')}/10)"], "people data"))
                notes += [x for x in facts]
    except Exception as e:
        errors.append(f"people data: {type(e).__name__}")

    notes += ["The phone number was not searched (numbers are reassigned and searches mostly find other people).",
              "Personal social media and people-finder sites are not searched or shown."]
    seen, out = set(), []
    for it in items:
        k = norm_url(it["url"])
        if k in seen:
            continue
        seen.add(k); out.append(it)
    order = {"confirmed": 0, "possible": 1}
    out.sort(key=lambda x: (order[x["status"]], x.get("dead", False)))
    return {"v": VERSION, "at": time.time(), "items": _id(out), "notes": notes, "queries": searched, "used": used, "errors": errors}


def _candidate_data(c: db.Candidate) -> dict:
    text = c.resume_text or ""
    return {"name": (c.name or "").strip(), "email": (c.email or "").strip().lower(), "location": c.location or "", "company": c.current_company or "",
            "headline": c.headline or "", "text": text[:20000], "skills": sorted(skills.extract(text))[:40]}


def skip_reason(c: db.Candidate, org_on: bool) -> str:
    if llm.MOCK:
        return "Public lookup is off in mock/demo mode."
    if not org_on:
        return "Public profile lookup is switched off for this company (Settings > Matching & AI)."
    if "sample" in (c.tags or []) or c.source == "demo":
        return "Sample candidates are never looked up."
    if len(tokens(c.name or "")) < 1:
        return "The candidate has no name to look up."
    return ""


async def gather(cand_id: str, force: bool = False) -> dict:
    """The candidate's public-web research (cached for a week in the candidate record)."""
    from .api_accounts import org_settings
    from . import verify
    with db.session() as s:
        c = s.get(db.Candidate, cand_id)
        if c is None:
            return {"v": VERSION, "items": [], "skipped": "Candidate not found."}
        org = s.get(db.Org, c.org_id)
        why = skip_reason(c, org_settings(org).get("public_lookup", True) is not False)
        cached = (c.parsed or {}).get("research")
        if why:
            return {"v": VERSION, "at": time.time(), "items": [], "skipped": why, "notes": [why], "used": {}}
        if cached and not force and cached.get("v") == VERSION and time.time() - cached.get("at", 0) < TTL_SEC:
            return cached
        data = _candidate_data(c)
        v = verify.ensure(s, c) or {}
        links = (v.get("links") or {"linkedin": [], "github": [], "other": []})
    try:
        res = await asyncio.wait_for(lookup(data, links), timeout=45)
    except asyncio.TimeoutError:
        res = {"v": VERSION, "at": time.time(), "items": [], "notes": ["The public lookup took too long and was skipped."], "errors": ["timeout"], "used": {}}
    with db.session() as s:
        c = s.get(db.Candidate, cand_id)
        if c is not None:
            c.parsed = {**(c.parsed or {}), "research": res}
    return res


def brief(res: dict | None, limit: int = 12) -> list[dict]:
    """The research as the AI sees it: id, kind, status, url, evidence, a short excerpt. Nothing else."""
    out = []
    for it in (res or {}).get("items", [])[:limit]:
        g = it.get("github") or {}
        extra = ""
        if g:
            extra = (f"{g.get('own_repos')} own repos, languages {', '.join(g.get('langs') or [])}, last push {g.get('last_push')}, followers {g.get('followers')}"
                     + ("; top repos: " + "; ".join(f"{r['name']} ({r['lang']}, {r['stars']} stars): {r['about']}" for r in g.get("top_repos", [])[:3]) if g.get("top_repos") else "")
                     + (f"; bio: {g.get('text')}" if g.get("text") else ""))
        out.append({"id": it["id"], "kind": it["kind"], "status": it["status"], "url": it["url"], "dead": bool(it.get("dead")),
                    "why": "; ".join(it.get("evidence") or []), "excerpt": (extra or it.get("about") or "")[:500]})
    return out
