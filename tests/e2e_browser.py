"""Real-browser end-to-end test (Chromium + Playwright), no Vapi account needed:  python -m tests.e2e_browser

A stand-in for the Vapi web SDK is served at /vendor/vapi-web.mjs. Like the real SDK it plays the
interviewer through an <audio> element and sends each candidate turn to our custom-LLM endpoint.
Chromium runs with a fake camera, microphone and screen. The face detector is also replaced so the test
can control how many faces are "seen". Everything else is the real app: pages, recording, uploads,
ffmpeg repair, proctoring, scoring (mock LLM), PDF/ZIP, reconnect window and the sweeper.

Checks the things HR complained about: the video is playable and seekable, it contains BOTH voices,
screen recording works, the proctoring report exists without AI scoring, downloads work, and a
candidate cannot rejoin after the window.
"""
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
import math
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PORT = 8799
BASE = f"http://127.0.0.1:{PORT}"
KEY = "e2e-admin-key-123456"
H = {"X-Admin-Key": KEY}

FAKE_VAPI = r"""
const sleep = ms => new Promise(r => setTimeout(r, ms));
export default class FakeVapi {
  constructor(key){ this.h = {}; this.muted = false; this.stopped = false; }
  on(e, f){ (this.h[e] ||= []).push(f); }
  emit(e, x){ (this.h[e] || []).forEach(f => f(x)); }
  isMuted(){ return this.muted; } setMuted(m){ this.muted = m; }
  getAudioPlayer(){ return this.player || null; }
  stop(){ this.stopped = true; this.cleanup(); this.emit('call-end'); }
  cleanup(){ try{ this.osc.stop(); }catch{} this.player && this.player.remove(); }
  async start(asst){
    const u = new URL(asst.model.url); this.path = u.pathname + '/chat/completions';
    const ctx = new AudioContext(); this.osc = ctx.createOscillator(); const d = ctx.createMediaStreamDestination();
    this.osc.frequency.value = 330; const g = ctx.createGain(); g.gain.value = 0.5; this.osc.connect(g).connect(d); this.osc.start();
    this.player = document.createElement('audio'); this.player.dataset.participantId = 'assistant';
    this.player.srcObject = d.stream; document.body.appendChild(this.player); this.player.play().catch(()=>{});
    window.__asst = asst;
    setTimeout(() => this.run(asst), 20);
    return {id: 'call_fake_' + Date.now()};
  }
  async speak(msgs, text){ msgs.push({role: 'assistant', content: text}); this.emit('speech-start'); this.emit('message', {type:'transcript', role:'assistant', transcriptType:'final', transcript: text}); await sleep(150); this.emit('speech-end'); }
  // Real SDK signature: say(message, endCallAfterSpoken, interruptionsEnabled, interruptAssistantEnabled)
  say(text, endAfter){ (window.__said ||= []).push({text, endAfter}); this.msgs && this.msgs.push({role: 'assistant', content: text});
    this.emit('message', {type:'transcript', role:'assistant', transcriptType:'final', transcript: text});
    if (endAfter){ this.stopped = true; setTimeout(() => { this.cleanup(); this.emit('call-end'); }, 800); } }
  async run(asst){
    this.emit('call-start');
    const msgs = this.msgs = [{role:'system', content:'x'}];
    await this.speak(msgs, asst.firstMessage);
    let n = 0;
    for (const a of (window.__ANSWERS || [])){
      await sleep(window.__TURN_MS || 1200);
      if (this.stopped) return;
      if (window.__DROP_AFTER && ++n > window.__DROP_AFTER){ window.__DROP_AFTER = 0; this.cleanup(); this.emit('call-end'); return; }
      msgs.push({role:'user', content: a});
      this.emit('message', {type:'transcript', role:'user', transcriptType:'final', transcript: a});
      const r = await fetch(this.path, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({messages: msgs, stream: true})});
      if (!r.ok){ window.__llmError = r.status; this.cleanup(); this.emit('call-end'); return; }
      const text = (await r.text()).split('\n').filter(l => l.startsWith('data: ') && !l.includes('[DONE]'))
        .map(l => JSON.parse(l.slice(6)).choices[0].delta.content || '').join('');
      await this.speak(msgs, text);
      if (/concludes our interview/i.test(text)){ await sleep(1500); this.cleanup(); this.emit('call-end'); return; }
    }
  }
}
"""

