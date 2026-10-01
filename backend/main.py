"""TalentLoop AI Interview server.

Run:  uvicorn backend.main:app --host 0.0.0.0 --port 8000   (one worker: locks live in process memory)
"""
import asyncio
import io
import json
import logging
import os
import secrets
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import (FileResponse, JSONResponse, PlainTextResponse, RedirectResponse,  # noqa: E402
                               Response, StreamingResponse)
from fastapi.staticfiles import StaticFiles  # noqa: E402
from sqlalchemy import or_  # noqa: E402
from starlette.background import BackgroundTask  # noqa: E402

from . import api_accounts, api_hiring, auth, brain, db, exports, ivindex, llm, matching, media, proctor, refs, store  # noqa: E402
from .vapi_config import build_assistant, public_url  # noqa: E402

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

ADMIN_KEY = os.getenv("ADMIN_KEY", "").strip()      # optional API key for automation (acts as a platform admin)
WEAK_ADMIN = bool(ADMIN_KEY) and (ADMIN_KEY == "change-me" or len(ADMIN_KEY) < 12)
# The React frontend (frontend/, built with `npm run build`). WEB_DIR overrides it.
WEB_DIR = Path(os.getenv("WEB_DIR") or Path(__file__).resolve().parent.parent / "frontend" / "dist")
MEDIA_CAP_BYTES = int(os.getenv("MEDIA_CAP_MB", "900")) * 1024 * 1024
MAX_EVENTS = 5000
MAX_IMAGES = 300
RECONNECT_WINDOW_SEC = int(os.getenv("RECONNECT_WINDOW_SEC", "30"))
RECONNECT_GRACE_SEC = 2          # network latency allowance on top of the window
RETENTION_DAYS = float(os.getenv("RETENTION_DAYS", "0") or 0)   # 0 = keep forever
SWEEP_EVERY_SEC = float(os.getenv("SWEEP_EVERY_SEC", "30"))
FINISH_DELAY_SEC = float(os.getenv("FINISH_DELAY_SEC", "25"))   # after a disqualification
CLOSED = ("completed", "incomplete", "scored")

if WEAK_ADMIN:
    log.warning("ADMIN_KEY is weak. Use a long random string, or remove it if you don't use the API.")

db.migrate()   # idempotent: creates missing tables (also when the app is imported by tests or tools)
store.ON_SAVE.append(ivindex.sync)
store.ON_DELETE.append(ivindex.remove)
app = FastAPI(title="TalentLoop")
app.include_router(api_accounts.router)
_presence: dict[str, float] = {}     # interview id -> last heartbeat from a live call (memory only)
_sweeping: set[str] = set()
_tasks: set[asyncio.Task] = set()


@app.on_event("startup")
async def _startup():
    n = await asyncio.to_thread(store.restore_all)
    if n:
        log.info("restored %d interviews from S3", n)
    n = await asyncio.to_thread(ivindex.backfill)
    if n:
        log.info("indexed %d interviews", n)
    n = await asyncio.to_thread(matching.backfill_features)
    if n:
        log.info("computed matching features for %d candidates", n)
    await llm.resolve_models()
    if SWEEP_EVERY_SEC > 0:
        asyncio.create_task(_sweeper())


@app.middleware("http")
async def _no_stale_pages(req: Request, call_next):
    """Pages, scripts, styles and samples must be revalidated on every load (cheap: ETag -> 304). Without a
    Cache-Control header browsers guess a lifetime and can pair a new page with an old script after a deploy,
    which breaks the page."""
    resp = await call_next(req)
    p = req.url.path
    if req.method != "GET" or p.startswith(("/api/", "/media/", "/llm/", "/webhook/")):
        return resp
    if p.startswith("/assets/") and resp.status_code == 200:
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"   # content-hashed file names
    elif p == "/" or p.endswith((".html", ".js", ".mjs", ".css", ".json")) or "." not in p.rsplit("/", 1)[-1]:   # app routes serve index.html
        resp.headers["Cache-Control"] = "no-cache"
    return resp


def require_admin(req: Request) -> auth.Ctx:
    """A signed-in team member (any role) or the ADMIN_KEY. Interview access is then checked per record."""
    with db.session() as s:
        ctx = auth.current(req, s)
        if not ctx.via_key and not ctx.org_id and not ctx.platform_admin:
            raise HTTPException(403, "Join or create a company workspace first.")
        ctx.visible_jobs = auth.visible_job_ids(s, ctx)   # type: ignore[attr-defined]
        return ctx


def can_see_interview(ctx: auth.Ctx, rec: dict) -> bool:
    if ctx.via_key:
        return True
    org = rec.get("org_id")
    if org is None:                       # created before companies existed
        return ctx.platform_admin
    if org != ctx.org_id:
        return False
    vis = getattr(ctx, "visible_jobs", None)
    return vis is None or rec.get("job_id") in vis or rec.get("created_by") == ctx.user_id


def resolve_iid(ctx: auth.Ctx, key: str) -> str:
    """Interview id for a readable ref (rohan-mehta-7) in this company, or the id itself."""
    if store._valid(key) and not refs.number_of(key):
        return key
    with db.session() as s:
        row = refs.resolve(s, db.InterviewIndex, ctx.org_id, key)
        return row.id if row else key


def hr_rec(iid: str, req: Request, manage: bool = False) -> tuple[auth.Ctx, dict]:
    ctx = require_admin(req)
    rec = get_rec(resolve_iid(ctx, iid))
    if not can_see_interview(ctx, rec):
        raise HTTPException(404, "Interview not found")
    if manage and not (ctx.has(auth.MANAGE_JOBS) or rec.get("created_by") == ctx.user_id):
        raise HTTPException(403, "Your role can't change this interview.")
    return ctx, rec


def get_rec(iid: str) -> dict:
    try:
        rec = store.load(iid)
    except ValueError:
        rec = None
    if not rec:
        raise HTTPException(404, "Interview not found")
    rec.setdefault("settings", {})
    rec.setdefault("sessions", [])
    rec.setdefault("images", [])
    return rec


