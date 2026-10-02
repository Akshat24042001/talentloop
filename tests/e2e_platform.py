"""Real-browser walk through the hiring app (Chromium + Playwright):  python -m tests.e2e_platform [screenshot_dir]

Sign-up, sample data, jobs, the JD editor, matches with AI reports, pipeline, candidates (bulk upload), team
invites with a hiring manager who edits only their job, settings, the careers page and applying, and the
platform admin console. Fails on any browser JS error or server traceback. Desktop and phone sizes."""
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from tests.e2e_browser import free_port_wait, pick

ROOT = Path(__file__).resolve().parent.parent
PORT = 8798
BASE = f"http://127.0.0.1:{PORT}"
SHOTS = Path(sys.argv[1]) if len(sys.argv) > 1 else None


def main():
    data = tempfile.mkdtemp()
    env = dict(os.environ, ALLOW_SAMPLE_DATA="1", LLM_MOCK="1", PUBLIC_URL="https://example.onrender.com", VAPI_PUBLIC_KEY="pk_test", ADMIN_KEY="", DATA_DIR=data,
               LOG_LEVEL="WARNING", PLATFORM_ADMIN_EMAILS="founder@e2e.test", DATABASE_URL=os.getenv("TEST_DATABASE_URL", ""), PYTHONUNBUFFERED="1")
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(PORT)], cwd=ROOT, env=env,
                           stdout=open(Path(data) / "server.log", "w"), stderr=subprocess.STDOUT)
    assert free_port_wait(PORT), "server did not start"
    errors: list[str] = []
    try:
        with sync_playwright() as p:
            exe = "/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else None
            browser = p.chromium.launch(executable_path=exe)

            def new(viewport=None):
                ctx = browser.new_context(viewport=viewport or {"width": 1440, "height": 900})
                pg = ctx.new_page()
                # Our confirmations are styled dialogs now (not window.confirm): accept them like the native ones were.
                pg.add_locator_handler(pg.locator("#ask-ok"), lambda: pg.locator("#ask-ok").click(), no_wait_after=True)
                pg.add_locator_handler(pg.get_by_role("button", name="Skip the tour"), lambda: pg.get_by_role("button", name="Skip the tour").click(), no_wait_after=True)
                pg.on("pageerror", lambda e: errors.append(f"{pg.url}: {e}"))
                pg.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text and errors.append(f"{pg.url}: console {m.text}"))
                return ctx, pg

            def shot(pg, name):
                if SHOTS:
                    SHOTS.mkdir(parents=True, exist_ok=True)
                    pg.wait_for_timeout(300)
                    pg.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)

            # ------------------------------------------------ landing, sign-up, sample data
            ctx, pg = new()
            pg.goto(BASE + "/")
            expect(pg.get_by_role("heading", level=1)).to_contain_text("shortlist")
            shot(pg, "01-landing")
            pg.get_by_role("link", name="Start free").first.click()
            pg.fill("#name", "Priya Owner"); pg.fill("#email", "priya@acme.test"); pg.fill("#company", "Acme Corp"); pg.fill("#password", "correct-horse-1")
            pg.get_by_role("button", name="Create workspace").click()
            expect(pg.get_by_text("Welcome to TalentLoop")).to_be_visible()
            shot(pg, "02-welcome")
            expect(pg.get_by_role("button", name="Load samples")).to_have_count(0)   # company owners don't load sample data
            assert pg.request.post(BASE + "/api/demo/seed").ok
            pg.reload()
            expect(pg.locator("text=Open jobs").locator("..").locator("..")).to_contain_text("6")
            shot(pg, "03-dashboard")

            # ------------------------------------------------ jobs, matches, AI reports
            pg.get_by_role("link", name="Jobs", exact=True).first.click()
            expect(pg.get_by_text("Senior Backend Engineer")).to_be_visible()
            shot(pg, "04-jobs")
            pg.get_by_text("Senior Backend Engineer").click()
            expect(pg.get_by_text("Shortlist · top 5")).to_be_visible(timeout=20000)
            pg.get_by_role("button", name="Write 5 AI reports").click()
            expect(pg.get_by_text("AI reports up to date")).to_be_visible(timeout=30000)
            expect(pg.get_by_text("AI match report").first).to_be_visible()
            shot(pg, "05-job-matches")
            pg.get_by_role("tab", name="Applicants").click()
            col = pg.get_by_role("region", name="AI CV screening")
            expect(col.locator("article").first).to_be_visible()
            shot(pg, "06-job-pipeline")
            col.locator("article button").first.click()
            pg.get_by_role("button", name="Pass AI CV screening").click()
            expect(pg.get_by_text(re.compile(r": (Passed|Moved|Selected|On hold|Started|Done)$"))).to_be_visible()
            pg.keyboard.press("Escape")
            pg.get_by_role("tab", name="Job description").click()
            expect(pg.get_by_role("heading", name="Senior Backend Engineer", level=2)).to_be_visible()
            shot(pg, "07-job-description")
            with pg.expect_popup() as pop:
                pg.get_by_role("link", name="Download JD as PDF").click()
            assert pop.value.url.endswith("/jd.pdf")
            pop.value.close()

            # ------------------------------------------------ JD editor: required fields block publishing
            pg.goto(BASE + "/app/jobs/new")
            expect(pg.get_by_role("heading", name="Role basics")).to_be_visible()
            pg.fill("#f-title", "Product Designer")
            pg.get_by_role("button", name="Publish").click()
            expect(pg.get_by_text("Fill in before publishing")).to_be_visible()
            shot(pg, "08-job-editor")
            pick(pg, "#f-department", "Design")
            pg.locator("nav button", has_text="Location & work model").click()          # the editor shows one section at a time
            pg.locator("#f-locations").fill("Bengaluru"); pg.locator("#f-locations").press("Enter")
            pg.locator("nav button", has_text="Requirements").click()
            pg.locator("#f-must_have_skills").fill("Figma"); pg.locator("#f-must_have_skills").press("Enter")
            pg.locator("#f-must_have_skills").fill("User Research"); pg.locator("#f-must_have_skills").press("Enter")
            pg.get_by_role("button", name="Publish").click()
            expect(pg.get_by_role("tab", name="Best matches")).to_be_visible(timeout=15000)
            expect(pg.get_by_text("Open", exact=True).first).to_be_visible()

            # ------------------------------------------------ candidates: upload, profile
            pg.goto(BASE + "/app/candidates")
            pg.get_by_role("button", name="Upload resumes").click()
            res = Path(data) / "zara.txt"
            res.write_text("Zara Khan\nzara.khan@example.com | Bengaluru\nProduct Designer, 4 years of experience.\nFigma, User Research, Prototyping, Design Systems.\nNotice period: 30 days")
            pg.set_input_files("input[type=file][multiple]", str(res))
            pg.get_by_role("button", name="Upload 1").click()
            expect(pg.get_by_text("1 added, 0 updated")).to_be_visible(timeout=20000)
            pg.keyboard.press("Escape")
            shot(pg, "09-candidates")
            pg.get_by_text("Zara Khan").first.click()
            expect(pg.get_by_text("Best-fit jobs")).to_be_visible()
            expect(pg.get_by_role("link", name="Product Designer")).to_be_visible()
            shot(pg, "10-candidate")

            # ------------------------------------------------ match center, settings
            pg.goto(BASE + "/app/matches")
            expect(pg.get_by_text("Candidates ranked")).to_be_visible(timeout=20000)
            shot(pg, "11-match-center")
            pg.goto(BASE + "/app/settings?tab=matching")
            expect(pg.get_by_text("Ranking weights")).to_be_visible()
            shot(pg, "12-settings")

            # ------------------------------------------------ team: a sales manager edits only the sales JD
            pg.goto(BASE + "/app/team")
            pg.fill("#inv-email", "sam@acme.test"); pick(pg, "#inv-role", "Hiring manager"); pg.fill("#inv-title", "Sales Manager")
            pg.get_by_role("button", name="Create invite link").click()
            link = pg.locator("span.break-all").inner_text(timeout=10000).strip()
            assert "/invite/" in link, link
            shot(pg, "13-team")
            pg.goto(BASE + "/app/jobs")
            pg.get_by_text("Enterprise Account Executive").click()
            pg.get_by_role("tab", name="Team access").click()
            ctx2, mgr = new()
            mgr.goto(BASE + link[link.index("/invite/"):])
            mgr.fill("#name", "Sam Sales"); mgr.fill("#password", "sam-password-1")
            mgr.get_by_role("button", name="Join Acme Corp").click()
            expect(mgr.get_by_text("Good")).to_be_visible(timeout=15000)
            mgr.goto(BASE + "/app/jobs")
            expect(mgr.get_by_text("No jobs assigned to you yet")).to_be_visible()
            pg.reload()
            pg.get_by_role("tab", name="Team access").click()
            pick(pg, pg.get_by_role("combobox").filter(has_text="Choose"), "Sam Sales (Sales Manager)")
            pg.get_by_role("button", name="Give access").click()
            expect(pg.get_by_text("Can edit JD")).to_be_visible()
            mgr.reload()
            expect(mgr.get_by_text("Enterprise Account Executive")).to_be_visible()
            expect(mgr.get_by_text("Senior Backend Engineer")).to_have_count(0)
            mgr.get_by_text("Enterprise Account Executive").click()
            mgr.get_by_role("link", name="Edit JD").click()
            mgr.locator("nav button", has_text="About the role").click()
            mgr.fill("#f-summary", "Win and grow our largest enterprise customers across India.")
            mgr.get_by_role("button", name="Save changes").click()
            expect(mgr.get_by_role("tab", name="Best matches")).to_be_visible(timeout=15000)
            assert mgr.get_by_role("button", name="Pause").count() == 0, "a hiring manager must not change the job status"
            shot(mgr, "14-manager-view")
            ctx2.close()

            # ------------------------------------------------ careers page and applying (no sign-in)
            ctx3, cand = new()
            cand.goto(BASE + "/careers/acme-corp")
            expect(cand.get_by_text("7 open roles")).to_be_visible(timeout=15000)
            shot(cand, "15-careers")
            cand.get_by_text("Customer Support Specialist").click()
            expect(cand.get_by_role("heading", name="Apply for Customer Support Specialist")).to_be_visible()
            cand.get_by_role("button", name="Build my resume").click()          # step 1 of 4: resume
            cand.fill("#ap-sum", "Support specialist with two years on chat and email.")
            cand.get_by_placeholder("Job title").fill("Support Associate"); cand.get_by_placeholder("Company").first.fill("Helio Health")
            cand.get_by_role("button", name="Next: About you").click()
            cand.get_by_role("button", name="Next: Experience").click()
            expect(cand.get_by_text("A few details are missing")).to_be_visible()                 # required fields are checked per step
            cand.fill("#ap-name", "Tara Fernandes"); cand.fill("#ap-email", "tara@example.com"); cand.fill("#ap-loc", "Hyderabad")
            expect(cand.get_by_text("Phone *")).to_be_visible()
            cand.fill("#ap-phone", "+91 98765 43210")
            cand.get_by_role("button", name="Next: Experience").click()
            cand.fill("#ap-notice", "30"); cand.fill("#ap-sal", "600000")
            cand.get_by_role("button", name="Next: Finish").click()
            pick(cand, "#q-auth", "Yes"); cand.fill("#q-notice", "30")
            cand.locator("input[type=checkbox][required]").check()
            shot(cand, "16-apply")
            cand.get_by_role("button", name="Submit application").click()
            expect(cand.get_by_text("Application sent")).to_be_visible(timeout=15000)
            ctx3.close()
            pg.goto(BASE + "/app/jobs")
            pg.get_by_text("Customer Support Specialist").click()
            pg.get_by_role("tab", name="Applicants").click()
            expect(pg.get_by_text("Tara Fernandes")).to_be_visible()

            # ------------------------------------------------ interview from a match: prefilled
            pg.goto(BASE + "/app/jobs")
            pg.get_by_text("Senior Backend Engineer").click()
            pg.get_by_role("link", name="Interview", exact=True).first.click()
            expect(pg.locator("#jd")).not_to_have_value("", timeout=15000)
            assert pg.locator("#cv").input_value(), "resume not prefilled"
            shot(pg, "17-interview-prefilled")

            # ------------------------------------------------ platform admin
            ctx4, fd = new()
            fd.goto(BASE + "/signup")
            fd.fill("#name", "Founder"); fd.fill("#email", "founder@e2e.test"); fd.fill("#company", "TalentLoop HQ"); fd.fill("#password", "founder-pass-1")
            fd.get_by_role("button", name="Create workspace").click()
            fd.get_by_role("link", name="Platform admin").click()
            expect(fd.get_by_text("Acme Corp")).to_be_visible(timeout=15000)
            row = fd.locator("tr", has_text="Acme Corp")
            expect(row).to_contain_text("priya@acme.test")
            shot(fd, "18-admin")
            ctx4.close()

            # ------------------------------------------------ phone size
            ctx5, ph = new({"width": 390, "height": 844})
            ph.goto(BASE + "/login")
            ph.fill("#email", "priya@acme.test"); ph.fill("#password", "correct-horse-1")
            ph.get_by_role("button", name="Sign in").click()
            expect(ph.get_by_role("button", name="Open menu")).to_be_visible(timeout=15000)
            shot(ph, "19-phone-dashboard")
            assert ph.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "horizontal scroll on phone"
            ph.get_by_role("button", name="Open menu").click()
            ph.get_by_role("link", name="Match center").click()
            expect(ph.get_by_text("Candidates ranked")).to_be_visible(timeout=15000)
            shot(ph, "20-phone-matches")
            ph.goto(BASE + "/careers/acme-corp")
            expect(ph.get_by_text("open roles")).to_be_visible()
            assert ph.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "horizontal scroll on careers page"
            # sign out
            ph.goto(BASE + "/app")
            ph.get_by_role("button", name="Open menu").click()
            ph.get_by_role("button", name="Sign out").click()
            expect(ph.get_by_role("heading", name="Welcome back")).to_be_visible(timeout=10000)
            ph.goto(BASE + "/app/jobs")
            expect(ph).to_have_url(f"{BASE}/login?next=%2Fapp%2Fjobs", timeout=10000)
            ctx5.close()
            browser.close()
    finally:
        srv.terminate()
        srv.wait(10)
    log = (Path(data) / "server.log").read_text()
    bad = [ln for ln in log.splitlines() if "Traceback" in ln or " ERROR " in ln]
    if bad:
        errors.append("server errors:\n" + log[-4000:])
    if errors:
        print("\nFAILURES:\n" + "\n".join(errors[:30]))
        sys.exit(1)
    print("\nPLATFORM BROWSER E2E PASSED")


if __name__ == "__main__":
    main()