# Face detector stand-in: detections controlled by window.__FACES (default 1).
FAKE_VISION = r"""
export const FilesetResolver = { forVisionTasks: async () => ({}) };
// Keypoints 0 right eye, 1 left eye, 2 nose tip. The nose swings left and right like a head turn (window.__YAW pins it).
const kp = () => { const y = window.__YAW ?? Math.sin(Date.now() / 400) * 0.6; return [{x: 0.45, y: 0.4}, {x: 0.55, y: 0.4}, {x: 0.5 + y * 0.1, y: 0.5}]; };
export const FaceDetector = { createFromOptions: async () => ({
  detectForVideo: () => ({ detections: Array.from({length: window.__FACES ?? 1}, () => ({categories: [{score: 0.9}], keypoints: kp()})) }) }) };
// Object detector stand-in (people anywhere in the room, phones): window.__PERSONS (default: one per face), window.__PHONES.
export const ObjectDetector = { createFromOptions: async () => ({
  detectForVideo: () => ({ detections: [
    ...Array.from({length: window.__PERSONS ?? Math.min(1, window.__FACES ?? 1)}, () => ({categories: [{categoryName: 'person', score: 0.8}]})),
    ...Array.from({length: window.__PHONES ?? 0}, () => ({categories: [{categoryName: 'cell phone', score: 0.7}]}))] }) }) };
// Face mesh stand-in: blendshapes. By default the jaw moves like someone talking and the eyes look at the screen;
// window.__STILL_LIPS freezes the mouth (someone else speaking), window.__EYES_DOWN looks into the lap.
export const FaceLandmarker = { createFromOptions: async () => ({
  detectForVideo: () => { const t = Date.now();
    const jaw = window.__STILL_LIPS ? 0.1 : 0.15 + 0.15 * Math.sin(t / 90) + 0.05 * Math.sin(t / 37);
    const down = window.__EYES_DOWN ? 0.8 : 0.15;
    return { faceBlendshapes: [{ categories: [['jawOpen', jaw], ['eyeLookDownLeft', down], ['eyeLookDownRight', down], ['eyeBlinkLeft', 0.1], ['eyeBlinkRight', 0.1],
      ['eyeLookInLeft', 0.05], ['eyeLookOutLeft', 0.05], ['eyeLookInRight', 0.05], ['eyeLookOutRight', 0.05]].map(([categoryName, score]) => ({categoryName, score})) }] } } }) };
"""

ANSWERS = ["Hi, I'm Rohan. I have three years of backend experience with Spring Boot at ShipKart, building shipment APIs.",
           "I want a bigger scale problem. ShipKart is small and I have owned most of the systems already, so I want to grow.",
           "My notice period is sixty days and it can be negotiated down to about forty five days.",
           "Yes, I can work from the Prahlad Nagar office three days a week without any problem.",
           "I built the tracking API, added composite indexes and Redis caching which cut p95 latency from 1.8 seconds to 350 ms.",
           "I led the migration of notifications to Kafka consumers with retries and a dead letter queue."] * 3


