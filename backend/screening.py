"""AI CV screening round: a score against the job with written reasons, knockout checks and a job-stability indicator.

The score is the free stage-1 match (skills, experience, keyword relevance, location, notice and salary), so it is
instant for hundreds of CVs. The reasons are written from that breakdown. An optional AI match report is added in
the background for each screened CV when the round's config asks for it (setup.py).
"""
from . import db, matching, resumes
from .api_accounts import org_settings


def reasons(bd: dict, ko: list[str], stab: dict) -> list[str]:
    out = []
    sk = bd.get("skills", {})
    must = sk.get("must_matched", []) + list((sk.get("must_related") or {}).keys()) + sk.get("must_missing", [])
    if must:
        out.append(f"Has {len(sk.get('must_matched', []))} of {len(must)} must-have skills"
                   + (f": {', '.join(sk['must_matched'][:5])}" if sk.get("must_matched") else ""))
    for need, have in (sk.get("must_related") or {}).items():
        out.append(f"No {need}, but has the related {have} (partial credit)")
    if sk.get("must_missing"):
        out.append(f"Missing: {', '.join(sk['must_missing'][:5])}")
    if sk.get("nice_matched"):
        out.append(f"Nice-to-have: {', '.join(sk['nice_matched'][:4])}")
    ex = bd.get("experience", {})
    if ex.get("years") is not None:
        out.append(f"{ex['years']:g} years of experience ({ex.get('note', '')})")
    else:
        out.append("Years of experience not found in the CV")
    lo = bd.get("location", {})
    if lo.get("note"):
        out.append(f"Location: {lo['note']}" + (f" ({lo['candidate']})" if lo.get("candidate") else ""))
    lg = bd.get("logistics", {})
    if lg.get("notice"):
        out.append(f"Notice period: {lg['notice']}")
    if lg.get("salary"):
        out.append(f"Expected salary {lg['salary']}")
    if stab.get("level") not in (None, "unknown"):
        out.append(f"Job stability: {stab['label']} (average {stab['avg_months']:g} months per job, {stab['short_stints']} under a year)")
    for k in ko:
        out.append(f"Knockout: {k}")
    return out


def score_application(s, app: db.Application, job: db.Job, rnd: dict, rr: db.RoundResult) -> None:
    """Fill the CV screening result for one application (synchronous, milliseconds)."""
    c = s.get(db.Candidate, app.candidate_id)
    st = org_settings(s.get(db.Org, app.org_id))
    cands, idx = matching.load_pool(s, app.org_id)
    me = next((i for i, x in enumerate(cands) if x.id == c.id), None)
    if me is None:
        matching.compute_features(c)
        cand = matching.cand_from_features(c.id, c.name, c.features)
        rel = 0.0
    else:
        cand = cands[me]
        jf = matching.job_features(job, st["match_top_n"])
        raw = idx.bm25(jf.terms)
        top = max(raw.values()) if raw else 0
        rel = (raw.get(me, 0) / top) if top else 0.0
    jf = matching.job_features(job, st["match_top_n"])
    score, bd, ko = matching.score_one(jf, cand, rel, st["match_weights"])
    stab = resumes.stability(c.resume_text or "", c.profile or {})
    if stab["level"] == "low":                       # a visible signal, never a silent rejection
        score = max(0.0, score - 5)
    rr.score = score
    rr.data = {**(rr.data or {}), "breakdown": bd, "knockouts": ko, "stability": stab, "reasons": reasons(bd, ko, stab),
               "ai_report_wanted": bool((rnd.get("config") or {}).get("use_ai_report"))}
    rr.started_at = rr.started_at or db.now()
    if ko:
        rr.integrity = {**(rr.integrity or {}), "knockouts": ko}
