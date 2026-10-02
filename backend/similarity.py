"""Cross-candidate integrity scan for one job: answers that look copied between candidates.

Single-candidate proctoring cannot see collusion, leaked answer sheets or one person applying twice. This compares
candidates of the same job with each other:

  * AI interview answers, live-task work and written answers: overlapping 6-word runs (shingles). Runs that most
    candidates share (the question read back, common phrases, boilerplate code) and the task text are removed first,
    so what is left is wording two people should not have in common.
  * Tests: the same wrong option on the same questions. Two people getting a question right says little; picking the
    same wrong option again and again is the classic sign of a shared answer sheet.
  * The same phone number under different candidate records.

Deterministic and explainable: every pair comes with the evidence (shared text or the questions). It flags pairs for a
person to look at; it never rejects anyone.
"""
import re
from collections import Counter
from itertools import combinations

from . import db, flows, store

K = 6                    # words per shingle
MIN_SHINGLES = 12        # texts shorter than this are too short to compare
TEXT_FLAG = 0.45         # share of the shorter text found in the other one
WRONG_FLAG = 3           # identical wrong options on shared questions
WORD = re.compile(r"[a-z0-9_]+")


def _words(text: str) -> list[str]:
    return WORD.findall((text or "").lower())


def shingles(text: str) -> set[str]:
    w = _words(text)
    return {" ".join(w[i:i + K]) for i in range(len(w) - K + 1)}


def _sample(a_text: str, common: set[str]) -> str:
    """The longest stretch of the first text made of shared shingles, for the evidence line."""
    w = _words(a_text)
    best, cur, start, best_start = 0, 0, 0, 0
    for i in range(len(w) - K + 1):
        if " ".join(w[i:i + K]) in common:
            if cur == 0:
                start = i
            cur += 1
            if cur > best:
                best, best_start = cur, start
        else:
            cur = 0
    return " ".join(w[best_start:best_start + best + K - 1])[:300] if best else ""


def _compare_texts(texts: dict[str, str], strip: set[str], kind: str, label: str) -> list[dict]:
    sets = {k: shingles(v) - strip for k, v in texts.items() if v}
    sets = {k: v for k, v in sets.items() if len(v) >= MIN_SHINGLES}
    if len(sets) < 2:
        return []
    if len(sets) >= 4:       # runs most candidates share are the question or boilerplate, not copying
        freq = Counter(x for v in sets.values() for x in v)
        common = {x for x, n in freq.items() if n > max(2, len(sets) // 2)}
        sets = {k: v - common for k, v in sets.items()}
    out = []
    for a, b in combinations(sorted(sets), 2):
        sa, sb = sets[a], sets[b]
        if len(sa) < MIN_SHINGLES or len(sb) < MIN_SHINGLES:
            continue
        both = sa & sb
        score = len(both) / min(len(sa), len(sb))
        if score >= TEXT_FLAG:
            out.append({"a": a, "b": b, "kind": kind, "round": label, "score": round(score * 100),
                        "detail": f"{round(score * 100)}% of the shorter {kind_word(kind)} also appears in the other one.",
                        "sample": _sample(texts[a], both)})
    return out


def kind_word(kind: str) -> str:
    return {"interview": "set of interview answers", "live_task": "submission", "written": "answer"}.get(kind, "text")


def interview_answers(iid: str) -> str:
    rec = store.load(iid) if iid else None
    if not rec:
        return ""
    log = ((rec.get("state") or {}).get("log")) or []
    return " ".join(e.get("text", "") for e in log if e.get("role") == "candidate" and e.get("text"))


def _test_pairs(s, rrs: list[db.RoundResult], label: str) -> list[dict]:
    ans = {rr.application_id: (rr.data or {}).get("answers") or {} for rr in rrs if (rr.data or {}).get("answers")}
    if len(ans) < 2:
        return []
    qids = {q for a in ans.values() for q in a}
    key = {q.id: (q.kind, q.answer or [], q.text) for q in s.query(db.Question).filter(db.Question.id.in_(qids or {""}))}
    wrong = {aid: {q: tuple(v) for q, v in a.items() if q in key and key[q][0] != "numeric" and sorted(v) != sorted(key[q][1])}
             for aid, a in ans.items()}
    out = []
    for a, b in combinations(sorted(wrong), 2):
        shared = [q for q in wrong[a] if q in wrong[b] and wrong[a][q] == wrong[b][q]]
        either = len(set(wrong[a]) & set(ans[b])) + len(set(wrong[b]) & set(ans[a]))
        if len(shared) >= WRONG_FLAG and either and 2 * len(shared) / either >= 0.6:
            out.append({"a": a, "b": b, "kind": "test", "round": label, "score": round(200 * len(shared) / either),
                        "detail": f"Picked the same wrong option on {len(shared)} questions.",
                        "sample": "; ".join(key[q][2][:80] for q in shared[:3])})
    return out


def scan(s, job: db.Job) -> dict:
    apps = s.query(db.Application).filter(db.Application.job_id == job.id).all()
    by_id = {a.id: a for a in apps}
    cands = {c.id: c for c in s.query(db.Candidate).filter(db.Candidate.id.in_([a.candidate_id for a in apps] or [""]))}
    rounds = {r["id"]: r for r in flows.flow_of(job)}
    rrs = s.query(db.RoundResult).filter(db.RoundResult.job_id == job.id).all()
    pairs: list[dict] = []
    compared = Counter()
    for rid, rnd in rounds.items():
        mine = [rr for rr in rrs if rr.round_id == rid]
        cfg = rnd.get("config") or {}
        if rnd["type"] == "test":
            pairs += _test_pairs(s, mine, rnd["name"])
            compared["test"] += sum(1 for rr in mine if (rr.data or {}).get("answers"))
        elif rnd["type"] == "live_task":
            texts = {rr.application_id: (rr.data or {}).get("live_content") or "" for rr in mine}
            pairs += _compare_texts(texts, shingles(cfg.get("instructions", "")), "live_task", rnd["name"])
            compared["live_task"] += sum(1 for t in texts.values() if t)
        elif rnd["type"] == "ai_interview":
            texts = {rr.application_id: interview_answers((rr.data or {}).get("interview_id")) for rr in mine}
            pairs += _compare_texts(texts, set(), "interview", rnd["name"])
            compared["interview"] += sum(1 for t in texts.values() if t)
    # one phone number, several candidate records
    phones: dict[str, list[str]] = {}
    for a in apps:
        c = cands.get(a.candidate_id)
        digits = re.sub(r"\D", "", (c.phone if c else "") or "")[-10:]
        if len(digits) == 10:
            phones.setdefault(digits, []).append(a.id)
    for digits, ids in phones.items():
        for a, b in combinations(sorted(ids), 2):
            if by_id[a].candidate_id != by_id[b].candidate_id:
                pairs.append({"a": a, "b": b, "kind": "contact", "round": "Application", "score": 100,
                              "detail": f"Same phone number (ending {digits[-4:]}) on two candidate records.", "sample": ""})

    def who(aid: str) -> dict:
        a = by_id.get(aid)
        c = cands.get(a.candidate_id) if a else None
        return {"application_id": aid, "name": (c.name if c else "") or (c.email if c else ""), "email": c.email if c else "", "stage": a.stage if a else ""}
    pairs.sort(key=lambda p: -p["score"])
    return {"pairs": [{**p, "a": who(p["a"]), "b": who(p["b"])} for p in pairs[:100]], "compared": dict(compared),
            "applications": len(apps)}
