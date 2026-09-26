"""TalentLoop AI Interview PoC server.

Run:  uvicorn backend.main:app --host 0.0.0.0 --port 8000
"""
import asyncio
import io
import json
import logging
import os
import secrets
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import httpx  # noqa: E402
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from . import brain, llm, store  # noqa: E402
from .vapi_config import build_assistant  # noqa: E402

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

ADMIN_KEY = os.getenv("ADMIN_KEY", "").strip()
WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="TalentLoop AI Interview PoC")


def require_admin(req: Request):
    if not ADMIN_KEY:
        return
    key = req.headers.get("x-admin-key") or req.query_params.get("key")
    if key != ADMIN_KEY:
        raise HTTPException(401, "Admin key required")


def get_rec(iid: str) -> dict:
    try:
        rec = store.load(iid)
    except ValueError:
        rec = None
    if not rec:
        raise HTTPException(404, "Interview not found")
    return rec


# ---------------------------------------------------------------------------
# HR side
# ---------------------------------------------------------------------------
@app.get("/")
def root():
    return RedirectResponse("/hr.html")


@app.get("/api/health")
def health():
    return {"ok": True, "mock": llm.MOCK, "fast_model": llm.FAST_MODEL, "smart_model": llm.SMART_MODEL,
            "public_url": os.getenv("PUBLIC_URL", ""), "vapi_key_set": bool(os.getenv("VAPI_PUBLIC_KEY")),
            "admin_protected": bool(ADMIN_KEY)}


@app.post("/api/extract")
async def extract_text(req: Request, file: UploadFile = File(...)):
    require_admin(req)
    raw = await file.read()
    name = (file.filename or "").lower()
    try:
        if name.endswith(".pdf"):
            from pypdf import PdfReader
            text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(raw)).pages)
        elif name.endswith(".docx"):
            try:
                import docx  # python-docx
            except ImportError:
                raise HTTPException(400, "DOCX needs: pip install python-docx. Or upload PDF/TXT.")
            text = "\n".join(p.text for p in docx.Document(io.BytesIO(raw)).paragraphs)
        else:
            text = raw.decode("utf-8", errors="ignore")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Could not read file: {e}")
    if len(text.strip()) < 50:
        raise HTTPException(400, "Very little text found. Scanned PDF? Paste the text instead.")
    return {"text": text.strip()}


@app.post("/api/plan")
async def make_plan(req: Request):
    require_admin(req)
    inp = await req.json()
    if not inp.get("jd") or not inp.get("resume"):
        raise HTTPException(400, "jd and resume are required")
    t0 = time.time()
    try:
        plan = await brain.generate_plan(inp)
    except Exception as e:
        log.exception("plan failed")
        raise HTTPException(502, f"Plan generation failed: {e}")
    return {"plan": plan, "ms": int((time.time() - t0) * 1000)}


@app.post("/api/interviews")
async def create_interview(req: Request):
    """Body: {plan, inputs:{jd,resume,questions,...}, expires_hours}. This is also the API
    TalentLoop's main app would call with its payload."""
    require_admin(req)
    body = await req.json()
    inputs = body.get("inputs") or {}
    plan = body.get("plan")
    if not plan:
        plan = await brain.generate_plan(inputs)
    try:
        plan = brain.normalize_plan(plan)
    except Exception as e:
        raise HTTPException(400, f"Invalid plan: {e}")
    iid = secrets.token_urlsafe(9).replace("-", "x").replace("_", "y")
    rec = {"id": iid, "created_at": time.time(),
           "expires_at": time.time() + float(body.get("expires_hours", 72)) * 3600,
           "status": "created", "plan": plan, "inputs": inputs, "state": None, "snapshots": {},
           "events": [], "media": [], "vapi": {}, "report": None, "hr": {}}
    store.save(rec)
    return {"id": iid, "candidate_path": f"/interview.html?id={iid}", "report_path": f"/report.html?id={iid}"}


@app.get("/api/interviews")
def list_interviews(req: Request):
    require_admin(req)
    out = []
    for r in store.list_all():
        rep = r.get("report") or {}
        out.append({"id": r["id"], "created_at": r["created_at"], "status": r["status"],
                    "candidate": r["plan"].get("candidate_name"), "role": r["plan"].get("role"),
                    "recommendation": rep.get("recommendation"),
                    "overall": (rep.get("computed") or {}).get("overall")})
    return out


@app.get("/api/interviews/{iid}")
def get_interview(iid: str, req: Request):
    require_admin(req)
    rec = get_rec(iid)
    rec.pop("snapshots", None)
    return rec


