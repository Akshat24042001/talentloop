"""Real-browser walk through interview scheduling:  python -m tests.e2e_scheduling [screenshot_dir]

A candidate books a human interview by day and time, moves it, cancels it and suggests other times; HR books a time
for them from the application drawer; another candidate books, then moves, an AI interview time; the candidate signs
in at /me with an emailed code and sees the booked time. Fails on any browser JS error or server traceback."""
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from tests.e2e_browser import free_port_wait

ROOT = Path(__file__).resolve().parent.parent
PORT = 8796
BASE = f"http://127.0.0.1:{PORT}"
SHOTS = Path(sys.argv[1]) if len(sys.argv) > 1 else None


def main():
    data = tempfile.mkdtemp()
    env = dict(os.environ, ALLOW_SAMPLE_DATA="1", LLM_MOCK="1", PUBLIC_URL=BASE, APP_URL=BASE, VAPI_PUBLIC_KEY="pk_test", ADMIN_KEY="", DATA_DIR=data,
               LOG_LEVEL="WARNING", PLATFORM_ADMIN_EMAILS="", DATABASE_URL=os.getenv("TEST_DATABASE_URL", ""), PYTHONUNBUFFERED="1")
    log = Path(data) / "server.log"
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(PORT)], cwd=ROOT, env=env,
                           stdout=open(log, "w"), stderr=subprocess.STDOUT)
    assert free_port_wait(PORT), "server did not start"
    os.environ.update(DATA_DIR=data, DATABASE_URL=env["DATABASE_URL"])
    from backend import db
    errors: list[str] = []

    def last_mail(to, template):
        with db.session() as s:
            m = s.query(db.Message).filter(db.Message.to == to, db.Message.template == template).order_by(db.Message.created_at.desc()).first()
            return m.body if m else ""

    try:
        with sync_playwright() as p:
            exe = "/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else None
            browser = p.chromium.launch(executable_path=exe)

            def new():
                ctx = browser.new_context(viewport={"width": 1280, "height": 900}, timezone_id="Asia/Kolkata")
                pg = ctx.new_page()
                pg.add_locator_handler(pg.locator("#ask-ok"), lambda: pg.locator("#ask-ok").click(), no_wait_after=True)
                pg.add_locator_handler(pg.get_by_role("button", name="Skip the tour"), lambda: pg.get_by_role("button", name="Skip the tour").click(), no_wait_after=True)
                pg.on("pageerror", lambda e: errors.append(f"{pg.url}: {e}"))
                pg.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text and errors.append(f"{pg.url}: console {m.text}"))
                return ctx, pg

            def shot(pg, name):
                if SHOTS:
                    SHOTS.mkdir(parents=True, exist_ok=True)
                    pg.screenshot(path=str(SHOTS / f"s-{name}.png"), full_page=True)

            def api(pg, path, method="get", **kw):
                r = getattr(pg.request, method)(BASE + path, **kw)
                assert r.ok, f"{method} {path}: {r.status} {r.text()[:300]}"
                return r.json()

            # ------------------------------------------------ HR sets up a job, slots and two candidates
            hctx, hr = new()
            api(hr, "/api/auth/signup", "post", data={"email": "hema@sched.test", "password": "correct-horse-1", "name": "Hema HR", "company": "Sched Co"})
            job = api(hr, "/api/jobs", "post", data={"fields": {"title": "Support Lead", "department": "Ops", "employment_type": "Full-time", "workplace_type": "On-site",
                                                                "locations": ["Pune"]}, "status": "draft"})
            api(hr, f"/api/jobs/{job['id']}/flow", "put", data={"rounds": [{"type": t, "advance": "hr"} for t in ("application", "human_interview", "ai_interview")]})
            rounds = {r["type"]: r for r in api(hr, f"/api/jobs/{job['id']}/flow")["rounds"]}
            hi, ai = rounds["human_interview"]["id"], rounds["ai_interview"]["id"]
            t0 = (int(time.time() // 3600) + 50) * 3600
            api(hr, f"/api/jobs/{job['id']}/rounds/{hi}/slots", "post", data={"slots": [{"starts_at": t0 + i * 3600, "ends_at": t0 + i * 3600 + 2700} for i in range(4)]
                                                                               + [{"starts_at": t0 + 86400, "ends_at": t0 + 86400 + 2700}], "meeting_url": "https://meet.test/x"})

            def candidate(name, email, rid):
                c = api(hr, "/api/candidates", "post", data={"name": name, "email": email, "phone": "9876543210", "resume_text": "Support"})
                api(hr, f"/api/jobs/{job['id']}/applications", "post", data={"candidate_id": c["id"]})
                aid = next(a["id"] for a in api(hr, f"/api/jobs/{job['id']}/pipeline")["items"] if a["candidate"]["id"] == c["id"])
                api(hr, f"/api/applications/{aid}/decide", "post", data={"action": "move", "round_id": rid})
                return aid
            a1 = candidate("Ravi Kumar", "ravi@sched.test", hi)
            link1 = next(r for r in api(hr, f"/api/applications/{a1}")["rounds"] if r["round"]["type"] == "human_interview")["result"]["candidate_link"]

            # ------------------------------------------------ candidate: book, move, cancel, suggest times
            cctx, cand = new()
            cand.goto(link1)
            expect(cand.get_by_text("Pick a time for your interview")).to_be_visible()
            cand.get_by_role("tab").first.click()
            cand.locator("button[aria-pressed]").first.click()
            shot(cand, "01-pick")
            cand.get_by_role("button", name=re.compile(r"^Book ")).click()
            expect(cand.get_by_text("Confirmed", exact=True)).to_be_visible()
            assert "IST" in last_mail("ravi@sched.test", "interview_booked"), "confirmation email in IST"
            shot(cand, "02-booked")
            cand.get_by_role("button", name="Change the time").click()
            cand.locator("button[aria-pressed=false]").filter(has_text=re.compile(r"\d:\d\d")).first.click()
            cand.get_by_role("button", name=re.compile(r"^Move to ")).click()
            expect(cand.get_by_text("Confirmed", exact=True)).to_be_visible()
            assert "Was: " in last_mail("ravi@sched.test", "interview_booked"), "reschedule email shows the old time"
            cand.get_by_role("button", name="Cancel", exact=True).click()
            cand.get_by_role("button", name="Cancel the time").click()
            expect(cand.get_by_text("Your interview time was cancelled")).to_be_visible()
            cand.get_by_role("button", name="None of these times work").click()
            cand.get_by_label("Times that suit you").fill("Weekdays after 6 pm")
            cand.get_by_role("button", name="Send", exact=True).click()
            expect(cand.get_by_text("We've told the hiring team")).to_be_visible()
            shot(cand, "03-cancelled")

            # ------------------------------------------------ HR books a time for them from the drawer
            hr.goto(f"{BASE}/app/jobs/{job['id']}?tab=pipeline&app={a1}")
            expect(hr.get_by_text("None of the open times work for them")).to_be_visible()
            hr.get_by_role("button", name="Book a time for them").click()
            dlg = hr.get_by_role("dialog").last
            dlg.locator("button[aria-pressed=false]").filter(has_text=re.compile(r"\d:\d\d")).first.click()
            dlg.get_by_role("button", name=re.compile(r"^Book ")).click()
            expect(hr.get_by_text(re.compile(r"booked by Hema HR"))).to_be_visible()
            shot(hr, "04-hr-booked")
            assert "by the hiring team" in last_mail("ravi@sched.test", "interview_booked")
            cand.reload()
            expect(cand.get_by_text("Confirmed by the hiring team")).to_be_visible()

            # ------------------------------------------------ AI interview: book a time, then move it
            a2 = candidate("Zara Ali", "zara@sched.test", ai)
            link2 = None
            for _ in range(40):
                r2 = next(r for r in api(hr, f"/api/applications/{a2}")["rounds"] if r["round"]["type"] == "ai_interview")["result"]
                if r2["status"] == "invited":
                    link2 = r2["candidate_link"]
                    break
                time.sleep(0.5)
            assert link2, "AI interview was not prepared"
            cand.goto(link2)
            cand.get_by_role("button", name="Book a time").click()
            cand.locator("button[aria-pressed=false]").filter(has_text=re.compile(r"\d:\d\d")).first.click()
            cand.get_by_role("button", name=re.compile(r"^Book ")).click()
            expect(cand.get_by_text("Booked", exact=True)).to_be_visible()
            expect(cand.get_by_role("link", name="Start now")).to_be_visible()
            shot(cand, "05-ai-booked")
            cand.get_by_role("button", name="Change the time").click()
            cand.locator("button[aria-pressed=false]").filter(has_text=re.compile(r"\d:\d\d")).first.click()   # any other free time (late in the day only a few are left)
            cand.get_by_role("button", name=re.compile(r"^Book ")).click()
            expect(cand.get_by_text("Booked", exact=True)).to_be_visible()
            assert "IST" in last_mail("zara@sched.test", "ai_interview_scheduled")

            # ------------------------------------------------ candidate signs in at /me
            mctx, me = new()
            me.goto(BASE + "/me")
            me.get_by_label("Email").fill("ravi@sched.test")
            me.get_by_role("button", name="Email me a code").click()
            expect(me.get_by_text("a code is on its way")).to_be_visible()
            code = re.search(r"\b(\d{6})\b", last_mail("ravi@sched.test", "candidate_login")).group(1)
            me.get_by_label("6-digit code").fill(code)
            me.get_by_role("button", name="Sign in").click()
            expect(me.get_by_text("Support Lead")).to_be_visible()
            expect(me.get_by_role("link", name="Details, change or cancel")).to_be_visible()
            shot(me, "06-me")
            me.get_by_role("link", name="Status and help").click()
            expect(me.get_by_text("Change or cancel the time")).to_be_visible()
            shot(me, "07-status")
            browser.close()
    finally:
        srv.terminate()
    tb = [l for l in log.read_text().splitlines() if "Traceback" in l]
    assert not errors, errors
    assert not tb, log.read_text()[-3000:]
    print("SCHEDULING BROWSER E2E PASSED")


if __name__ == "__main__":
    main()