def client_ip(req: Request) -> str:
    fwd = req.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else (req.client.host if req.client else "")) or "?"


def server_event(rec: dict, typ: str, detail: str = "") -> None:
    rec.setdefault("events", []).append({"type": typ, "ts": None, "server_ts": time.time(), "detail": detail[:200],
                                         "source": "server"})


def _spoke(rec: dict) -> bool:
    return any(e["role"] == "candidate" for e in (rec.get("state") or {}).get("log", []))


def last_activity(rec: dict) -> float:
    st = rec.get("state") or {}
    ts = [e.get("ts") or 0 for e in st.get("log", [])[-3:]]
    return max([_presence.get(rec["id"], 0), rec.get("last_seen", 0)] + ts)


def reconnect_window(rec: dict) -> int:
    return int(rec.get("settings", {}).get("reconnect_window_sec") or RECONNECT_WINDOW_SEC)


# ---------------------------------------------------------------------------
# HR side
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"ok": True, "mock": llm.MOCK, "fast_model": llm.FAST_MODEL, "smart_model": llm.SMART_MODEL,
            "llm_provider": "openrouter" if llm.OPENROUTER else ("custom" if llm.BASE_URL else "openai"),
            "llm_key_set": bool(llm.API_KEY), "fast_chain": llm.FAST_CHAIN, "smart_chain": llm.SMART_CHAIN,
            "free_models": any(m.endswith(":free") or m == "openrouter/free" for m in llm.FAST_CHAIN + llm.SMART_CHAIN),
            "model_note": llm.MODEL_CHECK["note"],
            "public_url": public_url(), "app_url": (os.getenv("APP_URL") or "").strip().rstrip("/"), "vapi_key_set": bool(os.getenv("VAPI_PUBLIC_KEY")),
            "vapi_private_key_set": bool(os.getenv("VAPI_PRIVATE_KEY")),
            "admin_protected": True, "admin_weak": WEAK_ADMIN, "platform": api_accounts.platform_status(),
            "storage": {"s3": store.S3_ENABLED, "s3_error": store.S3_STATUS["last_error"],
                        "persistent_disk": os.getenv("PERSISTENT_DISK", "") == "1"},
            "ffmpeg": bool(media.ffmpeg_exe()), "reconnect_window_sec": RECONNECT_WINDOW_SEC}


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
    return {"plan": plan, "warnings": brain.plan_warnings(plan, inp.get("questions")),
            "ms": int((time.time() - t0) * 1000)}


