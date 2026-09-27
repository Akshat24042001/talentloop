"""Recording files: making browser recordings playable, and copying Vapi's recordings.

Why recordings looked broken before: MediaRecorder writes WebM as a live stream. The file has no
duration and no seek index, so players show 0:00 or "Infinity", the scrub bar does not work, and some
players refuse it. Remuxing with ffmpeg (no re-encoding, seconds of CPU) writes a proper file with a
duration and cues. The ffmpeg binary comes from the imageio-ffmpeg pip package, so no system install
is needed on Render.
"""
import asyncio
import ipaddress
import logging
import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import store

log = logging.getLogger("media")
MAX_DOWNLOAD = 600 * 1024 * 1024


def ffmpeg_exe() -> str | None:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        from shutil import which
        return which("ffmpeg")


def remux(src: Path) -> tuple[bool, float | None, str]:
    """Rewrite a streamed WebM/MP4 so it has a duration and a seek index. Blocking.
    Returns (ok, duration_seconds, message). On failure the original file is kept untouched."""
    exe = ffmpeg_exe()
    if not exe:
        return False, None, "ffmpeg not available"
    out = src.with_name(src.stem + ".fixed" + src.suffix)
    args = [exe, "-hide_banner", "-loglevel", "error", "-y", "-fflags", "+genpts+igndts", "-i", str(src),
            "-map", "0", "-c", "copy"]
    if src.suffix == ".mp4":
        args += ["-movflags", "+faststart"]
    args.append(str(out))
    try:
        r = subprocess.run(args, capture_output=True, timeout=600)
        if r.returncode != 0 or not out.exists() or out.stat().st_size < 1000:
            out.unlink(missing_ok=True)
            return False, None, (r.stderr.decode(errors="ignore")[-300:] or "remux failed")
        out.replace(src)
        return True, probe_duration(src), "ok"
    except Exception as e:
        out.unlink(missing_ok=True)
        return False, None, str(e)[:300]


def probe_duration(p: Path) -> float | None:
    exe = ffmpeg_exe()
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "-hide_banner", "-i", str(p)], capture_output=True, timeout=60)
        txt = r.stderr.decode(errors="ignore")
        i = txt.find("Duration: ")
        if i < 0:
            return None
        hh, mm, ss = txt[i + 10:i + 21].split(":")
        return round(int(hh) * 3600 + int(mm) * 60 + float(ss), 1)
    except Exception:
        return None


async def finalize_media(iid: str, only_idle_sec: float = 0) -> int:
    """Remux finished browser recordings and mirror them to S3. Safe to call repeatedly.
    only_idle_sec: skip recordings that received a chunk within this many seconds (still uploading)."""
    async with store.lock(iid):
        rec = store.load(iid)
        if not rec:
            return 0
        todo = [dict(m) for m in rec.get("media", []) if m.get("rid") and not m.get("finalized")
                and time.time() - m.get("last_chunk_at", 0) >= only_idle_sec]
        for m in rec["media"]:
            if m.get("rid") in {t["rid"] for t in todo}:
                m["finalizing"] = True  # reject late chunks from now on
        store.save(rec)
    done = 0
    for m in todo:
        p = store.MEDIA_DIR / iid / m["file"]
        ok, dur, msg = (await asyncio.to_thread(remux, p)) if p.exists() else (False, None, "file missing")
        size = p.stat().st_size if p.exists() else 0
        uploaded = False
        if p.exists() and store.S3_ENABLED:
            try:
                await asyncio.to_thread(store.upload_media, iid, m["file"])
                uploaded = True
            except Exception:
                pass
        async with store.lock(iid):
            rec = store.load(iid)
            if not rec:
                return done
            for e in rec["media"]:
                if e.get("rid") == m["rid"]:
                    e.update(finalized=True, finalizing=False, playable=ok, bytes=size, in_s3=uploaded,
                             duration_sec=dur, finalize_note="" if ok else msg)
            store.save(rec)
        done += 1
    return done


# ---------------------------------------------------------------------------
# Downloading Vapi's recordings safely
# ---------------------------------------------------------------------------
def public_https_url(url: str) -> bool:
    """SSRF guard: https only, and the host must resolve to public IPs only (no localhost, private
    ranges, or cloud metadata endpoints). Allows any public storage host, since Vapi serves video and
    presigned URLs from storage providers we can't predict."""
    try:
        u = urlparse(url)
    except ValueError:
        return False
    if u.scheme != "https" or not u.hostname:
        return False
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            return False
    return bool(infos)


async def download(iid: str, url: str, kind: str, fname_hint: str) -> dict | None:
    if not await asyncio.to_thread(public_https_url, url):
        log.warning("[%s] refused non-public recording URL %s", iid, url[:100])
        return None
    path_ext = Path(urlparse(url).path).suffix.lower()
    ext = path_ext if path_ext in (".wav", ".mp3", ".mp4", ".webm", ".m4a") else (".mp4" if "video" in kind else ".wav")
    fname = f"{fname_hint}_{int(time.time())}{ext}"
    d = store.MEDIA_DIR / iid
    d.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        async with httpx.AsyncClient(timeout=300, follow_redirects=False) as c:
            async with c.stream("GET", url) as r:
                r.raise_for_status()
                with open(d / fname, "wb") as f:
                    async for chunk in r.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_DOWNLOAD:
                            raise ValueError("recording too large")
                        f.write(chunk)
    except Exception as e:
        (d / fname).unlink(missing_ok=True)
        log.warning("[%s] download of %s failed: %s", iid, kind, e)
        return None
    dur = await asyncio.to_thread(probe_duration, d / fname)
    in_s3 = False
    if store.S3_ENABLED:
        try:
            await asyncio.to_thread(store.upload_media, iid, fname)
            in_s3 = True
        except Exception:
            pass
    return {"kind": kind, "file": fname, "bytes": size, "source": "vapi", "duration_sec": dur,
            "finalized": True, "playable": True, "in_s3": in_s3, "added_at": time.time()}


async def fetch_vapi_call(call_id: str) -> dict | None:
    """GET /call/{id} with the PRIVATE key. The end-of-call webhook often lacks the video URL,
    which only appears once Vapi finishes processing."""
    key = os.getenv("VAPI_PRIVATE_KEY", "").strip()
    if not key or not call_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"https://api.vapi.ai/call/{call_id}", headers={"Authorization": f"Bearer {key}"})
            r.raise_for_status()
            return r.json()
    except Exception as e:
        log.warning("Vapi call fetch failed for %s: %s", call_id, e)
        return None
