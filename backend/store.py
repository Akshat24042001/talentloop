"""Dead-simple JSON file store. One file per interview in data/interviews/.
Fine for a PoC and a pilot of a few hundred interviews. Swap for Postgres later."""
import asyncio
import json
import os
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
INT_DIR = DATA_DIR / "interviews"
MEDIA_DIR = DATA_DIR / "media"
INT_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

_locks: dict[str, asyncio.Lock] = {}


def lock(iid: str) -> asyncio.Lock:
    if iid not in _locks:
        _locks[iid] = asyncio.Lock()
    return _locks[iid]


def _path(iid: str) -> Path:
    if not (iid.replace("-", "").replace("_", "").isascii() and iid.replace("-", "").replace("_", "").isalnum()):
        raise ValueError("bad id")
    return INT_DIR / f"{iid}.json"


def load(iid: str) -> dict | None:
    p = _path(iid)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save(rec: dict) -> None:
    p = _path(rec["id"])
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def delete(iid: str) -> None:
    import shutil
    p = _path(iid)
    if p.exists():
        p.unlink()
    shutil.rmtree(MEDIA_DIR / iid, ignore_errors=True)
    _locks.pop(iid, None)


def list_all() -> list[dict]:
    out = []
    for p in sorted(INT_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out