def sweep_y4m(path: Path):
    """A fake camera film for the room scan: the view turns a full circle (400 degrees), then tilts up and down, and repeats every 30 s.
    Chrome plays it in a loop in place of its green test picture, so the scan's own measurement is what the test exercises."""
    import numpy as np
    W, H, FPS, N, HFOV = 320, 180, 10, 300, 66.0
    ppd = W / HFOV
    pw, ph = int(360 * ppd), H + 260
    rng = np.random.default_rng(3)
    pan = rng.random((ph, pw)) * 255
    for _ in range(3):
        pan = (pan * 2 + np.roll(pan, 1, 0) + np.roll(pan, -1, 0) + np.roll(pan, 1, 1) + np.roll(pan, -1, 1)) / 6
    pan = (pan - pan.min()) / (pan.max() - pan.min()) * 200 + 25
    with open(path, "wb") as f:
        f.write(f"YUV4MPEG2 W{W} H{H} F{FPS}:1 Ip A1:1 C420jpeg\n".encode())
        for i in range(N):
            yaw = 400.0 * min(1.0, i / 190)
            pitch = 0.0 if i < 190 else 25 * math.sin((i - 190) / 110 * 2 * math.pi) * 1.0
            cx, cy = int(yaw * ppd), 130 - int(pitch * ppd)
            cols = (np.arange(W) + cx - W // 2) % pw
            frame = pan[cy:cy + H][:, cols]
            f.write(b"FRAME\n" + frame.astype(np.uint8).tobytes() + bytes([128]) * (W * H // 2))


def free_port_wait(port, up=True, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = socket.socket()
        ok = s.connect_ex(("127.0.0.1", port)) == 0
        s.close()
        if ok == up:
            return True
        time.sleep(0.3)
    return False


def ffprobe(path: Path) -> str:
    import imageio_ffmpeg
    r = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True)
    return r.stderr.decode(errors="ignore")


def tone_power(path: Path, freq: float, start: float, dur: float = 3.0) -> float:
    """Goertzel power of `freq` in the recording's audio (mono 8 kHz), relative to total energy."""
    import imageio_ffmpeg
    raw = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-ss", str(start), "-t", str(dur),
                          "-i", str(path), "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], capture_output=True).stdout
    xs = struct.unpack(f"<{len(raw) // 2}h", raw[: len(raw) // 2 * 2])
    if not xs:
        return 0.0
    k = 2 * math.cos(2 * math.pi * freq / 8000)
    s1 = s2 = 0.0
    for x in xs:
        s0 = x + k * s1 - s2
        s2, s1 = s1, s0
    power = s1 * s1 + s2 * s2 - k * s1 * s2
    energy = sum(x * x for x in xs) or 1
    return power / (energy * len(xs) / 2)


def create(c: httpx.Client, **settings) -> str:
    s = ROOT / "frontend" / "public" / "samples"
    inp = {"company": "Demo Tech", "role": "Java Backend Developer", "candidate_name": "Rohan Mehta", "duration_min": 15,
           "jd": (s / "sample_jd.txt").read_text(), "resume": (s / "sample_resume.txt").read_text(),
           "questions": [q for q in (s / "sample_questions.txt").read_text().splitlines() if q.strip()]}
    plan = c.post("/api/plan", json=inp).raise_for_status().json()["plan"]
    out = c.post("/api/interviews", json={"plan": plan, "inputs": inp, "settings": settings}).raise_for_status().json()
    assert "id=" not in out["candidate_path"] and out["id"] not in out["candidate_path"], out["candidate_path"]
    CREATED[out["id"]] = out
    return out["id"]


CREATED: dict[str, dict] = {}       # interview id -> the create response (candidate link and access code)


def wait(fn, timeout=60, every=0.5, what="condition"):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = fn()
        if v:
            return v
        time.sleep(every)
    raise AssertionError(f"timed out waiting for {what}")


def wait_question(pg):
    """The call is live once the current question is on screen."""
    pg.wait_for_function("(t => t.length > 5 && !t.startsWith('Connecting'))(document.getElementById('qText').textContent)", timeout=20000)


def scan_room(pg):
    """The room scan before the start (12 s with the stand-in detector); a no-op when the interview doesn't ask for it."""
    pg.wait_for_function("(e => !e || e.classList.contains('ok'))(document.getElementById('ckEars'))", timeout=20000)
    if pg.locator("#roomBtn").count() and not pg.locator("#ckRoom.ok").count():
        prev = pg.evaluate("window.__PERSONS")
        pg.evaluate("window.__PERSONS = 0")                       # turned away from the candidate: nobody in view
        pg.click("#roomBtn")
        pg.wait_for_selector("#ckRoom.ok", timeout=110000)
        pg.evaluate(f"window.__PERSONS = {json.dumps(prev)}")


def tracks_stopped(pg) -> bool:
    """No camera, microphone or screen track is still live."""
    return pg.evaluate("window.__mediaLive() === 0")


def main():
    data = tempfile.mkdtemp()
    film = Path(data) / "sweep.y4m"
    sweep_y4m(film)
    env = dict(os.environ, ALLOW_SAMPLE_DATA="1", LLM_MOCK="1", PUBLIC_URL="https://example.onrender.com", VAPI_PUBLIC_KEY="pk_test",
               ADMIN_KEY=KEY, DATA_DIR=data, RECONNECT_WINDOW_SEC="12", SWEEP_EVERY_SEC="3", LOG_LEVEL="WARNING",
               PYTHONUNBUFFERED="1", PLATFORM_ADMIN_EMAILS="admin@e2e.test", DATABASE_URL="")
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(PORT)], cwd=ROOT, env=env,
                           stdout=open(Path(data) / "server.log", "w"), stderr=subprocess.STDOUT)
    assert free_port_wait(PORT), "server did not start"
    c = httpx.Client(base_url=BASE, headers=H, timeout=60)
    failures = []
    try:
        with sync_playwright() as p:
            exe = "/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else None
            browser = p.chromium.launch(executable_path=exe, args=[
                "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", f"--use-file-for-fake-video-capture={film}", "--autoplay-policy=no-user-gesture-required",
                "--auto-select-desktop-capture-source=Entire screen", "--enable-usermedia-screen-capturing",
                "--allow-http-screen-capture"])

            def page_for(iid, answers, **flags):
                ctx = browser.new_context(permissions=["camera", "microphone"])
                pg = ctx.new_page()
                errs = []
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.route("**/vendor/vapi-web.mjs", lambda r: r.fulfill(status=200, content_type="text/javascript", body=FAKE_VAPI))
                pg.route("**/vendor/mediapipe/vision_bundle.mjs", lambda r: r.fulfill(status=200, content_type="text/javascript", body=FAKE_VISION))
                # screen.isExtended (second monitor) is controlled by window.__EXT, like a real display change.
                init = (f"window.__ANSWERS = {json.dumps(answers)}; window.__TURN_MS = {flags.get('turn_ms', 1200)}; window.__DROP_AFTER = {flags.get('drop_after', 0)}; window.__FACES = 1;"
                        "Object.defineProperty(Screen.prototype, 'isExtended', {get: () => !!window.__EXT, configurable: true});")
                # window.__VOICE: the microphone hears a voice (a 150 Hz voiced sound); window.__EXTRA_DEVICES: audio devices
                # added to the device list (earbuds), announced with a devicechange event like the real thing.
                init += ("const _gf = AnalyserNode.prototype.getFloatTimeDomainData;"
                         "AnalyserNode.prototype.getFloatTimeDomainData = function (b) { if (!window.__VOICE) return _gf.call(this, b);"
                         " const r = this.context.sampleRate; for (let i = 0; i < b.length; i++) b[i] = 0.3 * Math.sin(2 * Math.PI * 150 * i / r) + 0.1 * Math.sin(2 * Math.PI * 300 * i / r); };"
                         "const _ed = MediaDevices.prototype.enumerateDevices;"
                         "MediaDevices.prototype.enumerateDevices = async function () { const d = window.__EXTRA_DEVICES || []; return [...d, ...(await _ed.call(this)).filter(x => !d.some(y => y.deviceId === x.deviceId && y.kind === x.kind))]; };"
                         "window.__plug = (d) => { window.__EXTRA_DEVICES = d; navigator.mediaDevices.dispatchEvent(new Event('devicechange')); };")
                if flags.get("vcam"):      # a virtual camera driver, as OBS installs it
                    init += ("const _l = Object.getOwnPropertyDescriptor(MediaStreamTrack.prototype, 'label');"
                             "Object.defineProperty(MediaStreamTrack.prototype, 'label', {get() { return this.kind === 'video' ? 'OBS Virtual Camera' : _l.get.call(this) }});")
                pg.add_init_script(init)
                pg.goto(BASE + CREATED[iid]["candidate_path"])      # the encrypted link, then the access code
                pg.fill("#accessCode", CREATED[iid]["access_code"])
                pg.click("#unlockBtn")
                return pg, errs

            def pass_checks(pg, share=False):
                pg.check("#consent")
                pg.click("#toCheck")
                pg.wait_for_selector("#ckCam.ok", timeout=15000)
                pg.wait_for_selector("#ckMic.ok", timeout=20000)   # the fake mic plays a beep tone
                pg.wait_for_selector("#ckFace.ok", timeout=15000)
                pg.wait_for_function("(e => !e || e.classList.contains('ok'))(document.getElementById('ckLive'))", timeout=15000)   # head turn
                pg.wait_for_function("(e => !e || e.classList.contains('ok'))(document.getElementById('ckEars'))", timeout=15000)   # ear photos (demo: kept for HR)
                if pg.locator("#roomBtn").count():
                    assert pg.is_enabled("#startBtn") is False, "start must wait for the room scan"
                    pg.evaluate("window.__PERSONS = 0")                                                   # turned away from the candidate: nobody in view
                    pg.click("#roomBtn")
                    try:
                        pg.wait_for_selector("#ckRoom.ok", timeout=110000)                                # the camera film turns a full circle, then tilts
                    except Exception:
                        raise AssertionError("room scan did not finish: " + pg.inner_text("#ckRoom") + " | " + (pg.inner_text("#roomHint") if pg.locator("#roomHint").count() else "no hint"))
                    pg.evaluate("window.__PERSONS = undefined")
                if share:
                    assert pg.is_enabled("#startBtn") is False, "start must wait for screen sharing"
                    pg.click("#shareBtn")
                    pg.wait_for_selector("#ckShare.ok", timeout=15000)
                pg.wait_for_function("!document.getElementById('startBtn').disabled", timeout=15000)

            # ---------------------------------------------------------- 1. full interview, screen share required
            iid = create(c, require_screen_share=True, candidate_email="rohan@example.com", reconnect_window_sec=12)
            pg, errs = page_for(iid, ANSWERS, turn_ms=1500)
            pass_checks(pg, share=True)
            pg.click("#startBtn")
            pg.wait_for_selector("#s3:not(.hidden)")
            wait_question(pg)
            # the shared screen is shown live, and the candidate is never told counts or time
            assert pg.evaluate("document.getElementById('screenVid').srcObject?.active === true"), "screen share not shown"
            assert pg.is_visible("#screenTile")
            body = pg.inner_text("body").lower()
            assert "minutes" not in body and " of 5" not in body and "question 1 of" not in body, "counts or time shown to the candidate"
            time.sleep(4)
            # integrity signals during the call
            pg.evaluate("document.dispatchEvent(new ClipboardEvent('paste', {clipboardData: new DataTransfer()}))")
            pg.evaluate("window.__FACES = 2")
            time.sleep(3)
            pg.evaluate("window.__FACES = 0")
            time.sleep(5)
            pg.evaluate("window.__FACES = 1")
            pg.click("#muteBtn")
            assert pg.is_visible("#mutedBanner")
            time.sleep(1.5)
            pg.click("#muteBtn")
            other = pg.context.new_page()
            other.goto(f"{BASE}/style.css")
            other.bring_to_front()
            time.sleep(2)
            pg.bring_to_front()
            other.close()
            pg.wait_for_selector("#s4:not(.hidden)", timeout=180000)
            pg.wait_for_function("document.getElementById('uploadMsg')?.textContent.includes('saved') || document.getElementById('uploadMsg')?.textContent === ''", timeout=60000)
            pg.wait_for_selector("#fbBox:not(.hidden)", timeout=30000)
            assert tracks_stopped(pg), "camera or screen sharing still running after the interview"
            pg.click("#stars button:nth-child(5)")
            pg.click("#fbSend")
            pg.wait_for_function("document.getElementById('fbDone').textContent.includes('Thank')")
            if errs:
                failures.append(f"candidate page JS errors: {errs}")

            rec = wait(lambda: (lambda r: r if r.get("report") and all(m.get("finalized") for m in r["media"] if m.get("rid")) else None)(
                c.get(f"/api/interviews/{iid}").json()), timeout=90, what="scoring + recording finalization")
            print("status:", rec["status"], "| risk:", rec["proctoring"]["risk"], "|", rec["proctoring"]["reasons"])
            kinds = {m["kind"] for m in rec["media"]}
            print("media:", [(m["kind"], m.get("duration_sec"), m.get("playable"), m["bytes"]) for m in rec["media"]])
            assert rec["status"] == "scored", rec["status"]
            assert {"candidate_video", "screen_video"} <= kinds, kinds
            cam = next(m for m in rec["media"] if m["kind"] == "candidate_video")
            assert cam["playable"] and cam["duration_sec"] and cam["duration_sec"] > 10, cam
            vid = Path(data) / "media" / iid / cam["file"]
            info = ffprobe(vid)
            assert "Video: vp8" in info and "Audio: opus" in info, info[-400:]
            assert "Duration: N/A" not in info
            # Both voices in the recording: the interviewer's 330 Hz tone must be present in the audio.
            p330 = max(tone_power(vid, 330, s) for s in (3, 8, 13))
            print(f"interviewer voice (330 Hz) share of recording audio: {p330:.2f}")
            assert p330 > 0.05, "interviewer audio missing from the camera recording"
            scr = next(m for m in rec["media"] if m["kind"] == "screen_video")
            assert scr["playable"] and "Video:" in ffprobe(Path(data) / "media" / iid / scr["file"])
            cnt = rec["proctoring"]["counts"]
            for k in ("paste", "multiple_faces", "face_missing_start", "mute_on", "screen_share_started", "call_start", "liveness_passed", "answer_timing"):
                assert cnt.get(k), f"missing proctoring event {k}: {cnt}"
            assert not cnt.get("virtual_camera"), "the test camera is not a virtual camera"
            assert not cnt.get("identity_check_unavailable"), "face-api and its self-hosted models must load"
            assert rec["plan"]["questions"][0].get("practice"), "the interview starts with a practice question"
            assert rec["proctoring"]["risk"] in ("medium", "high")
            assert any(i["reason"] == "reference" for i in rec["images"]), rec["images"]
            assert any(i["reason"] == "reference" and i.get("source") == "screen" for i in rec["images"]), "no screen snapshot"
            assert any(i["reason"] in ("multiple_faces", "no_face") for i in rec["images"])
            assert rec["consent"] and rec["feedback"]["rating"] == 5 and rec["device"].get("screen")
            assert rec["settings"]["candidate_email"] == "rohan@example.com"

            # HR report page: video plays with a real duration, jump-to-moment works, downloads work
            hr_ctx = browser.new_context()
            hr = hr_ctx.new_page()
            hr.add_locator_handler(hr.get_by_role("button", name="Skip the tour"), lambda: hr.get_by_role("button", name="Skip the tour").click(), no_wait_after=True)
            hr_errs = []
            hr.on("pageerror", lambda e: hr_errs.append(str(e)))
            # interviews made with the API key belong to no company, so a platform admin sees them
            assert hr_ctx.request.post(f"{BASE}/api/auth/signup", data={"email": "admin@e2e.test", "password": "e2e-password-1",
                                                                        "name": "E2E Admin", "company": "E2E Co"}).ok
            hr.goto(f"{BASE}/report.html?id={iid}")      # old link: redirects to /app/interviews/<id>
            hr.wait_for_selector("video[data-file]", timeout=20000)
            dur = hr.evaluate("""() => new Promise(res => { const v = document.querySelector('video[data-file]');
                if (v.readyState >= 1) return res(v.duration); v.onloadedmetadata = () => res(v.duration); setTimeout(() => res(v.duration), 8000); })""")
            print("report page video duration:", dur)
            assert dur and dur != float("inf") and dur > 10, dur
            ts = rec["state"]["log"][4]["ts"]
            hr.evaluate(f"jump({ts})")
            time.sleep(1)
            cur = hr.evaluate("document.querySelector('video[data-file]').currentTime")
            print("jump-to-moment currentTime:", cur)
            assert cur > 1, cur
            assert hr.locator("text=Integrity and proctoring").count() and hr.locator(".snaps img, .moment img").count() >= 3
            assert hr.locator(".hbar").count() >= 3, "report charts missing"
            assert not hr.locator("td.qref:text-matches('^q[0-9]+$')").count(), "bare question ids shown to HR"
            with hr.expect_download() as d:
                hr.click("text=Download PDF report")
            pdf = Path(d.value.path()).read_bytes()
            assert pdf[:5] == b"%PDF-" and len(pdf) > 20000
            with hr.expect_download() as d:
                hr.click("text=Download everything (ZIP)")
            import zipfile
            names = zipfile.ZipFile(d.value.path()).namelist()
            print("zip:", [n.split("/", 1)[1] for n in names])
            assert any(n.endswith("report.pdf") for n in names) and any("/recordings/camera_" in n for n in names)
            assert any("/snapshots/" in n for n in names)
            if hr_errs:
                failures.append(f"report page JS errors: {hr_errs}")
            hr.goto(f"{BASE}/app/interviews")
            hr.wait_for_selector("tbody >> text=Rohan Mehta", timeout=15000)
            hr.fill("#q", "nobody-matches")
            assert hr.locator("text=No interviews match").count()
            if hr_errs:
                failures.append(f"HR page JS errors: {hr_errs}")

            # ---------------------------------------------------------- 2. drop and rejoin inside the window
            iid2 = create(c, reconnect_window_sec=12)
            pg2, errs2 = page_for(iid2, ANSWERS, drop_after=2, turn_ms=800)
            pass_checks(pg2)
            pg2.click("#startBtn")
            pg2.wait_for_selector("#reconnectBox:not(.hidden)", timeout=60000)
            assert "left to rejoin" in pg2.inner_text("#rejoinLeft")
            time.sleep(2)
            pg2.click("#reconnectBtn")
            pg2.wait_for_function("window.__asst && window.__asst.firstMessage.startsWith('Welcome back')", timeout=20000)
            pg2.wait_for_selector("#s4:not(.hidden)", timeout=120000)
            r2 = wait(lambda: (lambda r: r if r.get("report") and all(m.get("finalized") for m in r["media"] if m["kind"] == "candidate_video") else None)(
                c.get(f"/api/interviews/{iid2}").json()), 90, what="rejoined interview scored and its recordings saved")
            assert r2["state"]["reconnects"] == 1 and r2["state"]["ended"], r2["state"].get("reconnects")
            parts = [m for m in r2["media"] if m["kind"] == "candidate_video"]
            assert len(parts) == 2 and all(m.get("playable") for m in parts), parts
            print("rejoin inside window: OK, recording parts:", [m.get("duration_sec") for m in parts])
            if errs2:
                failures.append(f"rejoin page JS errors: {errs2}")

            # ---------------------------------------------------------- 3. drop, try to rejoin after the window
            iid3 = create(c, reconnect_window_sec=12)
            pg3, _ = page_for(iid3, ANSWERS, drop_after=2, turn_ms=800)
            pass_checks(pg3)
            pg3.click("#startBtn")
            pg3.wait_for_selector("#reconnectBox:not(.hidden)", timeout=60000)
            # the page itself closes the door when the countdown ends
            pg3.wait_for_function("document.getElementById('doneTitle')?.textContent === 'Interview closed'", timeout=40000)
            # and the server refuses a late rejoin even if the page is bypassed (after its 2 s grace)
            time.sleep(3)
            assert httpx.post(f"{BASE}/api/interviews/{iid3}/assistant").status_code == 404, "a raw id must open nothing"
            key3 = CREATED[iid3]["candidate_path"].split("k=")[1]       # the candidate's own browser: key + code cookie
            late = pg3.request.post(f"{BASE}/api/interviews/{key3}/assistant", data={})
            print("late rejoin:", late.status, late.json().get("detail", "")[:80])
            assert late.status in (409, 410), late.status
            r3 = wait(lambda: (lambda r: r if r["status"] in ("incomplete", "scored") and r.get("report") else None)(
                c.get(f"/api/interviews/{iid3}").json()), 60, what="abandoned interview closed and scored")
            assert r3.get("ended_early") and any("did not reach its normal end" in x for x in r3["report"]["human_review_reasons"])
            print("rejoin after window: refused, interview closed and scored:", r3["status"])

            # ---------------------------------------------------------- 4. candidate ends deliberately
            iid4 = create(c)
            pg4, _ = page_for(iid4, ANSWERS, turn_ms=1500, vcam=True)
            pass_checks(pg4)
            pg4.click("#startBtn")
            wait_question(pg4)
            time.sleep(4)
            pg4.click("#endBtn")
            pg4.wait_for_selector("#endModal:not(.hidden)")
            pg4.click("#endConfirm")
            pg4.wait_for_function("document.getElementById('doneTitle')?.textContent === 'Interview ended'", timeout=30000)
            assert pg4.request.post(f"{BASE}/api/interviews/{CREATED[iid4]['candidate_path'].split('k=')[1]}/assistant", data={}).status == 409
            assert tracks_stopped(pg4)
            ev4 = wait(lambda: [e for e in c.get(f"/api/interviews/{iid4}").json()["events"] if e["type"] == "virtual_camera"], 20, what="virtual camera event")
            assert "OBS" in ev4[0]["detail"], ev4
            print("deliberate end: closed, no rejoin; virtual camera flagged")

            # ---------------------------------------------------------- 5. second screen + leaving the window -> warned, then stopped
            iid5 = create(c, require_screen_share=True, max_warnings=1, candidate_email="multi@example.com")
            pg5, errs5 = page_for(iid5, ANSWERS, turn_ms=2500)
            pg5.evaluate("window.__EXT = true")
            pg5.check("#consent"); pg5.click("#toCheck")
            pg5.wait_for_selector("#ckScreen.bad", timeout=15000)
            pg5.click("#shareBtn"); pg5.wait_for_selector("#ckShare.ok", timeout=15000)
            pg5.wait_for_selector("#ckMic.ok", timeout=20000); time.sleep(1)
            assert pg5.is_enabled("#startBtn") is False, "a second screen must block the start"
            pg5.evaluate("window.__EXT = false")
            pg5.wait_for_selector("#ckScreen.ok", timeout=10000)
            scan_room(pg5)
            pg5.wait_for_function("!document.getElementById('startBtn').disabled", timeout=15000)
            pg5.click("#startBtn")
            wait_question(pg5)
            time.sleep(2)
            pg5.evaluate("window.__EXT = true")                       # monitor plugged in mid-interview
            pg5.wait_for_selector("#monOverlay:not(.hidden)", timeout=10000)
            pg5.wait_for_selector("#warnBar:not(.hidden)", timeout=10000)
            assert "Final warning" in pg5.inner_text("#warnTitle"), pg5.inner_text("#warnTitle")
            pg5.evaluate("window.__EXT = false")
            pg5.wait_for_selector("#monOverlay.hidden", state="attached", timeout=10000)
            time.sleep(4.5)                                          # past the server's one-episode debounce
            pg5.evaluate("window.dispatchEvent(new Event('blur'))")  # switched to another window
            pg5.wait_for_function("document.getElementById('doneTitle')?.textContent === 'Interview stopped'", timeout=30000)
            said = pg5.evaluate("window.__said")
            print("interviewer said:", [s["text"][:60] for s in said])
            assert len(said) == 2 and said[0]["endAfter"] is False and said[1]["endAfter"] is True, said
            assert "second screen" in said[0]["text"] and "stop the interview" in said[1]["text"]
            assert tracks_stopped(pg5), "screen sharing kept running after the interview was stopped"
            r5 = wait(lambda: (lambda r: r if r.get("report") else None)(c.get(f"/api/interviews/{iid5}").json()), 60, what="disqualified interview scored")
            assert r5["disqualified"] and len(r5["warnings"]) == 2 and r5["report"]["human_review_reasons"][0].startswith("DISQUALIFIED")
            shots = [(i["reason"], i.get("source")) for i in r5["images"]]
            assert ("window_blur", "screen") in shots and ("multi_monitor", "screen") in shots, shots
            assert pg5.request.post(f"{BASE}/api/interviews/{CREATED[iid5]['candidate_path'].split('k=')[1]}/assistant", data={}).status == 409, "a disqualified candidate rejoined"
            if errs5:
                failures.append(f"disqualification page JS errors: {errs5}")
            hr.goto(f"{BASE}/app/interviews/{iid5}")
            hr.wait_for_selector(".dq", timeout=15000)
            assert hr.locator(".moment").count() >= 2
            print("second screen + window switch: warned, then stopped; screen captured:", shots)

            # ---------------------------------------------------------- 6. someone else in the room, a phone: blocked, warned, stopped
            iid6 = create(c, max_warnings=1, candidate_email="room@example.com")
            pg6, errs6 = page_for(iid6, ANSWERS, turn_ms=3000)
            pg6.evaluate("window.__PERSONS = 2")                        # a second person standing back: one face, two people
            pg6.check("#consent"); pg6.click("#toCheck")
            pg6.wait_for_selector("#ckFace.bad", timeout=20000)
            assert "someone else" in pg6.inner_text("#ckFace").lower(), pg6.inner_text("#ckFace")
            pg6.wait_for_selector("#ckMic.ok", timeout=20000)
            pg6.click("#roomBtn"); pg6.wait_for_selector("#ckRoom.bad", timeout=60000)       # the room scan finds them too
            assert pg6.is_enabled("#startBtn") is False, "someone else in the room must block the start"
            pg6.evaluate("window.__PERSONS = 1")
            pg6.wait_for_selector("#ckFace.ok", timeout=10000)
            scan_room(pg6)
            pg6.wait_for_function("!document.getElementById('startBtn').disabled", timeout=15000)
            pg6.click("#startBtn"); wait_question(pg6); time.sleep(2)
            pg6.evaluate("window.__PERSONS = 2")                        # someone walks in during the interview
            pg6.wait_for_selector("#warnBar:not(.hidden)", timeout=15000)
            assert "Final warning" in pg6.inner_text("#warnTitle"), pg6.inner_text("#warnTitle")
            pg6.evaluate("window.__PERSONS = 1"); time.sleep(6)
            pg6.evaluate("window.__PHONES = 1")                         # then a phone comes out: the interview is stopped
            pg6.wait_for_selector("#dqOverlay:not(.hidden)", timeout=25000)
            r6 = wait(lambda: (lambda r: r if r.get("disqualified") else None)(c.get(f"/api/interviews/{iid6}").json()), 30, what="room disqualification")
            kinds = [w["type"] for w in r6["warnings"]]
            assert kinds == ["multiple_people", "phone_visible"], kinds
            ev6 = {e["type"] for e in r6["events"]}
            assert {"extra_person", "phone_visible", "room_scan_failed", "room_scan_passed", "ear_check_unverified"} <= ev6, ev6
            shots6 = {i["reason"] for i in r6["images"]}
            assert {"extra_person", "phone_visible", "vision_room"} <= shots6, shots6
            if errs6:
                failures.append(f"room page JS errors: {errs6}")
            print("someone else in the room / a phone: start blocked, warned, then stopped; photos:", sorted(shots6))

            # ---------------------------------------------------------- 7. earbuds, a voice that isn't the candidate's, eyes in the lap
            iid7 = create(c, max_warnings=2, candidate_email="buds@example.com")
            pg7, errs7 = page_for(iid7, ANSWERS, turn_ms=3000)
            pg7.evaluate("window.__EXTRA_DEVICES = [{kind: 'audiooutput', label: 'Default - AirPods Pro (Bluetooth)', deviceId: 'default'}]")
            pg7.check("#consent"); pg7.click("#toCheck")
            pg7.wait_for_selector("#ckEars.bad", timeout=20000)
            assert "AirPods" in pg7.inner_text("#ckEars"), pg7.inner_text("#ckEars")
            pg7.wait_for_selector("#ckMic.ok", timeout=20000)
            time.sleep(2)
            assert pg7.is_enabled("#startBtn") is False, "connected earbuds must block the start"
            pg7.evaluate("window.__plug([])")                            # they take the earbuds out
            scan_room(pg7)
            pg7.wait_for_function("!document.getElementById('startBtn').disabled", timeout=25000)
            pg7.click("#startBtn"); wait_question(pg7); time.sleep(2)
            pg7.evaluate("window.__STILL_LIPS = 1; window.__VOICE = 1")  # a voice answers while the lips stay still
            ev = lambda: {e["type"] for e in c.get(f"/api/interviews/{iid7}").json()["events"]}
            wait(lambda: "voice_not_lips" in ev(), 30, what="voice without lip movement")
            pg7.evaluate("window.__STILL_LIPS = 0; window.__VOICE = 0; window.__EYES_DOWN = 1")
            wait(lambda: "eyes_off_screen" in ev(), 30, what="eyes held in the lap")
            pg7.evaluate("window.__EYES_DOWN = 0; window.__plug([{kind: 'audiooutput', label: 'Galaxy Buds2 Pro', deviceId: 'g'}])")   # earbuds mid-call
            pg7.wait_for_selector("#warnBar:not(.hidden)", timeout=20000)
            r7 = wait(lambda: (lambda r: r if any(w["type"] == "earphones" for w in r.get("warnings") or []) else None)(c.get(f"/api/interviews/{iid7}").json()), 30, what="earbuds warning")
            e7 = {e["type"] for e in r7["events"]}
            assert {"earphones_device", "earphones_connected", "voice_not_lips", "eyes_off_screen", "automation_detected"} <= e7, e7
            reasons = " | ".join(r7["proctoring"]["reasons"])
            assert "lips were still" in reasons and "connected during the interview" in reasons, reasons
            shots7 = {i["reason"] for i in r7["images"]}
            assert {"voice_not_lips", "eyes_off_screen"} <= shots7, shots7
            if errs7:
                failures.append(f"behaviour page JS errors: {errs7}")
            print("earbuds blocked at the start, then warned mid-call; a voice with still lips and eyes in the lap flagged:", r7["proctoring"]["risk"])
            browser.close()
    finally:
        srv.terminate()
        srv.wait(10)
    log = (Path(data) / "server.log").read_text()
    bad = [ln for ln in log.splitlines() if "Traceback" in ln or " ERROR " in ln]
    if bad:
        failures.append("server errors:\n" + "\n".join(bad[:10]) + "\n" + log[-3000:])
    if failures:
        print("\nFAILURES:\n" + "\n".join(failures))
        sys.exit(1)
    print("\nBROWSER E2E PASSED")


if __name__ == "__main__":
    main()


def pick(page, trigger, label):
    """Choose `label` in one of our styled dropdowns (a Radix listbox, not a native <select>)."""
    if isinstance(trigger, str):
        trigger = page.locator(trigger)
    trigger.click()
    page.get_by_role("option", name=label, exact=True).click()
