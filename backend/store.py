"""Interview storage: one JSON file per interview plus a media folder, on local disk.

Optional S3-compatible mirror (Backblaze B2, Cloudflare R2, Supabase Storage, AWS S3...). Hosts like
Render's free plan wipe the local disk on every restart, which silently deletes interviews and
recordings. With S3_BUCKET set, every save and every finished media file is copied to the bucket,
and anything missing locally is fetched back from it, so nothing is lost on a restart.

  S3_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_ENDPOINT_URL (non-AWS), S3_REGION, S3_PREFIX
"""
import asyncio
import json
import logging
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

log = logging.getLogger("store")

DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
INT_DIR = DATA_DIR / "interviews"
MEDIA_DIR = DATA_DIR / "media"
INT_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

S3_BUCKET = os.getenv("S3_BUCKET", "").strip()
S3_PREFIX = os.getenv("S3_PREFIX", "talentloop").strip().strip("/")
S3_ENABLED = bool(S3_BUCKET and os.getenv("S3_ACCESS_KEY_ID") and os.getenv("S3_SECRET_ACCESS_KEY"))

_locks: dict[str, asyncio.Lock] = {}
_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="s3")
_pending: set[str] = set()
_pending_lock = threading.Lock()
_s3 = None
S3_STATUS = {"enabled": S3_ENABLED, "last_error": ""}


def lock(iid: str) -> asyncio.Lock:
    if iid not in _locks:
        _locks[iid] = asyncio.Lock()
    return _locks[iid]


def _valid(iid: str) -> bool:
    x = iid.replace("-", "").replace("_", "")
    return bool(x) and x.isascii() and x.isalnum()


def _path(iid: str) -> Path:
    if not _valid(iid):
        raise ValueError("bad id")
    return INT_DIR / f"{iid}.json"


def safe_name(fname: str) -> str:
    name = Path(fname).name
    if not name or name != fname or name.startswith(".") or not all(c.isascii() and (c.isalnum() or c in "._-") for c in name):
        raise ValueError("bad file name")
    return name


# ---------------------------------------------------------------------------
# S3 mirror
# ---------------------------------------------------------------------------
def s3():
    global _s3
    if _s3 is None:
        import boto3
        from botocore.config import Config
        endpoint = (os.getenv("S3_ENDPOINT_URL") or "").strip() or None
        region = (os.getenv("S3_REGION") or "").strip()
        if not region and endpoint:
            # Backblaze B2 / AWS style endpoints carry the region: https://s3.us-west-004.backblazeb2.com
            host = endpoint.split("://")[-1].split("/")[0]
            parts = host.split(".")
            region = parts[1] if len(parts) > 2 and parts[0] == "s3" else "auto"
        _s3 = boto3.client(
            "s3", endpoint_url=endpoint,
            region_name=region or "us-east-1",
            aws_access_key_id=os.getenv("S3_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY"),
            config=Config(retries={"max_attempts": 4, "mode": "standard"}, signature_version="s3v4"))
    return _s3


def _key(*parts: str) -> str:
    return "/".join([p for p in (S3_PREFIX, *parts) if p])


def _s3_err(what: str, e: Exception):
    S3_STATUS["last_error"] = f"{what}: {e}"[:300]
    log.warning("S3 %s failed: %s", what, e)


def _upload_json_now(iid: str):
    with _pending_lock:
        _pending.discard(iid)
    p = _path(iid)
    if not p.exists():
        return
    try:
        s3().put_object(Bucket=S3_BUCKET, Key=_key("interviews", f"{iid}.json"), Body=p.read_bytes(),
                        ContentType="application/json")
    except Exception as e:
        _s3_err(f"upload {iid}.json", e)


def _queue_json(iid: str):
    """Coalesce: many saves in quick succession become one upload of the latest file."""
    with _pending_lock:
        if iid in _pending:
            return
        _pending.add(iid)
    _pool.submit(_upload_json_now, iid)


def upload_media(iid: str, fname: str) -> None:
    """Blocking. Call from a thread (asyncio.to_thread) for big files."""
    if not S3_ENABLED:
        return
    p = MEDIA_DIR / iid / safe_name(fname)
    if not p.exists():
        return
    try:
        s3().upload_file(str(p), S3_BUCKET, _key("media", iid, p.name))
    except Exception as e:
        _s3_err(f"upload media {iid}/{fname}", e)
        raise


def media_path(iid: str, fname: str) -> Path | None:
    """Local path of a media file, fetching it from S3 first if it only exists there. Blocking."""
    if not _valid(iid):
        return None
    p = MEDIA_DIR / iid / safe_name(fname)
    if p.exists():
        return p
    if not S3_ENABLED:
        return None
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".part")
        s3().download_file(S3_BUCKET, _key("media", iid, p.name), str(tmp))
        tmp.replace(p)
        return p
    except Exception as e:
        _s3_err(f"download media {iid}/{fname}", e)
        return None


def restore_all() -> int:
    """At startup: bring back every interview JSON that exists in S3 but not on local disk. Blocking."""
    if not S3_ENABLED:
        return 0
    n = 0
    try:
        pag = s3().get_paginator("list_objects_v2")
        for page in pag.paginate(Bucket=S3_BUCKET, Prefix=_key("interviews") + "/"):
            for obj in page.get("Contents", []):
                name = obj["Key"].rsplit("/", 1)[-1]
                if not name.endswith(".json") or not _valid(name[:-5]):
                    continue
                p = INT_DIR / name
                if p.exists():
                    continue
                body = s3().get_object(Bucket=S3_BUCKET, Key=obj["Key"])["Body"].read()
                json.loads(body)  # never restore a corrupt file
                p.write_bytes(body)
                n += 1
        S3_STATUS["last_error"] = ""
    except Exception as e:
        _s3_err("restore", e)
    return n


def flush(timeout: float = 30) -> None:
    """Wait for queued uploads (used by tests and on shutdown)."""
    _pool.submit(lambda: None).result(timeout=timeout)
    for _ in range(3):
        with _pending_lock:
            left = list(_pending)
        if not left:
            return
        for iid in left:
            _upload_json_now(iid)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def load(iid: str) -> dict | None:
    p = _path(iid)
    if not p.exists() and S3_ENABLED:
        try:
            body = s3().get_object(Bucket=S3_BUCKET, Key=_key("interviews", f"{iid}.json"))["Body"].read()
            p.write_bytes(body)
        except Exception:
            return None
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save(rec: dict) -> None:
    p = _path(rec["id"])
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)
    if S3_ENABLED:
        _queue_json(rec["id"])


def delete(iid: str) -> None:
    p = _path(iid)
    if p.exists():
        p.unlink()
    shutil.rmtree(MEDIA_DIR / iid, ignore_errors=True)
    _locks.pop(iid, None)
    if S3_ENABLED:
        try:
            s3().delete_object(Bucket=S3_BUCKET, Key=_key("interviews", f"{iid}.json"))
            pag = s3().get_paginator("list_objects_v2")
            for page in pag.paginate(Bucket=S3_BUCKET, Prefix=_key("media", iid) + "/"):
                objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
                if objs:
                    s3().delete_objects(Bucket=S3_BUCKET, Delete={"Objects": objs})
        except Exception as e:
            _s3_err(f"delete {iid}", e)


def list_all() -> list[dict]:
    out = []
    for p in sorted(INT_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out