@app.post("/api/interviews/{iid}/score")
async def rescore(iid: str, req: Request):
    require_admin(req)
    return await run_scoring(iid)


@app.post("/api/interviews/{iid}/hr")
async def save_hr_review(iid: str, req: Request):
    """HR's own scores per question: this is the calibration data (AI vs HR agreement)."""
    require_admin(req)
    body = await req.json()
    async with store.lock(iid):
        rec = get_rec(iid)
        rec["hr"] = {"scores": body.get("scores", {}), "decision": body.get("decision"),
                     "notes": body.get("notes", ""), "at": time.time()}
        store.save(rec)
    return {"ok": True}


@app.get("/api/calibration")
def calibration(req: Request):
    """Across all interviews HR has scored: how often does the AI land within +/-1 of HR?"""
    require_admin(req)
    pairs = []
    for r in store.list_all():
        hr = (r.get("hr") or {}).get("scores") or {}
        for qr in ((r.get("report") or {}).get("questions") or []):
            h = hr.get(qr.get("q_id"))
            if isinstance(qr.get("score"), (int, float)) and h not in (None, ""):
                pairs.append((qr["score"], int(h)))
    if not pairs:
        return {"pairs": 0}
    within1 = sum(1 for a, h in pairs if abs(a - h) <= 1) / len(pairs)
    exact = sum(1 for a, h in pairs if a == h) / len(pairs)
    bias = sum(a - h for a, h in pairs) / len(pairs)
    return {"pairs": len(pairs), "within_1": round(within1 * 100), "exact": round(exact * 100),
            "ai_minus_hr_avg": round(bias, 2)}


@app.get("/media/{iid}/{fname}")
def get_media(iid: str, fname: str, req: Request):
    require_admin(req)
    get_rec(iid)
    p = store.MEDIA_DIR / iid / Path(fname).name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p)


# ---------------------------------------------------------------------------
# Candidate side
# ---------------------------------------------------------------------------
def _check_open(rec: dict):
    if rec["status"] in ("completed", "scored"):
        raise HTTPException(409, "This interview has already been completed. Thank you.")
    if time.time() > rec.get("expires_at", 1e18):
        raise HTTPException(410, "This interview link has expired. Please contact HR.")


@app.get("/api/interviews/{iid}/public")
def public_info(iid: str):
    rec = get_rec(iid)
    p = rec["plan"]
    return {"candidate_name": p.get("candidate_name"), "role": p.get("role"), "company": p.get("company"),
            "duration_min": p["duration_min"], "status": rec["status"],
            "expired": time.time() > rec.get("expires_at", 1e18),
            "resuming": bool(rec.get("state")) and rec["status"] == "in_progress"}


@app.post("/api/interviews/{iid}/assistant")
async def assistant_for_call(iid: str):
    """Called by the candidate page right before vapi.start(). Opens a new session."""
    key = os.getenv("VAPI_PUBLIC_KEY", "").strip()
    if not key:
        raise HTTPException(500, "VAPI_PUBLIC_KEY not set on server")
    async with store.lock(iid):
        rec = get_rec(iid)
        _check_open(rec)
        try:
            first = brain.start_session(rec)
        except ValueError as e:
            raise HTTPException(409, str(e))
        try:
            assistant = build_assistant(iid, rec["plan"], first)
        except RuntimeError as e:
            raise HTTPException(500, str(e))
        store.save(rec)
    return {"publicKey": key, "assistant": assistant}


@app.post("/api/interviews/{iid}/started")
async def call_started(iid: str, req: Request):
    body = await req.json()
    async with store.lock(iid):
        rec = get_rec(iid)
        rec.setdefault("vapi", {}).setdefault("call_ids", []).append(body.get("call_id"))
        store.save(rec)
    return {"ok": True}


@app.post("/api/interviews/{iid}/events")
async def add_events(iid: str, req: Request):
    body = await req.json()
    evs = body if isinstance(body, list) else [body]
    async with store.lock(iid):
        rec = get_rec(iid)
        for e in evs[:200]:
            rec["events"].append({"type": str(e.get("type"))[:40], "ts": e.get("ts"), "detail": str(e.get("detail", ""))[:200]})
        store.save(rec)
    return {"ok": True}


