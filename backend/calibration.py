"""AI vs your team: how often people's decisions agree with the AI scores, round by round.

For every round where the AI scores or recommends and a person then decides, this counts agreements, shows the score
gap between candidates people passed and rejected, and lists the cases where they disagreed most. It answers "can we
trust the AI here, or should we adjust the pass mark or the questions?" with the company's own decisions, and it is the
evidence a bias or AI audit asks for. Automatic decisions are left out: they agree with the AI by construction.
"""
from . import db, flows

SCORED = ("cv_screening", "test", "video_intro", "role_task", "practical_task", "live_task", "ai_interview")
AUTO = ("automatic", "flow changed", "")


RULE_REASONS = ("met the pass mark", "below the pass mark", "top ", "outside the top")    # decisions a rule made for someone


def _human(rr: db.RoundResult) -> bool:
    reason = str((rr.data or {}).get("reason") or "").lower()
    return rr.decision in ("pass", "fail") and (rr.decided_by or "").strip().lower() not in AUTO and not reason.startswith(RULE_REASONS)


def _ai_says(rr: db.RoundResult, mark: float) -> str | None:
    d = rr.data or {}
    if rr.round_type == "ai_interview" and d.get("recommendation"):
        rec = str(d["recommendation"]).lower()
        return "pass" if rec.startswith(("strong", "yes", "hire")) else "fail" if rec.startswith(("no", "reject")) else "unsure"
    if rr.score is None:
        return None
    return "pass" if rr.score >= mark else "fail"


def job_report(s, job: db.Job) -> dict:
    rounds = [r for r in flows.flow_of(job) if r["type"] in SCORED]
    rrs = s.query(db.RoundResult).filter(db.RoundResult.job_id == job.id, db.RoundResult.round_id.in_([r["id"] for r in rounds] or [""])).all()
    names = {a.id: c.name or c.email for a, c in s.query(db.Application, db.Candidate).join(db.Candidate, db.Candidate.id == db.Application.candidate_id)
             .filter(db.Application.job_id == job.id)}
    out = []
    for r in rounds:
        rule = r.get("pass_rule") or {}
        has_mark = rule.get("mode") == "min_score" and float(rule.get("value") or 0) > 0
        mark = float(rule["value"]) if has_mark else 50.0
        mine = [rr for rr in rrs if rr.round_id == r["id"] and _human(rr)]
        rows = [(rr, _ai_says(rr, mark)) for rr in mine]
        rows = [(rr, ai) for rr, ai in rows if ai]
        sure = [(rr, ai) for rr, ai in rows if ai != "unsure"]
        agree = sum(1 for rr, ai in sure if ai == rr.decision)
        passed = [rr.score for rr in mine if rr.decision == "pass" and rr.score is not None]
        failed = [rr.score for rr in mine if rr.decision == "fail" and rr.score is not None]
        avg = lambda xs: round(sum(xs) / len(xs), 1) if xs else None   # noqa: E731
        dis = [rr for rr, ai in sure if ai != rr.decision]
        dis.sort(key=lambda rr: -abs((rr.score if rr.score is not None else mark) - mark))
        note = ""
        if len(sure) >= 5:
            rate = agree / len(sure)
            fp = sum(1 for rr, ai in sure if ai == "pass" and rr.decision == "fail")
            fn = sum(1 for rr, ai in sure if ai == "fail" and rr.decision == "pass")
            if rate < 0.7 and fp > 2 * fn:
                note = f"Your team rejects many candidates the AI would pass. Consider raising the pass mark above {mark:g} or tightening the rubric."
            elif rate < 0.7 and fn > 2 * fp:
                note = f"Your team passes many candidates the AI would reject. Consider lowering the pass mark below {mark:g} or checking the questions."
            elif rate < 0.7:
                note = "The AI and your team often disagree in both directions. Review the disagreements below before relying on the AI here."
            else:
                note = "The AI and your team mostly agree on this round."
        else:
            note = "Fewer than 5 people-made decisions so far: too few to judge."
        out.append({"round_id": r["id"], "name": r["name"], "type": r["type"], "mark": mark, "mark_source": "pass mark" if has_mark else "50 (no pass mark set)",
                    "decided": len(mine), "compared": len(sure), "unsure": len(rows) - len(sure), "agree": agree,
                    "agreement": round(100 * agree / len(sure)) if sure else None,
                    "avg_score_passed": avg(passed), "avg_score_rejected": avg(failed), "note": note,
                    "disagreements": [{"application_id": rr.application_id, "name": names.get(rr.application_id, ""), "score": rr.score,
                                       "ai": _ai_says(rr, mark), "decision": rr.decision, "by": rr.decided_by, "reason": (rr.data or {}).get("reason", "")[:200]}
                                      for rr in dis[:8]]})
    return {"rounds": out}