def _intish(v, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _settings(body: dict) -> dict:
    s = body.get("settings") or {}
    out = {"candidate_email": str(s.get("candidate_email") or "")[:200],
           "require_screen_share": bool(s.get("require_screen_share")),
           "reconnect_window_sec": max(10, min(900, int(s.get("reconnect_window_sec") or RECONNECT_WINDOW_SEC))),
           "face_detection": s.get("face_detection", True) is not False,
           "snapshots": s.get("snapshots", True) is not False,
           "enforce_focus": s.get("enforce_focus", True) is not False,
           "block_multi_monitor": s.get("block_multi_monitor", True) is not False,
           "max_warnings": max(0, min(5, _intish(s.get("max_warnings"), 2))),
           "hr_note": str(s.get("hr_note") or "")[:500]}
    af = s.get("available_from")
    out["available_from"] = float(af) if isinstance(af, (int, float)) and af > 0 else None
    return out


@app.post("/api/interviews")
async def create_interview(req: Request):
    """Body: {plan, inputs:{jd,resume,questions,...}, expires_hours, settings}. This is also the API
    TalentLoop's main app would call with its payload."""
    ctx = require_admin(req)
    body = await req.json()
    job_id = str(body.get("job_id") or "") or None
    cand_id = str(body.get("candidate_id") or "") or None
    with db.session() as s:
        job = refs.resolve(s, db.Job, ctx.org_id, job_id) if job_id else None
        if job_id and (not job or not auth.job_permission(s, ctx, job)):
            raise HTTPException(404, "Job not found")
        if not ctx.has(auth.MANAGE_JOBS) and not (job and auth.job_permission(s, ctx, job) in ("manage", "edit")):
            raise HTTPException(403, "Your role can't create interviews.")
        job_id = job.id if job else None
        if cand_id:
            cand = refs.resolve(s, db.Candidate, ctx.org_id, cand_id)
            cand_id = cand.id if cand else None
    inputs = body.get("inputs") or {}
    plan = body.get("plan")
    if not plan:
        plan = await brain.generate_plan(inputs)
    try:
        plan = brain.normalize_plan(plan)
    except Exception as e:
        raise HTTPException(400, f"Invalid plan: {e}")
    iid = secrets.token_urlsafe(9).replace("-", "x").replace("_", "y")
    now = time.time()
    settings = _settings(body)
    starts = settings["available_from"] or now
    rec = {"id": iid, "created_at": now, "org_id": ctx.org_id, "created_by": ctx.user_id, "job_id": job_id,
           "candidate_id": cand_id, "application_id": str(body.get("application_id") or "") or None,
           "expires_at": starts + max(0.5, float(body.get("expires_hours") or 72)) * 3600,
           "status": "created", "plan": plan, "inputs": inputs, "state": None, "snapshots": [],
           "events": [], "media": [], "images": [], "sessions": [], "vapi": {}, "report": None, "hr": {},
           "scoring": None, "settings": settings}
    store.save(rec)
    if rec["application_id"]:
        with db.session() as s:
            app_ = s.get(db.Application, rec["application_id"])
            if app_ and app_.org_id == ctx.org_id:
                app_.interview_id = iid
                if app_.stage in ("applied", "screening", "shortlisted"):
                    app_.stage = "interview"
    with db.session() as s:
        row = s.get(db.InterviewIndex, iid)
        ref = ivindex.ref_of(row) if row else iid
    return {"id": iid, "ref": ref, "candidate_path": f"/interview.html?id={iid}", "report_path": f"/app/interviews/{ref}",
            "warnings": _history_warnings(settings["candidate_email"], iid, org_id=ctx.org_id, all_orgs=ctx.via_key)}


def _history_warnings(email: str, skip: str = "", org_id: str | None = None, all_orgs: bool = False) -> list[str]:
    email = (email or "").strip().lower()
    if not email:
        return []
    out = []
    with db.session() as s:
        q = s.query(db.InterviewIndex).filter(db.InterviewIndex.email == email, db.InterviewIndex.id != skip)
        if not all_orgs:                                    # a company only sees its own history
            q = q.filter(db.InterviewIndex.org_id == org_id)
        for r in q:
            sm = r.summary or {}
            if sm.get("disqualified"):
                out.append(f"This email was disqualified in an earlier interview ({r.role}, "
                           f"{time.strftime('%d %b %Y', time.localtime(sm.get('dq_at') or 0))}): {sm.get('dq_reason', '')}")
    return out


@app.get("/api/candidates/history")
def candidate_history(req: Request, email: str = ""):
    """Lets the HR form warn before a link is sent to a previously disqualified candidate."""
    ctx = require_admin(req)
    return {"warnings": _history_warnings(email, org_id=ctx.org_id, all_orgs=ctx.via_key)}


def visible_index(ctx: auth.Ctx, s) -> list[db.InterviewIndex]:
    q = s.query(db.InterviewIndex)
    if not ctx.via_key:
        q = q.filter(db.InterviewIndex.org_id == ctx.org_id) if ctx.org_id else q.filter(db.InterviewIndex.id == "")
        vis = getattr(ctx, "visible_jobs", None)
        if vis is not None:
            q = q.filter(or_(db.InterviewIndex.job_id.in_(vis or [""]), db.InterviewIndex.created_by == ctx.user_id))
    rows = q.order_by(db.InterviewIndex.created_at.desc()).all()
    if ctx.platform_admin and not ctx.via_key:     # interviews created before companies existed
        rows += s.query(db.InterviewIndex).filter(db.InterviewIndex.org_id.is_(None)).order_by(db.InterviewIndex.created_at.desc()).all()
    return rows


@app.get("/api/interviews")
def list_interviews(req: Request):
    ctx = require_admin(req)
    with db.session() as s:
        return [ivindex.row_json(r) for r in visible_index(ctx, s)]


@app.get("/api/interviews.csv")
def interviews_csv(req: Request):
    ctx = require_admin(req)
    with db.session() as s:
        ids = [r.id for r in visible_index(ctx, s)]
    recs = [r for r in (store.load(i) for i in ids) if r]
    return Response(exports.interviews_csv(recs), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="interviews_{time.strftime("%Y%m%d")}.csv"'})


@app.get("/api/interviews/{iid}")
def get_interview(iid: str, req: Request):
    ctx, rec = hr_rec(iid, req)
    out = exports.public_record(rec)
    if rec.get("state"):
        out["proctoring"] = proctor.summary(rec)
        out["stats"] = proctor.stats(rec)
        out["started_at"] = proctor.interview_start(rec)
    out["reconnect_window_sec"] = reconnect_window(rec)
    return out


@app.get("/api/interviews/{iid}/proctoring")
def get_proctoring(iid: str, req: Request):
    ctx, rec = hr_rec(iid, req)
    return {"proctoring": proctor.summary(rec), "stats": proctor.stats(rec) if rec.get("state") else None}


@app.get("/api/interviews/{iid}/report.pdf")
async def report_pdf(iid: str, req: Request):
    ctx, rec = hr_rec(iid, req)
    pdf = await asyncio.to_thread(exports.report_pdf, rec)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{exports.base_name(rec)}_report.pdf"'})


@app.get("/api/interviews/{iid}/transcript.txt")
def transcript_txt(iid: str, req: Request):
    ctx, rec = hr_rec(iid, req)
    return PlainTextResponse(exports.transcript_text(rec), headers={
        "Content-Disposition": f'attachment; filename="{exports.base_name(rec)}_transcript.txt"'})


@app.get("/api/interviews/{iid}/export.json")
def export_json(iid: str, req: Request):
    ctx, rec = hr_rec(iid, req)
    data = exports.public_record(rec)
    if rec.get("state"):
        data["proctoring"] = proctor.summary(rec)
        data["stats"] = proctor.stats(rec)
    return Response(json.dumps(data, indent=1, ensure_ascii=False), media_type="application/json", headers={
        "Content-Disposition": f'attachment; filename="{exports.base_name(rec)}.json"'})


@app.get("/api/interviews/{iid}/bundle.zip")
async def bundle(iid: str, req: Request):
    ctx, rec = hr_rec(iid, req)
    fd, tmp = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    await asyncio.to_thread(exports.bundle_zip, rec, Path(tmp))
    return FileResponse(tmp, media_type="application/zip", filename=f"{exports.base_name(rec)}.zip",
                        background=BackgroundTask(lambda: os.unlink(tmp)))


@app.delete("/api/interviews/{iid}")
async def delete_interview(iid: str, req: Request):
    """The consent screen promises deletion on request. This deletes our copy (and the S3 copy).
    Vapi and the LLM provider keep their own copies under their retention policies."""
    hr_rec(iid, req, manage=True)
    async with store.lock(iid):
        get_rec(iid)
        await asyncio.to_thread(store.delete, iid)
    _presence.pop(iid, None)
    return {"ok": True}


@app.post("/api/interviews/{iid}/score")
async def rescore(iid: str, req: Request, bg: BackgroundTasks):
    """Runs in the background: scoring can take longer than a proxy's request timeout."""
    ctx, rec = hr_rec(iid, req, manage=True)
    if not rec.get("state"):
        raise HTTPException(400, "Interview has not started")
    bg.add_task(run_scoring, iid, True)
    return {"ok": True, "status": "scoring"}


@app.post("/api/interviews/{iid}/close")
async def close_interview(iid: str, req: Request, bg: BackgroundTasks):
    """HR closes an interview the candidate abandoned, without waiting for the sweeper."""
    hr_rec(iid, req, manage=True)
    async with store.lock(iid):
        rec = get_rec(iid)
        if rec["status"] in ("created", "in_progress"):
            rec["status"] = "incomplete" if rec.get("state") else "cancelled"
            rec["ended_early"] = bool(rec.get("state"))
            server_event(rec, "closed_by_hr")
            store.save(rec)
    if rec.get("state"):
        bg.add_task(_finish_up, iid)
    return {"ok": True, "status": rec["status"]}


@app.post("/api/interviews/{iid}/hr")
async def save_hr_review(iid: str, req: Request):
    """HR's own scores per question: this is the calibration data (AI vs HR agreement)."""
    ctx, _ = hr_rec(iid, req)
    body = await req.json()
    async with store.lock(iid):
        rec = get_rec(iid)
        rec["hr"] = {"scores": body.get("scores", {}), "decision": body.get("decision"),
                     "notes": str(body.get("notes", ""))[:5000], "at": time.time()}
        store.save(rec)
    return {"ok": True}


@app.get("/api/calibration")
def calibration(req: Request):
    """Across all interviews HR has scored: how often does the AI land within +/-1 of HR?"""
    ctx = require_admin(req)
    pairs = []
    with db.session() as s:
        ids = [r.id for r in visible_index(ctx, s) if r.status == "scored"]
    for r in (store.load(i) for i in ids):
        if not r:
            continue
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
async def get_media(iid: str, fname: str, req: Request):
    ctx, rec = hr_rec(iid, req)
    try:
        name = store.safe_name(fname)
    except ValueError:
        raise HTTPException(400, "bad file name")
    known = {m["file"] for m in rec.get("media", [])} | {s["file"] for s in rec.get("images", [])}
    if name not in known:
        raise HTTPException(404)
    p = await asyncio.to_thread(store.media_path, iid, name)
    if not p:
        raise HTTPException(404, "File not found. On a host without persistent storage it may have been wiped by a restart.")
    if req.query_params.get("download"):
        return FileResponse(p, filename=f"{exports.base_name(rec)}_{name}")
    return FileResponse(p)  # supports Range requests, so the video scrub bar works


# ---------------------------------------------------------------------------
# Candidate side
# ---------------------------------------------------------------------------
def _check_open(rec: dict):
    if rec.get("disqualified"):
        raise HTTPException(409, "This interview was ended because the interview rules were broken after "
                                 "warnings. Please contact HR.")
    if rec["status"] == "incomplete":
        raise HTTPException(409, "This interview was closed because the connection was not restored in time. "
                                 "Please contact HR.")
    if rec["status"] in CLOSED or rec["status"] == "cancelled":
        raise HTTPException(409, "This interview has already been completed. Thank you.")
    af = rec.get("settings", {}).get("available_from")
    if af and time.time() < af:
        raise HTTPException(425, "This interview is not open yet.")
    if time.time() > rec.get("expires_at", 1e18):
        raise HTTPException(410, "This interview link has expired. Please contact HR.")


@app.get("/api/interviews/{iid}/public")
def public_info(iid: str):
    rec = get_rec(iid)
    p = rec["plan"]
    s = rec["settings"]
    resuming = rec["status"] == "in_progress" and _spoke(rec)
    deadline = last_activity(rec) + reconnect_window(rec) if resuming else None
    # Deliberately no question count and no duration: the candidate is not told either.
    return {"candidate_name": p.get("candidate_name"), "role": p.get("role"), "company": p.get("company"),
            "status": rec["status"], "disqualified": bool(rec.get("disqualified")),
            "enforce_focus": s.get("enforce_focus", True), "block_multi_monitor": s.get("block_multi_monitor", True),
            "max_warnings": s.get("max_warnings", 2),
            "expired": time.time() > rec.get("expires_at", 1e18),
            "available_from": s.get("available_from"), "not_open_yet": bool(s.get("available_from") and time.time() < s["available_from"]),
            "require_screen_share": bool(s.get("require_screen_share")),
            "face_detection": s.get("face_detection", True), "snapshots": s.get("snapshots", True),
            "reconnect_window_sec": reconnect_window(rec), "resuming": resuming,
            "reconnect_seconds_left": max(0, int(deadline - time.time())) if deadline else None,
            "server_time": time.time()}


@app.post("/api/interviews/{iid}/consent")
async def consent(iid: str, req: Request):
    body = await req.json()
    async with store.lock(iid):
        rec = get_rec(iid)
        rec.setdefault("consents", []).append({"at": time.time(), "ip": client_ip(req),
                                               "ua": req.headers.get("user-agent", "")[:300],
                                               "version": str(body.get("version", ""))[:40]})
        rec["consent"] = rec["consents"][0]
        store.save(rec)
    return {"ok": True}


@app.post("/api/interviews/{iid}/device")
async def device_info(iid: str, req: Request):
    body = await req.json()
    allowed = ("platform", "screen", "window", "extended_display", "screens", "timezone", "language", "cores",
               "memory_gb", "touch", "browser", "camera", "microphone", "connection")
    async with store.lock(iid):
        rec = get_rec(iid)
        rec["device"] = {k: str(body.get(k))[:200] for k in allowed if k in body}
        store.save(rec)
    return {"ok": True}


@app.post("/api/interviews/{iid}/assistant")
async def assistant_for_call(iid: str, req: Request, bg: BackgroundTasks):
    """Called by the candidate page right before vapi.start(). Opens a new call session.
    A candidate who spoke and then dropped can rejoin only within the reconnect window."""
    key = os.getenv("VAPI_PUBLIC_KEY", "").strip()
    if not key:
        raise HTTPException(500, "VAPI_PUBLIC_KEY not set on server")
    ip, ua = client_ip(req), req.headers.get("user-agent", "")[:300]
    async with store.lock(iid):
        rec = get_rec(iid)
        _check_open(rec)
        st = rec.get("state")
        if st and not st.get("ended") and _spoke(rec):
            gap = time.time() - last_activity(rec)
            if gap > reconnect_window(rec) + RECONNECT_GRACE_SEC:
                rec["status"] = "incomplete"
                rec["ended_early"] = True
                server_event(rec, "reconnect_denied", f"tried to rejoin {int(gap)}s after dropping")
                store.save(rec)
                bg.add_task(_finish_up, iid)
                raise HTTPException(410, f"The {reconnect_window(rec)}-second window to rejoin has passed, so this "
                                         "interview is now closed. Please contact HR if this was a technical problem.")
        try:
            first = brain.start_session(rec)
        except ValueError as e:
            raise HTTPException(409, str(e))
        try:
            assistant = build_assistant(iid, rec["plan"], first, rec["state"]["token"])
        except RuntimeError as e:
            raise HTTPException(500, str(e))
        prev = rec["sessions"][-1] if rec["sessions"] else None
        if prev and prev.get("spoke"):
            if prev.get("ua") != ua:
                server_event(rec, "device_changed", f"{prev.get('ua', '')[:80]} -> {ua[:80]}")
            if prev.get("ip") != ip:
                server_event(rec, "ip_changed", f"{prev.get('ip')} -> {ip}")
        for s in rec["sessions"]:
            s["spoke"] = s.get("spoke") or _spoke(rec)
        rec["sessions"].append({"n": rec["state"]["session"], "at": time.time(), "ip": ip, "ua": ua})
        server_event(rec, "session_start", f"session {rec['state']['session']} from {ip}")
        rec["last_seen"] = time.time()
        store.save(rec)
    _presence[iid] = time.time()
    return {"publicKey": key, "assistant": assistant, "reconnect_window_sec": reconnect_window(rec)}


@app.post("/api/interviews/{iid}/started")
async def call_started(iid: str, req: Request):
    body = await req.json()
    async with store.lock(iid):
        rec = get_rec(iid)
        cid = str(body.get("call_id") or "")[:80]
        if cid:
            rec.setdefault("vapi", {}).setdefault("call_ids", []).append(cid)
        store.save(rec)
    return {"ok": True}


@app.post("/api/interviews/{iid}/heartbeat")
async def heartbeat(iid: str):
    """Every few seconds while the call is live. Only live-call signals (this, and interview turns)
    count as presence; other uploads after a drop must not keep the reconnect window open."""
    rec = get_rec(iid)
    now = time.time()
    if rec["status"] == "in_progress":
        _presence[iid] = now
        if now - rec.get("last_seen", 0) > 20:  # persist occasionally, survives a server restart
            async with store.lock(iid):
                r = get_rec(iid)
                r["last_seen"] = now
                store.save(r)
    return {"ok": True, "status": rec["status"]}


@app.get("/api/interviews/{iid}/progress")
def progress(iid: str):
    """What the candidate's screen shows: the question being asked now. No counts, no timer."""
    rec = get_rec(iid)
    st = rec.get("state") or {}
    return {"status": rec["status"], "ended": bool(st.get("ended")), "disqualified": bool(rec.get("disqualified")),
            "question": st.get("display"), "warnings": len(rec.get("warnings") or []),
            "max_warnings": rec["settings"].get("max_warnings", 2)}


VIOLATION_KINDS = ("tab_hidden", "window_blur", "multi_monitor")
VIOLATION_DEBOUNCE_SEC = 4


@app.post("/api/interviews/{iid}/violation")
async def violation(iid: str, req: Request):
    """The candidate left the interview (tab/window switch) or connected a second screen during a live call.
    The count lives on the server, so closing or reloading the page does not reset it. The page speaks the
    returned words through the interviewer's voice; on the last one the call ends and the interview is
    closed as disqualified. The custom-LLM endpoint also refuses to continue a disqualified interview,
    so a tampered page cannot carry on."""
    body = await req.json()
    kind = str(body.get("type") or "")
    if kind not in VIOLATION_KINDS:
        raise HTTPException(400, "unknown violation type")
    detail = str(body.get("detail") or "")[:200]
    async with store.lock(iid):
        rec = get_rec(iid)
        s = rec["settings"]
        st = rec.get("state") or {}
        enforced = s.get("block_multi_monitor", True) if kind == "multi_monitor" else s.get("enforce_focus", True)
        if rec.get("disqualified"):
            return {"action": "terminate", "say": "", "warning": len(rec.get("warnings") or []), "already": True}
        if rec["status"] != "in_progress" or not st or st.get("ended") or not enforced:
            return {"action": "ignored", "say": "", "warning": len(rec.get("warnings") or [])}
        warns = rec.setdefault("warnings", [])
        now = time.time()
        if warns and now - warns[-1]["at"] < VIOLATION_DEBOUNCE_SEC:
            return {"action": "ignored", "say": "", "warning": len(warns), "debounced": True}
        max_w = int(s.get("max_warnings", 2))
        n = len(warns) + 1
        disp = st.get("display") or {}
        question = disp.get("text", "") if disp.get("kind") != "closing" else ""
        say, terminate = brain.integrity_message(rec["plan"], kind, n, max_w, question)
        q_id = (st.get("display") or {}).get("q_id")
        warns.append({"n": n, "type": kind, "at": now, "say": say, "q_id": q_id, "detail": detail,
                      "action": "terminate" if terminate else "warn"})
        server_event(rec, "integrity_warning", f"warning {n} of {max_w}: {kind} {detail}".strip())
        if terminate:
            what = brain.VIOLATION_WHAT.get(kind, kind)
            during = f", during {brain.question_label(rec['plan'], q_id)}" if q_id else ""
            after = f"after {max_w} warning{'' if max_w == 1 else 's'}" if max_w else "with no warnings allowed"
            rec["disqualified"] = {"at": now, "type": kind, "violations": n,
                                   "reason": f"{what[0].upper() + what[1:]} {after}{during}"}
            rec["status"] = "incomplete"
            rec["ended_early"] = True
            server_event(rec, "disqualified", f"after {n} violation(s)")
        rec["last_seen"] = now
        store.save(rec)
    log.info("[%s] integrity %s #%d (%s)", iid, "TERMINATE" if terminate else "warning", n, kind)
    if terminate:
        # Detached, not a request background task: the request finishes now and a shutdown isn't held up.
        # If the server restarts first, the sweeper scores the interview instead.
        t = asyncio.create_task(_finish_up_later(iid))
        _tasks.add(t)
        t.add_done_callback(_tasks.discard)
    return {"action": "terminate" if terminate else "warn", "say": say, "warning": n, "max_warnings": max_w}


async def _finish_up_later(iid: str):
    """Give the page time to finish speaking and upload the last recording pieces."""
    await asyncio.sleep(FINISH_DELAY_SEC)
    await _finish_up(iid)


@app.post("/api/interviews/{iid}/events")
async def add_events(iid: str, req: Request):
    body = await req.json()
    now_ms = time.time() * 1000
    if isinstance(body, dict) and "events" in body:
        evs, sent_at = body.get("events") or [], body.get("sent_at")
    else:
        evs, sent_at = (body if isinstance(body, list) else [body]), None
    offset = (now_ms - sent_at) if isinstance(sent_at, (int, float)) else None
    async with store.lock(iid):
        rec = get_rec(iid)
        if offset is not None:
            rec["clock_offset_ms"] = offset
        room = MAX_EVENTS - len(rec["events"])
        for e in [e for e in evs if isinstance(e, dict)][:max(0, min(300, room))]:
            ts = e.get("ts") if isinstance(e.get("ts"), (int, float)) else None
            ev = {"type": str(e.get("type"))[:40], "ts": ts, "detail": str(e.get("detail", ""))[:200]}
            if ts is not None and offset is not None:
                ev["server_ts"] = (ts + offset) / 1000
            rec["events"].append(ev)
        store.save(rec)
    return {"ok": True}


@app.post("/api/interviews/{iid}/snapshot")
async def snapshot(iid: str, req: Request, reason: str = "periodic", source: str = "camera"):
    """source=camera: the candidate's webcam. source=screen: a frame of the shared screen, taken e.g. the
    moment the candidate switches away, so HR sees what was on the screen."""
    data = await req.body()
    source = "screen" if source == "screen" else "camera"
    cap = 700 * 1024 if source == "screen" else 400 * 1024
    if not data.startswith(b"\xff\xd8") or len(data) > cap:
        raise HTTPException(400, f"JPEG under {cap // 1024} KB expected")
    reason = "".join(c for c in reason if c.isalnum() or c == "_")[:30] or "periodic"
    async with store.lock(iid):
        rec = get_rec(iid)
        if rec["status"] in CLOSED and time.time() - rec.get("last_seen", 0) > 120:
            raise HTTPException(409, "Interview closed")
        if len(rec["images"]) >= MAX_IMAGES:
            return {"ok": False, "reason": "limit"}
        fname = f"snap_{len(rec['images']) + 1:03d}_{'screen_' if source == 'screen' else ''}{reason}.jpg"
        d = store.MEDIA_DIR / iid
        d.mkdir(parents=True, exist_ok=True)
        (d / fname).write_bytes(data)
        rec["images"].append({"file": fname, "at": time.time(), "reason": reason, "bytes": len(data), "source": source})
        store.save(rec)
    if store.S3_ENABLED:
        asyncio.get_running_loop().run_in_executor(None, _quiet_upload, iid, fname)
    return {"ok": True}


def _quiet_upload(iid: str, fname: str):
    try:
        store.upload_media(iid, fname)
    except Exception:
        pass


@app.post("/api/interviews/{iid}/media/chunk")
async def upload_media_chunk(iid: str, req: Request, rid: str, seq: int, ext: str = "webm", kind: str = "camera",
                             chunk_sec: float = 5):
    """The browser uploads recordings in 5-second pieces DURING the interview, so a closed tab or a dead
    laptop loses seconds, not the whole video. Pieces must arrive in order; MediaRecorder pieces
    concatenated in order form one stream, which is remuxed into a seekable file when the call ends."""
    if not rid.isalnum() or len(rid) > 24 or seq < 0:
        raise HTTPException(400, "bad chunk id")
    kind = "screen" if kind == "screen" else "camera"
    data = await req.body()
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, "Chunk too large")
    fname = f"{kind}_{rid}.{'mp4' if ext == 'mp4' else 'webm'}"
    async with store.lock(iid):
        rec = get_rec(iid)
        if time.time() > rec.get("expires_at", 1e18) + 86400:
            raise HTTPException(410, "Interview expired")
        entry = next((m for m in rec["media"] if m.get("rid") == rid), None)
        if entry and (entry.get("finalized") or entry.get("finalizing")):
            raise HTTPException(409, "recording already finalized")
        total = sum(m.get("bytes", 0) for m in rec["media"])
        if total + len(data) > MEDIA_CAP_BYTES:
            raise HTTPException(413, "Recording storage limit reached")
        expected = entry["next_seq"] if entry else 0
        if seq < expected:
            return {"ok": True, "duplicate": True}
        if seq > expected:
            raise HTTPException(409, f"expected chunk {expected}")
        d = store.MEDIA_DIR / iid
        d.mkdir(parents=True, exist_ok=True)
        with open(d / fname, "ab") as f:
            f.write(data)
        now = time.time()
        if not entry:
            entry = {"kind": "candidate_video" if kind == "camera" else "screen_video", "file": fname, "bytes": 0,
                     "rid": rid, "next_seq": 0, "started_at": now - max(0.5, min(30, chunk_sec)),
                     "session": (rec.get("state") or {}).get("session")}
            rec["media"].append(entry)
        entry["bytes"] += len(data)
        entry["next_seq"] = seq + 1
        entry["last_chunk_at"] = now
        store.save(rec)
    return {"ok": True}


@app.post("/api/interviews/{iid}/complete")
async def complete(iid: str, bg: BackgroundTasks, req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    async with store.lock(iid):
        rec = get_rec(iid)
        if rec["status"] == "in_progress" and rec.get("state") and rec["state"].get("ended"):
            rec["status"] = "completed"
        elif rec["status"] == "in_progress" and isinstance(body, dict) and body.get("ended_by_candidate"):
            rec["status"] = "incomplete"       # a deliberate "End interview" closes it; no rejoin
            rec["ended_early"] = True
            server_event(rec, "ended_by_candidate")
        store.save(rec)
    # The browser has finished uploading, so its recordings can be finalized now.
    bg.add_task(media.finalize_media, iid)
    if rec["status"] in ("completed", "incomplete") and not rec.get("report"):
        bg.add_task(run_scoring, iid)
    left = None
    if rec["status"] == "in_progress" and _spoke(rec):
        left = max(0, int(last_activity(rec) + reconnect_window(rec) - time.time()))
    return {"ok": True, "status": rec["status"], "reconnect_window_sec": reconnect_window(rec),
            "reconnect_seconds_left": left}


@app.post("/api/interviews/{iid}/feedback")
async def feedback(iid: str, req: Request):
    body = await req.json()
    try:
        rating = max(1, min(5, int(body.get("rating"))))
    except (TypeError, ValueError):
        raise HTTPException(400, "rating 1-5 required")
    async with store.lock(iid):
        rec = get_rec(iid)
        if rec["status"] == "created":
            raise HTTPException(409, "Interview not taken")
        if rec.get("feedback"):
            return {"ok": True, "duplicate": True}
        rec["feedback"] = {"rating": rating, "comment": str(body.get("comment", ""))[:1000], "at": time.time()}
        store.save(rec)
    return {"ok": True}


async def run_scoring(iid: str, force: bool = False) -> None:
    """Background scoring with a guard, so the browser's /complete, the Vapi webhook, the sweeper and
    an HR click don't pay for several identical scoring runs. Failures are saved for the report page."""
    async with store.lock(iid):
        try:
            rec = get_rec(iid)
        except HTTPException:
            return
        sc = rec.get("scoring") or {}
        if not rec.get("state") or not _spoke(rec) or (rec.get("report") and not force):
            return
        if sc.get("state") == "running" and time.time() - sc.get("at", 0) < 600:
            return
        rec["scoring"] = {"state": "running", "at": time.time()}
        store.save(rec)
    try:
        report = await brain.score_interview(rec)
        err = None
    except Exception as e:
        log.exception("scoring failed for %s", iid)
        report, err = None, str(e)[:300]
    async with store.lock(iid):
        try:
            rec = get_rec(iid)
        except HTTPException:
            return
        if report:
            rec["report"] = report
            if rec["status"] in ("completed", "incomplete"):
                rec["status"] = "scored"
            rec["scoring"] = None
        else:
            rec["scoring"] = {"state": "failed", "at": time.time(), "error": err}
        store.save(rec)


async def _finish_up(iid: str):
    await media.finalize_media(iid)
    await run_scoring(iid)


# ---------------------------------------------------------------------------
# Background sweeper: abandoned calls, unfinished recordings, Vapi cloud video, retention
# ---------------------------------------------------------------------------
async def sweep_once() -> None:
    now = time.time()
    with db.session() as s:
        work = [r.id for r in s.query(db.InterviewIndex.id, db.InterviewIndex.summary) if (r.summary or {}).get("needs_sweep")]
        if RETENTION_DAYS:
            work += [i for (i,) in s.query(db.InterviewIndex.id).filter(db.InterviewIndex.created_at < now - RETENTION_DAYS * 86400)]
    for iid in dict.fromkeys(work):
        rec = store.load(iid)
        if not rec:
            ivindex.remove(iid)
            continue
        if iid in _sweeping:
            continue
        _sweeping.add(iid)
        try:
            rec.setdefault("settings", {})
            if RETENTION_DAYS and now - rec.get("created_at", now) > RETENTION_DAYS * 86400:
                async with store.lock(iid):
                    await asyncio.to_thread(store.delete, iid)
                log.info("[%s] deleted by retention policy", iid)
                continue
            st = rec.get("state") or {}
            if rec["status"] == "in_progress" and not st.get("ended") and _spoke(rec):
                if now - last_activity(rec) > reconnect_window(rec) + 60:
                    async with store.lock(iid):
                        r = get_rec(iid)
                        if r["status"] == "in_progress":
                            r["status"] = "incomplete"
                            r["ended_early"] = True
                            server_event(r, "abandoned", "candidate did not rejoin within the window")
                            store.save(r)
                    log.info("[%s] marked incomplete (candidate did not return)", iid)
                    await _finish_up(iid)
                    continue
            if rec["status"] in CLOSED:
                if any(m.get("rid") and not m.get("finalized") for m in rec.get("media", [])):
                    await media.finalize_media(iid, only_idle_sec=45)
                if rec["status"] in ("completed", "incomplete") and not rec.get("report") and \
                        (rec.get("scoring") or {}).get("state") != "failed":
                    await run_scoring(iid)
                await _fetch_vapi_video(rec)
        except Exception:
            log.exception("[%s] sweep failed", iid)
        finally:
            _sweeping.discard(iid)


async def _fetch_vapi_video(rec: dict) -> None:
    """With VAPI_PRIVATE_KEY set, pull Vapi's cloud video/audio once it is ready (the webhook usually
    arrives before the video is processed)."""
    v = rec.get("vapi") or {}
    if not os.getenv("VAPI_PRIVATE_KEY") or not v.get("call_ids"):
        return
    tries = v.get("fetch_tries", 0)
    if tries >= 6 or time.time() - v.get("last_fetch", 0) < 60 * (tries + 1):
        return
    have = set(v.get("downloaded", []))
    got_any = False
    for cid in v["call_ids"]:
        call = await media.fetch_vapi_call(cid)
        art = (call or {}).get("artifact") or {}
        for kind, url in (("call_video", art.get("videoRecordingUrl")), ("call_audio", art.get("recordingUrl"))):
            if url and url not in have:
                m = await media.download(rec["id"], url, kind, kind)
                if m:
                    have.add(url)
                    got_any = True
                    async with store.lock(rec["id"]):
                        r = get_rec(rec["id"])
                        r["media"].append(m)
                        r.setdefault("vapi", {})["downloaded"] = sorted(have)
                        store.save(r)
    async with store.lock(rec["id"]):
        r = get_rec(rec["id"])
        vv = r.setdefault("vapi", {})
        vv["fetch_tries"] = 6 if (got_any and any("video" in m["kind"] for m in r["media"] if m.get("source") == "vapi")) \
            else tries + 1
        vv["last_fetch"] = time.time()
        store.save(r)


async def _sweeper():
    while True:
        await asyncio.sleep(SWEEP_EVERY_SEC)
        try:
            await sweep_once()
        except Exception:
            log.exception("sweeper failed")


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


def _token_ok(rec: dict, token: str, current_only: bool) -> bool:
    st = rec.get("state") or {}
    valid = [st.get("token")] if current_only else (st.get("tokens") or [])
    return any(t and secrets.compare_digest(token.encode(), t.encode()) for t in valid)


@app.post("/llm/{iid}/{token}/chat/completions")
async def custom_llm(iid: str, token: str, req: Request):
    """Vapi calls this on every candidate turn. The LLM call happens WITHOUT holding the
    interview lock, so when Vapi re-requests a turn (candidate kept talking) the new request
    is not stuck behind the old one."""
    body = await req.json()
    messages = [m for m in (body.get("messages") or []) if isinstance(m, dict)]
    async with store.lock(iid):
        rec = get_rec(iid)
        if not _token_ok(rec, token, current_only=True):
            log.warning("[%s] rejected LLM request with stale or wrong token", iid)
            raise HTTPException(403, "This call session is no longer active")
        if rec.get("disqualified"):
            prep = {"reply": f"The interview has been stopped, and {brain.END_PHRASE}."}
        else:
            prep = brain.prepare_turn(rec, messages)
        rec["last_seen"] = time.time()
        store.save(rec)
        plan = rec["plan"]
    _presence[iid] = time.time()
    if "reply" in prep:
        say = prep["reply"]
    else:
        d, ms, failed = await brain.judge_turn(prep, plan)
        async with store.lock(iid):
            rec = get_rec(iid)
            if not _token_ok(rec, token, current_only=True):
                raise HTTPException(403, "This call session is no longer active")
            say = brain.apply_turn(rec, prep, d, ms, failed)
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


@app.post("/webhook/vapi/{iid}/{token}")
async def vapi_webhook(iid: str, token: str, req: Request, bg: BackgroundTasks):
    body = await req.json()
    msg = body.get("message") or {}
    if not _token_ok(get_rec(iid), token, current_only=False):
        raise HTTPException(403, "bad token")
    if msg.get("type") == "end-of-call-report":
        art = msg.get("artifact") or {}
        audio = art.get("recordingUrl") or msg.get("recordingUrl") or \
            ((art.get("recording") or {}).get("mono") or {}).get("combinedUrl")
        video = art.get("videoRecordingUrl")
        async with store.lock(iid):
            rec = get_rec(iid)
            v = rec.setdefault("vapi", {})
            v.setdefault("end_reports", []).append({
                "endedReason": msg.get("endedReason"), "recordingUrl": audio, "videoRecordingUrl": video,
                "durationSeconds": msg.get("durationSeconds"), "cost": msg.get("cost"), "at": time.time(),
                "transcript": (art.get("transcript") or msg.get("transcript") or "")[:60000]})
            v["end_report"] = v["end_reports"][-1]
            call_id = ((msg.get("call") or {}).get("id") or "")[:80]
            if call_id and call_id not in v.get("call_ids", []):
                v.setdefault("call_ids", []).append(call_id)
            ended = bool((rec.get("state") or {}).get("ended"))
            if ended and rec["status"] == "in_progress":
                rec["status"] = "completed"
            store.save(rec)
        for kind, url in (("call_audio", audio), ("call_video", video)):
            if url:
                bg.add_task(_download_and_attach, iid, url, kind)
        # The candidate may close the tab before the browser calls /complete. Score from here too.
        if ended:
            bg.add_task(_finish_up, iid)
    return {"ok": True}


async def _download_and_attach(iid: str, url: str, kind: str):
    rec = get_rec(iid)
    if url in (rec.get("vapi") or {}).get("downloaded", []):
        return
    m = await media.download(iid, url, kind, kind)
    if not m:
        return
    async with store.lock(iid):
        rec = get_rec(iid)
        rec["media"].append(m)
        v = rec.setdefault("vapi", {})
        v["downloaded"] = sorted(set(v.get("downloaded", [])) | {url})
        store.save(rec)


# Jobs, candidates, matching and careers. Included after the routes above so fixed paths such as
# /api/candidates/history win over /api/candidates/{id}.
app.include_router(api_hiring.router)

# The web app is one page (index.html) with its own routes; the server returns it for each of them.
SPA_ROUTES = ["/app", "/app/{rest:path}", "/admin", "/login", "/signup", "/invite/{rest:path}", "/careers/{rest:path}"]


def _spa(rest: str = ""):
    return FileResponse(WEB_DIR / "index.html", media_type="text/html")


for _r in SPA_ROUTES:
    app.add_api_route(_r, _spa, methods=["GET"], include_in_schema=False)


# Pages from the earlier version: old bookmarks and links in emails keep working.
@app.get("/dashboard.html", include_in_schema=False)
def _old_dashboard():
    return RedirectResponse("/app/interviews", status_code=301)


@app.get("/hr.html", include_in_schema=False)
def _old_hr():
    return RedirectResponse("/app/interviews/new", status_code=301)


@app.get("/report.html", include_in_schema=False)
def _old_report(id: str = ""):
    return RedirectResponse(f"/app/interviews/{id}" if id else "/app/interviews", status_code=301)


if (WEB_DIR / "index.html").exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
else:
    log.error("Frontend not built: %s is missing. Run: cd frontend && npm ci && npm run build", WEB_DIR)

    @app.get("/{path:path}", include_in_schema=False)
    def frontend_missing(path: str):
        return PlainTextResponse("The web interface has not been built. Run: cd frontend && npm ci && npm run build",
                                 status_code=503)
