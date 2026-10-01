"""Readable references for URLs: "senior-backend-engineer-12" instead of a random database id.

The number is per company and per kind (job, candidate, interview), so it reveals nothing across companies and
every lookup is still scoped to the signed-in company. The slug part is cosmetic: only the trailing number is
used to find the record, so a renamed job's old links keep working. Raw ids are still accepted (old links, API).
"""
import re

from . import db
from .auth import slugify

_NUM = re.compile(r"(?:^|-)(\d{1,9})$")


def make(label: str, number: int | None, fallback_id: str) -> str:
    if not number:
        return fallback_id
    slug = slugify(label or "", 48)
    return f"{slug}-{number}" if slug and slug != "company" else str(number)


def job_ref(j: db.Job) -> str:
    return make(j.title, j.number, j.id)


def cand_ref(c: db.Candidate) -> str:
    return make(c.name or "candidate", c.number, c.id)


def interview_ref(candidate: str, role: str, number: int | None, iid: str) -> str:
    return make(candidate or role or "interview", number, iid)


def number_of(ref: str) -> int | None:
    m = _NUM.search(ref or "")
    return int(m.group(1)) if m else None


def resolve(s, model, org_id: str | None, key: str):
    """The row of `model` (Job, Candidate or InterviewIndex) in this company for an id or a readable ref."""
    key = (key or "").strip()
    if not key:
        return None
    row = s.get(model, key)
    if row is not None and (org_id is None or row.org_id == org_id):
        return row
    n = number_of(key)
    if n is None or org_id is None:
        return None
    return s.query(model).filter(model.org_id == org_id, model.number == n).first()
