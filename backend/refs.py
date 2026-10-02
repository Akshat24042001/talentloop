"""Opaque references for URLs: every job, candidate, interview and application link carries an encrypted token
("k3x9...") instead of a database id, a title or a running number, so an address reveals nothing (no names, no
counts) and can't be guessed.

Token = base32(tag || id XOR keystream): tag = HMAC(key, kind|id)[:8] and keystream = HMAC(key, tag) (a
deterministic SIV construction from the standard library). The same record always gets the same token, any change
to a token fails the tag check, and a token for one kind never resolves as another. The key comes from URL_SECRET
when set; otherwise it is generated once and kept in the database, so links survive restarts and redeploys.

Every lookup is still scoped to the signed-in company (or to the careers page's company). Older links with raw ids
or readable refs ("senior-backend-engineer-12") keep working.
"""
import base64
import hashlib
import hmac
import os
import re
import secrets

from sqlalchemy.exc import IntegrityError

from . import db

_NUM = re.compile(r"(?:^|-)(\d{1,9})$")
_TOKEN = re.compile(r"^[a-z2-7]{24,64}$")
_key: bytes | None = None


def key() -> bytes:
    global _key
    if _key is None:
        env = os.getenv("URL_SECRET", "").strip()
        if env:
            _key = hashlib.sha256(env.encode()).digest()
        else:
            with db.session() as s:
                row = s.get(db.AppSecret, "url")
                if row is None:
                    s.add(db.AppSecret(name="url", value=secrets.token_hex(32)))
                    try:
                        s.commit()
                    except IntegrityError:          # another process created it first
                        s.rollback()
                    row = s.get(db.AppSecret, "url")
                _key = bytes.fromhex(row.value)
    return _key


def _stream(tag: bytes, n: int) -> bytes:
    out, i = b"", 0
    while len(out) < n:
        out += hmac.new(key(), b"s" + tag + bytes([i]), hashlib.sha256).digest()
        i += 1
    return out[:n]


def encode(kind: str, rid: str) -> str:
    raw = rid.encode()
    tag = hmac.new(key(), kind.encode() + b"|" + raw, hashlib.sha256).digest()[:8]
    ct = bytes(a ^ b for a, b in zip(raw, _stream(tag, len(raw))))
    return base64.b32encode(tag + ct).decode().rstrip("=").lower()


def decode(kind: str, token: str) -> str | None:
    """The id inside a token of this kind, or None when it isn't one (or was tampered with)."""
    token = (token or "").strip().lower()
    if not _TOKEN.match(token):
        return None
    try:
        blob = base64.b32decode(token.upper() + "=" * (-len(token) % 8))
    except Exception:
        return None
    tag, ct = blob[:8], blob[8:]
    raw = bytes(a ^ b for a, b in zip(ct, _stream(tag, len(ct))))
    good = hmac.new(key(), kind.encode() + b"|" + raw, hashlib.sha256).digest()[:8]
    if not hmac.compare_digest(tag, good):
        return None
    try:
        return raw.decode()
    except UnicodeDecodeError:
        return None


def job_ref(j: db.Job) -> str:
    return encode("job", j.id)


def cand_ref(c: db.Candidate) -> str:
    return encode("candidate", c.id)


def cand_ref_of(cid: str) -> str:
    return encode("candidate", cid)


def interview_ref(iid: str) -> str:
    return encode("interview", iid)


def app_ref(aid: str) -> str:
    return encode("application", aid)


def app_id(key_: str) -> str:
    """Application id for a token, or the value itself (raw ids from API callers)."""
    return decode("application", key_) or key_


def number_of(ref: str) -> int | None:
    m = _NUM.search(ref or "")
    return int(m.group(1)) if m else None


_KIND = {"Job": "job", "Candidate": "candidate", "InterviewIndex": "interview"}


def resolve(s, model, org_id: str | None, key_: str):
    """The row of `model` (Job, Candidate or InterviewIndex) in this company for a token, an id or an old readable ref."""
    key_ = (key_ or "").strip()
    if not key_:
        return None
    rid = decode(_KIND[model.__name__], key_)
    row = s.get(model, rid or key_)
    if row is not None and (org_id is None or row.org_id == org_id):
        return row
    if rid:
        return None
    n = number_of(key_)
    if n is None or org_id is None:
        return None
    return s.query(model).filter(model.org_id == org_id, model.number == n).first()