@app.post("/api/interviews/{iid}/media")
async def upload_media(iid: str, file: UploadFile = File(...)):
    get_rec(iid)
    d = store.MEDIA_DIR / iid
    d.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "").suffix.lower()
    fname = f"candidate_{int(time.time())}{ext if ext in ('.webm', '.mp4') else '.webm'}"
    size = 0
    with open(d / fname, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > 400 * 1024 * 1024:
                raise HTTPException(413, "Recording too large")
            f.write(chunk)
    async with store.lock(iid):
        rec = get_rec(iid)
        rec["media"].append({"kind": "candidate_video", "file": fname, "bytes": size})
        store.save(rec)
    return {"ok": True, "file": fname}


@app.post("/api/interviews/{iid}/complete")
async def complete(iid: str, bg: BackgroundTasks):
    async with store.lock(iid):
        rec = get_rec(iid)
        if rec["status"] == "in_progress" and rec.get("state") and rec["state"].get("ended"):
            rec["status"] = "completed"
        store.save(rec)
    rec = get_rec(iid)
    # Score only when the interview properly ended. Dropped calls can reconnect instead.
    if rec["status"] == "completed" and not rec.get("report"):
        bg.add_task(run_scoring, iid)
    return {"ok": True, "status": rec["status"]}


async def run_scoring(iid: str) -> dict:
    rec = get_rec(iid)
    if not rec.get("state"):
        raise HTTPException(400, "Interview has not started")
    try:
        report = await brain.score_interview(rec)
    except Exception as e:
        log.exception("scoring failed")
        raise HTTPException(502, f"Scoring failed: {e}")
    async with store.lock(iid):
        rec = get_rec(iid)
        rec["report"] = report
        rec["status"] = "scored"
        store.save(rec)
    return report


# ---------------------------------------------------------------------------
# Vapi -> us
# ---------------------------------------------------------------------------
def _chunk(content: str | None, finish: str | None = None, role: bool = False) -> str:
    delta = {}
    if role:
        delta["role"] = "assistant"
    if content:
        delta["content"] = content
    obj = {"id": "chatcmpl-tl", "object": "chat.completion.chunk", "created": int(time.time()),
           "model": "talentloop-interview-brain",
           "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    return f"data: {json.dumps(obj)}\n\n"


@app.post("/llm/{iid}/chat/completions")
async def custom_llm(iid: str, req: Request):
    body = await req.json()
    messages = body.get("messages") or []
    async with store.lock(iid):
        rec = get_rec(iid)
        say = await brain.handle_turn(rec, messages)
        store.save(rec)
    log.info("[%s] AI: %s", iid, say[:120])

    if not body.get("stream", True):
        return JSONResponse({"id": "chatcmpl-tl", "object": "chat.completion", "created": int(time.time()),
                             "model": "talentloop-interview-brain",
                             "choices": [{"index": 0, "message": {"role": "assistant", "content": say},
                                          "finish_reason": "stop"}]})

    async def gen():
        yield _chunk(None, role=True)
        yield _chunk(say)
        yield _chunk(None, finish="stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/webhook/vapi/{iid}")
async def vapi_webhook(iid: str, req: Request, bg: BackgroundTasks):
    body = await req.json()
    msg = body.get("message") or {}
    if msg.get("type") == "end-of-call-report":
        art = msg.get("artifact") or {}
        url = art.get("recordingUrl") or msg.get("recordingUrl") or (art.get("recording") or {}).get("mono", {}).get("combinedUrl")
        async with store.lock(iid):
            rec = get_rec(iid)
            rec.setdefault("vapi", {})["end_report"] = {
                "endedReason": msg.get("endedReason"), "recordingUrl": url,
                "durationSeconds": msg.get("durationSeconds"), "cost": msg.get("cost"),
                "transcript": (art.get("transcript") or msg.get("transcript") or "")[:60000]}
            store.save(rec)
        if url:
            bg.add_task(download_recording, iid, url)
    return {"ok": True}


async def download_recording(iid: str, url: str):
    """Vapi keeps recordings only for a limited time on self-serve plans. Copy ours immediately."""
    try:
        d = store.MEDIA_DIR / iid
        d.mkdir(parents=True, exist_ok=True)
        ext = ".wav" if ".wav" in url else ".mp3" if ".mp3" in url else ".audio"
        fname = f"call_audio_{int(time.time())}{ext}"
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as c:
            r = await c.get(url)
            r.raise_for_status()
            (d / fname).write_bytes(r.content)
        async with store.lock(iid):
            rec = get_rec(iid)
            rec["media"].append({"kind": "call_audio", "file": fname, "bytes": len(r.content)})
            store.save(rec)
    except Exception as e:
        log.warning("recording download failed for %s: %s", iid, e)


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
