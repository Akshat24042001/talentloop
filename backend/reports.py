"""Hiring reports: the funnel, time to hire, drop-off by round, and how sources and colleges perform."""
import statistics
import time

from . import db, flows

DONE = ("submitted", "passed", "failed", "on_hold", "no_show")
SELECTED = ("offer", "hired")
TYPE_ORDER = list(flows.ROUND_TYPES)


def _days(xs: list[float]) -> dict:
    xs = [x / 86400 for x in xs if x is not None and x >= 0]
    if not xs:
        return {"n": 0, "median": None, "average": None}
    return {"n": len(xs), "median": round(statistics.median(xs), 1), "average": round(sum(xs) / len(xs), 1)}


def build(s, org_id: str, job_ids: list[str] | None, job: db.Job | None = None, days: int = 0) -> dict:
    """job_ids None = every job in the company. days = only applications from the last N days (0 = all time)."""
    since = time.time() - days * 86400 if days else 0
    q = s.query(db.Application, db.Candidate.college, db.Drive.college).join(db.Candidate, db.Candidate.id == db.Application.candidate_id) \
        .outerjoin(db.Drive, db.Drive.id == db.Application.drive_id).filter(db.Application.org_id == org_id, db.Application.created_at >= since)
    if job is not None:
        q = q.filter(db.Application.job_id == job.id)
    elif job_ids is not None:
        q = q.filter(db.Application.job_id.in_(job_ids or [""]))
    rows = q.all()
    apps = {a.id: (a, (drive_college or cand_college or "").strip()) for a, cand_college, drive_college in rows}
    rrs: dict[str, list[db.RoundResult]] = {}
    ids = list(apps)
    for i in range(0, len(ids), 900):
        for rr in s.query(db.RoundResult).filter(db.RoundResult.application_id.in_(ids[i:i + 900])):
            rrs.setdefault(rr.application_id, []).append(rr)

    def assessed(aid):
        return any(r.round_type not in ("application", "cv_screening") and r.status in DONE for r in rrs.get(aid, []))

    def interviewed(aid):
        return any(r.round_type in ("ai_interview", "human_interview") and r.status in DONE for r in rrs.get(aid, []))

    def screened_in(aid):
        return any(r.round_type != "application" and r.status == "passed" for r in rrs.get(aid, []))

    total = len(apps)
    funnel = [
        {"key": "applied", "label": "Applied", "n": total},
        {"key": "screened", "label": "Passed a screening round", "n": sum(1 for aid in apps if screened_in(aid))},
        {"key": "assessed", "label": "Completed an assessment", "n": sum(1 for aid in apps if assessed(aid))},
        {"key": "interviewed", "label": "Interviewed", "n": sum(1 for aid in apps if interviewed(aid))},
        {"key": "selected", "label": "Selected", "n": sum(1 for a, _ in apps.values() if a.stage in SELECTED)},
        {"key": "hired", "label": "Hired", "n": sum(1 for a, _ in apps.values() if a.stage == "hired")},
    ]
    sel = [a for a, _ in apps.values() if a.stage in SELECTED and a.decided_at]
    rejected = [a for a, _ in apps.values() if a.stage == "rejected" and a.decided_at]

    # drop-off: per round of the job's flow, or per round type across jobs
    if job is not None:
        keys = [(r["id"], r["name"], r["type"]) for r in flows.flow_of(job)]
        key_of = lambda rr: rr.round_id            # noqa: E731
    else:
        keys = [(t, flows.ROUND_TYPES[t]["label"], t) for t in TYPE_ORDER]
        key_of = lambda rr: rr.round_type          # noqa: E731
    stats = {k: {"entered": 0, "completed": 0, "passed": 0, "failed": 0, "missed": 0, "scores": []} for k, _, _ in keys}
    for aid, lst in rrs.items():
        for rr in lst:
            st = stats.get(key_of(rr))
            if st is None:
                continue
            st["entered"] += 1
            if rr.status in DONE:
                st["completed"] += 1
            if rr.status == "passed":
                st["passed"] += 1
            if rr.status == "failed":
                st["failed"] += 1
            if rr.status in ("expired", "no_show"):
                st["missed"] += 1
            if rr.score is not None:
                st["scores"].append(rr.score)
    rounds = []
    for k, label, kind in keys:
        st = stats[k]
        if not st["entered"] and job is None:
            continue
        rounds.append({"key": k, "label": label, "type": kind, "entered": st["entered"], "completed": st["completed"], "passed": st["passed"],
                       "failed": st["failed"], "missed": st["missed"],
                       "completion_rate": round(st["completed"] / st["entered"] * 100) if st["entered"] else None,
                       "pass_rate": round(st["passed"] / st["entered"] * 100) if st["entered"] else None,
                       "avg_score": round(sum(st["scores"]) / len(st["scores"]), 1) if st["scores"] else None})

    def group(key) -> list[dict]:
        out: dict[str, dict] = {}
        for aid, (a, college) in apps.items():
            g = key(a, college)
            if not g:
                continue
            x = out.setdefault(g, {"name": g, "applications": 0, "screened": 0, "interviewed": 0, "selected": 0, "scores": []})
            x["applications"] += 1
            x["screened"] += screened_in(aid)
            x["interviewed"] += interviewed(aid)
            x["selected"] += a.stage in SELECTED
            x["scores"] += [r.score for r in rrs.get(aid, []) if r.score is not None and r.round_type in ("test", "cv_screening")]
        res = []
        for x in out.values():
            sc = x.pop("scores")
            x["avg_score"] = round(sum(sc) / len(sc), 1) if sc else None
            x["selection_rate"] = round(x["selected"] / x["applications"] * 100, 1) if x["applications"] else None
            res.append(x)
        return sorted(res, key=lambda x: (-x["applications"], x["name"]))

    return {"total": total, "funnel": funnel, "rounds": rounds,
            "time_to_hire": _days([a.decided_at - a.created_at for a in sel]), "time_to_reject": _days([a.decided_at - a.created_at for a in rejected]),
            "by_source": group(lambda a, c: a.source or "unknown"), "by_college": group(lambda a, c: c)[:30]}
