"""Real-browser walk through hiring flows (Chromium + Playwright, fake camera):  python -m tests.e2e_flows [screenshot_dir]

HR loads the starter question bank, applies the campus template in the flow builder, adds a round and a campus
drive. A student registers with a live photo, takes the proctored test, records a video introduction; a manager
decides from the no-login link; the student books a human interview; the interviewer gives feedback. HR uses the
pipeline board and drawer, and every new page loads. Fails on any browser JS error or server traceback."""
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
PORT = 8799
BASE = f"http://127.0.0.1:{PORT}"
SHOTS = Path(sys.argv[1]) if len(sys.argv) > 1 else None


def main():
    data = tempfile.mkdtemp()
    env = dict(os.environ, ALLOW_SAMPLE_DATA="1", LLM_MOCK="1", PUBLIC_URL=BASE, APP_URL=BASE, VAPI_PUBLIC_KEY="pk_test", ADMIN_KEY="", DATA_DIR=data, LOG_LEVEL="WARNING",
               PLATFORM_ADMIN_EMAILS="", DATABASE_URL=os.getenv("TEST_DATABASE_URL", ""), PYTHONUNBUFFERED="1")
    log = Path(data) / "server.log"
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(PORT)], cwd=ROOT, env=env,
                           stdout=open(log, "w"), stderr=subprocess.STDOUT)
    assert free_port_wait(PORT), "server did not start"
    errors: list[str] = []
    try:
        with sync_playwright() as p:
            exe = "/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else None
            browser = p.chromium.launch(executable_path=exe, args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])

            def new(viewport=None):
                ctx = browser.new_context(viewport=viewport or {"width": 1440, "height": 900}, permissions=["camera", "microphone"])
                pg = ctx.new_page()
                # Our confirmations are styled dialogs now (not window.confirm): accept them like the native ones were.
                pg.add_locator_handler(pg.locator("#ask-ok"), lambda: pg.locator("#ask-ok").click(), no_wait_after=True)
                pg.add_locator_handler(pg.get_by_role("button", name="Skip the tour"), lambda: pg.get_by_role("button", name="Skip the tour").click(), no_wait_after=True)
                pg.on("pageerror", lambda e: errors.append(f"{pg.url}: {e}"))
                pg.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text and errors.append(f"{pg.url}: console {m.text}"))
                pg.on("dialog", lambda d: d.accept())
                return ctx, pg

            def shot(pg, name):
                if SHOTS:
                    SHOTS.mkdir(parents=True, exist_ok=True)
                    pg.wait_for_timeout(300)
                    pg.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)

            def api(pg, path, method="get", **kw):
                r = getattr(pg.request, method)(BASE + path, **kw)
                assert r.ok, f"{method} {path}: {r.status} {r.text()[:300]}"
                return r.json()

            # ------------------------------------------------ HR: workspace, samples, question bank
            ctx, hr = new()
            hr.goto(BASE + "/signup")
            hr.fill("#name", "Hema HR"); hr.fill("#email", "hema@flows.test"); hr.fill("#company", "Flow Co"); hr.fill("#password", "correct-horse-1")
            hr.get_by_role("button", name="Create workspace").click()
            expect(hr.get_by_text("Welcome to TalentLoop")).to_be_visible()
            assert hr.request.post(BASE + "/api/demo/seed").ok      # sample data: platform-admin tool, loaded via the API here
            hr.reload()
            hr.get_by_role("link", name="Question bank").click()
            hr.get_by_role("button", name="Load about 60 starter questions").click()
            expect(hr.get_by_text("Quantitative aptitude").first).to_be_visible(timeout=15000)
            shot(hr, "f01-question-bank")
            hr.get_by_role("button", name="Draft with AI").click()
            pick(hr, "#dq-j", "Customer Support Specialist")                      # suggest from a job's JD
            hr.get_by_role("button", name="Draft", exact=True).click()
            expect(hr.get_by_text("Keep draft 1")).to_be_visible()
            hr.get_by_role("button", name="Save 5 question(s)").click()
            expect(hr.get_by_text("5 question(s) saved")).to_be_visible()

            # ------------------------------------------------ flow builder: campus template, add a round, save
            job = next(j for j in api(hr, "/api/jobs") if j["title"] == "Customer Support Specialist")
            hr.goto(f"{BASE}/app/jobs/{job['ref']}?tab=flow")
            expect(hr.get_by_text("Hiring flow").first).to_be_visible()
            hr.get_by_role("button", name="Templates").click()
            hr.get_by_role("button", name="Use Campus / fresher").click()
            expect(hr.get_by_text("Template applied")).to_be_visible()
            expect(hr.get_by_role("list", name="Rounds").get_by_text("Aptitude and domain test")).to_be_visible()
            hr.get_by_role("button", name="Practical task").click()                  # palette: add a round
            expect(hr.get_by_text("Unsaved changes")).to_be_visible()
            hr.get_by_role("button", name="Remove round").last.click()               # and take it out again
            hr.get_by_role("list", name="Rounds").get_by_text("Aptitude and domain test").click()
            hr.fill("#t-oc", "0")                                                    # anyone who finishes passes the test
            sec_minutes = hr.locator("label:has-text('Minutes') input")
            for i in range(sec_minutes.count()):
                sec_minutes.nth(i).fill("5")
            hr.get_by_role("button", name="Save flow").click()
            expect(hr.get_by_text("Flow saved")).to_be_visible()
            shot(hr, "f02-flow-builder")
            flow = api(hr, f"/api/jobs/{job['id']}/flow")["rounds"]
            test_round = next(r for r in flow if r["type"] == "test")
            assert test_round["config"]["overall_cutoff"] == 0 and all(s["minutes"] == 5 for s in test_round["config"]["sections"]), test_round
            for sct in test_round["config"]["sections"]:
                sct["cutoff"] = 0
            test_round["pass_rule"] = {"mode": "min_score", "value": 0}
            api(hr, f"/api/jobs/{job['id']}/flow", "put", data={"rounds": flow})

            # ------------------------------------------------ campus drive with QR code
            hr.get_by_role("tab", name="Campus drives").click()
            hr.get_by_role("button", name="New drive").click()
            hr.fill("#dr-c", "E2E Institute of Technology")
            hr.get_by_role("button", name="Create drive").click()
            expect(hr.get_by_text("E2E Institute of Technology")).to_be_visible()
            hr.get_by_role("button", name="QR code").click()
            expect(hr.get_by_alt_text("QR code for", exact=False)).to_be_visible()
            shot(hr, "f03-drive-qr")
            hr.keyboard.press("Escape")
            drive = api(hr, f"/api/jobs/{job['id']}/drives")[0]

            # ------------------------------------------------ student: register with a live photo, take the test
            ctx2, st = new({"width": 390, "height": 844})
            st.goto(drive["link"])
            expect(st.get_by_role("heading", name="Customer Support Specialist")).to_be_visible()
            st.fill("#dv-n", "Sana Student"); st.fill("#dv-e", "sana@student.test"); st.fill("#dv-p", "+91 98000 11111")
            st.fill("#dv-d", "BCA"); st.fill("#dv-y", "2026")
            for sel in st.locator("button[id^=dq-]").all():
                pick(st, sel, "Yes")
            for inp in st.locator("input[id^=dq-]").all():
                inp.fill("30")
            st.get_by_role("button", name="Open camera").click()
            st.get_by_role("button", name="Take photo").click()
            expect(st.get_by_alt_text("Your photo")).to_be_visible()
            st.locator("input[type=checkbox][required]").check()
            shot(st, "f04-drive-register")
            st.get_by_role("button", name="Register").click()
            expect(st.get_by_text("You're registered")).to_be_visible(timeout=20000)
            assert st.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "horizontal scroll on phone"
            st.get_by_role("link", name="Start the test").click()
            expect(st.get_by_text("I agree to take this test on my own")).to_be_visible()
            st.locator("input[type=checkbox]").first.check()
            shot(st, "f05-test-intro")
            st.get_by_role("button", name="Start the test").click()
            for _ in range(5):
                expect(st.get_by_text("Section", exact=False).first).to_be_visible(timeout=15000)
                st.locator("input[type=radio]").first.check()
                expect(st.get_by_text("Saved", exact=True)).to_be_visible()
                last = st.get_by_role("button", name="Submit the test").count() > 0
                st.get_by_role("button", name="Submit the test" if last else "Next section").click()
                st.get_by_role("button", name="Submit" if last else "Next section").last.click()
                if last:
                    break
            expect(st.get_by_text("Your test is submitted")).to_be_visible(timeout=15000)
            shot(st, "f06-test-done")

            app = next(a for a in api(hr, f"/api/jobs/{job['id']}/pipeline")["items"] if a["candidate"]["name"] == "Sana Student")
            det = api(hr, f"/api/applications/{app['id']}")
            tr = next(r for r in det["rounds"] if r["round"]["type"] == "test")
            assert tr["result"]["status"] in ("passed", "submitted"), tr["result"]
            assert tr["result"]["integrity"].get("start_photo"), "start photo saved"

            # ------------------------------------------------ HR: board and drawer with test sections and photos
            hr.goto(f"{BASE}/app/jobs/{job['ref']}?tab=pipeline")
            expect(hr.get_by_text("Sana Student")).to_be_visible()
            hr.get_by_role("button", name="List").click()
            expect(hr.get_by_role("table")).to_contain_text("E2E Institute of Technology")
            boxes = hr.get_by_role("table").locator("tbody input[type=checkbox]")
            boxes.nth(0).check(); boxes.nth(1).check()
            hr.get_by_role("button", name="Compare").click()
            expect(hr.get_by_role("dialog").get_by_text("Match score")).to_be_visible()
            shot(hr, "f06b-compare")
            hr.keyboard.press("Escape")
            hr.get_by_role("button", name="Clear selection").click()
            hr.get_by_role("button", name="Board").click()
            hr.get_by_text("Sana Student").click()
            expect(hr.get_by_text("Sections", exact=True)).to_be_visible()
            expect(hr.get_by_alt_text("At the start")).to_be_visible()
            expect(hr.get_by_alt_text("Registration photo")).to_be_visible()
            shot(hr, "f07-drawer-test")
            pick(hr, hr.get_by_role("combobox", name="Move to round"), "Video introduction")
            expect(hr.get_by_text(re.compile(r": (Passed|Moved|Selected|On hold|Started|Done)$"))).to_be_visible()
            hr.keyboard.press("Escape")

            # ------------------------------------------------ student: video introduction with the fake camera
            det = api(hr, f"/api/applications/{app['id']}")
            vr = next(r for r in det["rounds"] if r["round"]["type"] == "video_intro")
            st.goto(vr["result"]["candidate_link"])
            expect(st.get_by_text("What to talk about")).to_be_visible()
            st.locator("input[type=checkbox]").first.check()
            st.get_by_role("button", name="Get ready").click()
            st.get_by_role("button", name="Start now").click()
            expect(st.get_by_role("button", name="Stop recording")).to_be_visible()
            st.wait_for_timeout(2500)
            st.get_by_role("button", name="Stop recording").click()
            st.get_by_role("button", name="Submit this recording").click()
            expect(st.get_by_text("Your recording is submitted")).to_be_visible(timeout=30000)

            hr.goto(f"{BASE}/app/jobs/{job['ref']}?tab=insights")
            expect(hr.get_by_text("AI vs your team")).to_be_visible()
            expect(hr.get_by_text(re.compile(r"Compared so far: "))).to_be_visible()
            shot(hr, "f07b-insights")

            # ------------------------------------------------ manager: decide from the no-login link
            hr.goto(f"{BASE}/app/jobs/{job['ref']}?tab=pipeline&app={app['id']}")
            expect(hr.get_by_role("button", name="Video introduction", exact=False).first).to_be_visible()
            expect(hr.locator("video").first).to_be_visible()
            hr.get_by_role("button", name="2×").click()
            pick(hr, hr.get_by_role("combobox", name="Move to round"), "Manager approval")
            expect(hr.get_by_text(re.compile(r": (Passed|Moved|Selected|On hold|Started|Done)$"))).to_be_visible()
            hr.keyboard.press("Escape")
            det = api(hr, f"/api/applications/{app['id']}")
            mr = next(r for r in det["rounds"] if r["round"]["type"] == "manager_approval")
            ctx3, mg = new()
            mg.goto(mr["result"]["manager_link"])
            expect(mg.get_by_role("heading", name="Sana Student")).to_be_visible()
            mg.get_by_role("button", name="Select", exact=True).click()
            mg.fill("#dc-n", "Manoj Manager")
            shot(mg, "f08-decide")
            mg.get_by_role("button", name="Confirm").click()
            expect(mg.get_by_text("Decision recorded")).to_be_visible()

            # ------------------------------------------------ student books the human interview; interviewer gives feedback
            det = api(hr, f"/api/applications/{app['id']}")
            hrnd = next(r for r in det["rounds"] if r["round"]["type"] == "human_interview")
            assert det["round_id"] == hrnd["round"]["id"], "manager's Select moves the candidate to the final round"
            start = time.time() + 2 * 86400
            api(hr, f"/api/jobs/{job['id']}/rounds/{hrnd['round']['id']}/slots", "post", data={"series": {"start": start, "end": start + 3 * 3600, "minutes": 45}})
            st.goto(hrnd["result"]["candidate_link"])
            st.locator("button[aria-pressed]").first.click()
            st.get_by_role("button", name="Book this time").click()
            expect(st.get_by_role("link", name="Add to calendar")).to_be_visible()
            shot(st, "f09-booked")
            det = api(hr, f"/api/applications/{app['id']}")
            fb = next(r for r in det["rounds"] if r["round"]["type"] == "human_interview")["result"]["manager_link"]
            mg.goto(fb)
            expect(mg.get_by_text("Prep kit")).to_be_visible()
            mg.get_by_role("button", name="Select", exact=True).click()
            mg.get_by_role("button", name="4 stars").click()
            mg.fill("#fb-n", "Clear communicator, good attitude, handled the support scenario calmly.")
            mg.fill("#fb-name", "Ira Interviewer")
            shot(mg, "f10-feedback")
            mg.get_by_role("button", name="Submit feedback").click()
            expect(mg.get_by_text("Feedback submitted")).to_be_visible(timeout=20000)
            det = api(hr, f"/api/applications/{app['id']}")
            assert det["stage"] == "offer", det["stage"]

            # ------------------------------------------------ candidate status page and the placement officer's results
            st.goto(det["status_link"])
            expect(st.get_by_text("Customer Support Specialist")).to_be_visible()
            expect(st.get_by_text("Selected").first).to_be_visible()
            assert st.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "horizontal scroll on status page"
            shot(st, "f11-status")
            st.goto(drive["results_link"])
            expect(st.get_by_text("Sana Student")).to_be_visible()

            # ------------------------------------------------ the other HR pages load
            for path, text in (("/app/requests", "Candidate requests"), ("/app/outbox", "Outbox"), ("/app/my-interviews", "My interviews"),
                               ("/app/drives", "Campus drives"), ("/app/reports", "Funnel"), ("/app/audit", "Audit log"), ("/app/settings?tab=hiring", "Company FAQ")):
                hr.goto(BASE + path)
                expect(hr.get_by_text(text).first).to_be_visible(timeout=15000)
                shot(hr, "f12-" + path.strip("/").replace("/", "-").replace("?tab=", "-"))
            hr.goto(BASE + "/app/settings?tab=hiring")
            hr.get_by_role("button", name="Add a question").click()
            hr.get_by_label("Question 1").fill("Is this role hybrid?"); hr.get_by_label("Answer 1").fill("Yes, three days a week in the office.")
            hr.get_by_role("button", name="Add column").click()
            hr.get_by_label("HROne header 1").fill("Employee Name"); pick(hr, hr.get_by_role("combobox", name="Field for column 1"), "Full name")
            hr.get_by_role("button", name="Save", exact=True).click()
            expect(hr.get_by_text("Settings saved")).to_be_visible()
            r = hr.request.get(f"{BASE}/api/exports/hrone.xlsx?job={job['id']}")
            assert r.ok and r.body()[:2] == b"PK", r.status
            ctx.close(); ctx2.close(); ctx3.close()
            browser.close()
    finally:
        srv.terminate()
        srv.wait(10)
    text = log.read_text()
    if "Traceback" in text:
        errors.append("server traceback:\n" + text[text.index("Traceback"):][:3000])
    assert not errors, "\n".join(errors)
    print("FLOWS BROWSER E2E PASSED")


if __name__ == "__main__":
    main()
