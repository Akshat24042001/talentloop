"""The interview brain.

Design principle: CODE controls the interview (which question, how many follow-ups, time),
the LLM only judges the latest answer and writes the words. This is what keeps a voice
interviewer from drifting, skipping questions or running over time.
"""
import asyncio
import copy
import json
import logging
import os
import re
import time

from . import llm, prompts

log = logging.getLogger("brain")

END_PHRASE = "this concludes our interview"
CLOSING = ("That brings us to the end. Thank you for your time today. "
           "The HR team will review this and get back to you. Thank you, " + END_PHRASE + ".")
TURN_TIMEOUT = float(os.getenv("TURN_TIMEOUT_SEC", "7"))
END_BUFFER_SEC = 40          # below this remaining time, wrap up
MAX_SESSIONS = int(os.getenv("MAX_RECONNECTS", "3")) + 1


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------
def normalize_plan(plan: dict, duration_min: int | None = None) -> dict:
    """Make the plan safe to run no matter what the LLM (or HR edits) produced."""
    plan = copy.deepcopy(plan)
    if duration_min:
        plan["duration_min"] = int(duration_min)
    plan["duration_min"] = int(plan.get("duration_min") or 20)
    qs = [q for q in plan.get("questions", []) if (q.get("ask") or "").strip()]
    if not qs:
        raise ValueError("Plan has no questions")
    seen = set()
    for i, q in enumerate(qs):
        qid = str(q.get("id") or f"q{i+1}")
        if qid in seen:
            qid = f"q{i+1}"
        seen.add(qid)
        q["id"] = qid
        q["ask"] = q["ask"].strip()
        q.setdefault("type", "jd_skill")
        q["scored"] = bool(q.get("scored", q["type"] != "warmup"))
        q["good_answer_covers"] = [str(x) for x in (q.get("good_answer_covers") or [])][:5]
        q["red_flags"] = [str(x) for x in (q.get("red_flags") or [])]
        q["max_followups"] = max(0, min(3, int(q.get("max_followups", 1))))
        q["time_budget_sec"] = max(45, min(420, int(q.get("time_budget_sec", 150))))
    plan["questions"] = qs
    comps = plan.get("competencies") or [{"id": "c1", "name": "Overall fit", "weight": 1.0, "anchors": {}}]
    total_w = sum(float(c.get("weight", 0) or 0) for c in comps) or 1.0
    for c in comps:
        c["weight"] = round(float(c.get("weight", 0) or 0) / total_w, 3) if total_w else 1 / len(comps)
    plan["competencies"] = comps
    plan["keyterms"] = [str(k)[:50] for k in (plan.get("keyterms") or []) if str(k).strip()][:50]
    plan.setdefault("company_facts", [])
    plan.setdefault("resume_claims_to_verify", [])
    plan.setdefault("do_not_ask", [])
    return plan


async def generate_plan(inp: dict) -> dict:
    """inp: company, role, candidate_name, duration_min, jd, resume, questions (list[str])."""
    if llm.MOCK:
        return normalize_plan(_mock_plan(inp))
    user = prompts.PLAN_USER_TEMPLATE.format(
        company=inp.get("company", ""), role=inp.get("role", ""),
        candidate_name=inp.get("candidate_name", ""), duration_min=inp.get("duration_min", 20),
        jd=inp.get("jd", "")[:12000], resume=inp.get("resume", "")[:12000],
        questions="\n".join(inp.get("questions") or []) or "(none provided)",
    )
    plan = await llm.complete_json(prompts.PLAN_SYSTEM, user, llm.SMART_MODEL, temperature=0.3, max_tokens=4000)
    return normalize_plan(plan, inp.get("duration_min"))


# ---------------------------------------------------------------------------
# Live interview state machine
# ---------------------------------------------------------------------------
def _first_name(plan: dict) -> str:
    name = (plan.get("candidate_name") or "").strip()
    return name.split()[0] if name else "there"


def opening_message(plan: dict) -> str:
    q0 = plan["questions"][0]["ask"]
    return (f"Hi {_first_name(plan)}, welcome. I'm the AI interviewer for the {plan.get('role', 'open')} role"
            f"{' at ' + plan['company'] if plan.get('company') else ''}. This will take about {plan['duration_min']} minutes. "
            "Take your time with each answer, I will wait while you think. "
            "If you want a question repeated, just say so. Let's begin. " + q0)


def start_session(rec: dict) -> str:
    """Called when a (re)connecting candidate starts a call. Returns the first message to speak."""
    plan = rec["plan"]
    now = time.time()
    st = rec.get("state")
    if st is None:
        st = {"session": 1, "q_idx": 0, "fu_used": 0, "stall": 0, "covered": {}, "notes": {},
              "ended": False, "active_before": 0.0, "last_active": 0.0, "q_started_active": 0.0,
              "session_started": now, "log": []}
        first = opening_message(plan)
    else:
        if st.get("ended"):
            raise ValueError("Interview already completed")
        if st["session"] >= MAX_SESSIONS:
            raise ValueError("Too many reconnects")
        st["session"] += 1
        st["active_before"] = st.get("last_active", 0.0)
        st["session_started"] = now
        st["stall"] = 0
        q = plan["questions"][st["q_idx"]]
        first = (f"Welcome back {_first_name(plan)}. It looks like we got disconnected. "
                 f"Let's continue from where we stopped. {q['ask']}")
    st["log"].append({"role": "ai", "text": first, "q_id": plan["questions"][st["q_idx"]]["id"],
                      "action": "open" if st["session"] == 1 else "resume", "t": round(st["active_before"])})
    rec["state"] = st
    rec["snapshots"] = {f"{st['session']}:0": copy.deepcopy(st)}
    rec["status"] = "in_progress"
    return first


def _content(m: dict) -> str:
    c = m.get("content")
    if isinstance(c, list):
        c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return (c or "").strip()


def _trailing_user_text(messages: list[dict]) -> str:
    parts = []
    for m in reversed(messages):
        if m.get("role") == "user":
            parts.append(_content(m))
        elif m.get("role") == "assistant":
            break
    return " ".join(reversed([p for p in parts if p]))


def _allowed_actions(st: dict, plan: dict, active: float) -> tuple[list[str], str]:
    qs = plan["questions"]
    q = qs[st["q_idx"]]
    remaining = plan["duration_min"] * 60 - active
    progress = "end" if st["q_idx"] >= len(qs) - 1 else "next_question"
    if remaining <= END_BUFFER_SEC:
        return ["end"], "end"
    allowed = [progress]
    q_time = active - st["q_started_active"]
    if st["stall"] < 2:  # stop loops of repeats / redirects
        allowed += ["invite_continue", "clarify_repeat", "answer_candidate_question", "redirect"]
    if (st["fu_used"] < q["max_followups"] and q_time < q["time_budget_sec"] * 1.25 and remaining > 90):
        allowed.append("follow_up")
    return allowed, progress


def _recent(st: dict, k: int = 6) -> str:
    lines = []
    for e in st["log"][-k:]:
        who = "INTERVIEWER" if e["role"] == "ai" else "CANDIDATE"
        lines.append(f"{who}: {e['text'][:400]}")
    return "\n".join(lines)


async def _judge(st: dict, plan: dict, said: str, allowed: list[str]) -> dict:
    q = plan["questions"][st["q_idx"]]
    ctx = {
        "allowed": allowed, "q": q, "said": said,
        "fu_used": st["fu_used"], "already": st["covered"].get(q["id"], []),
    }
    if llm.MOCK:
        return _mock_turn(ctx)
    user = prompts.TURN_USER_TEMPLATE.format(
        allowed=json.dumps(allowed), role=plan.get("role", ""),
        facts=json.dumps(plan.get("company_facts", [])[:8]),
        question=q["ask"], covers=json.dumps(q["good_answer_covers"]),
        already=json.dumps(ctx["already"]), fu_used=st["fu_used"], fu_max=q["max_followups"],
        recent=_recent(st), said=said[:2500],
    )
    return await asyncio.wait_for(
        llm.complete_json(prompts.TURN_SYSTEM, user, llm.FAST_MODEL, temperature=0.3, max_tokens=300,
                          timeout=TURN_TIMEOUT),
        timeout=TURN_TIMEOUT + 1,
    )


def _clean(s) -> str:
    s = re.sub(r"[*#_`>\[\]]", "", str(s or "")).strip()
    return s.replace(END_PHRASE, "").replace(END_PHRASE.capitalize(), "")


async def handle_turn(rec: dict, messages: list[dict]) -> str:
    """Process one candidate turn. Idempotent per turn number: if Vapi re-requests the same
    turn (candidate kept talking), we recompute from the snapshot before that turn."""
    plan = rec["plan"]
    cur = rec.get("state")
    if cur is None:
        start_session(rec)
        cur = rec["state"]
    s = cur["session"]
    n = sum(1 for m in messages if m.get("role") == "user")
    said = _trailing_user_text(messages)
    qs = plan["questions"]

    if n == 0 or not said:
        return qs[cur["q_idx"]]["ask"]

    snaps = rec.setdefault("snapshots", {})
    base_keys = [int(k.split(":")[1]) for k in snaps if k.startswith(f"{s}:") and int(k.split(":")[1]) < n]
    base = snaps[f"{s}:{max(base_keys)}"] if base_keys else cur
    st = copy.deepcopy(base)

    if st.get("ended"):
        return "Thank you, " + END_PHRASE + "."

    now = time.time()
    active = st["active_before"] + (now - st["session_started"])
    allowed, progress = _allowed_actions(st, plan, active)
    q = qs[st["q_idx"]]

    t0 = time.time()
    try:
        d = await _judge(st, plan, said, allowed)
    except Exception as e:  # never let the interview stall on an LLM failure
        log.warning("judge failed (%s); falling back to %s", e, progress)
        d = {"action": progress, "ack": "Thank you."}
    latency_ms = int((time.time() - t0) * 1000)

    action = d.get("action") if d.get("action") in allowed else progress
    if action == "follow_up" and not _clean(d.get("followup")):
        action = progress
    ack = _clean(d.get("ack")) or "Thank you."

    if action == "invite_continue":
        say = _clean(d.get("reply")) or "Please go on, I'm listening."
        st["stall"] += 1
    elif action == "follow_up":
        say = _clean(d.get("followup"))
        st["fu_used"] += 1
        st["stall"] = 0
    elif action == "clarify_repeat":
        say = _clean(d.get("rephrase")) or ("Sure. " + q["ask"])
        st["stall"] += 1
    elif action in ("answer_candidate_question", "redirect"):
        say = _clean(d.get("reply")) or ("Let's stay with the interview. " + q["ask"])
        st["stall"] += 1
    elif action == "next_question":
        st["q_idx"] += 1
        nq = qs[st["q_idx"]]
        prefix = "Final question. " if st["q_idx"] == len(qs) - 1 else ""
        say = f"{ack} {prefix}{nq['ask']}"
        st["fu_used"] = 0
        st["stall"] = 0
        st["q_started_active"] = active
    else:  # end
        say = f"{ack} {CLOSING}"
        st["ended"] = True

    cov = set(st["covered"].get(q["id"], []))
    for i in d.get("covered") or []:
        if isinstance(i, int) and 0 <= i < len(q["good_answer_covers"]):
            cov.add(i)
    st["covered"][q["id"]] = sorted(cov)
    if d.get("note"):
        st["notes"].setdefault(q["id"], []).append(_clean(d["note"])[:200])

    st["log"].append({"role": "candidate", "text": said, "q_id": q["id"], "t": round(active)})
    st["log"].append({"role": "ai", "text": say, "q_id": qs[st["q_idx"]]["id"], "action": action,
                      "t": round(active), "judge_ms": latency_ms})
    st["last_active"] = active

    snaps[f"{s}:{n}"] = copy.deepcopy(st)
    # keep the snapshot dict small
    for k in sorted([k for k in snaps if k.startswith(f"{s}:")], key=lambda k: int(k.split(":")[1]))[:-6]:
        snaps.pop(k, None)
    rec["state"] = st
    if st["ended"]:
        rec["status"] = "completed"
    return say


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def _mmss(t) -> str:
    t = int(t or 0)
    return f"{t // 60:02d}:{t % 60:02d}"


def build_transcript(rec: dict) -> str:
    qs = {q["id"]: q for q in rec["plan"]["questions"]}
    out, last_q = [], None
    for e in (rec.get("state") or {}).get("log", []):
        if e["role"] == "ai" and e.get("q_id") != last_q and e.get("action") in ("open", "resume", "next_question"):
            q = qs.get(e["q_id"], {})
            out.append(f"\n--- {e['q_id']} ({q.get('type', '')}, scored={q.get('scored')}) ---")
            last_q = e["q_id"]
        who = "AI" if e["role"] == "ai" else "CANDIDATE"
        out.append(f"[{_mmss(e['t'])}] {who}: {e['text']}")
    return "\n".join(out).strip()


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())).strip()


def _verify_quote(quote: str, cand_lines: list[str]) -> str:
    nq = _norm(quote)
    if not nq:
        return "unverified"
    if any(nq in _norm(l) for l in cand_lines):
        return "exact"
    qt = nq.split()
    best = 0.0
    for l in cand_lines:
        lt = set(_norm(l).split())
        if qt:
            best = max(best, sum(1 for w in qt if w in lt) / len(qt))
    return "approx" if best >= 0.8 else "unverified"


def proctoring_summary(events: list[dict]) -> dict:
    counts: dict[str, int] = {}
    hidden_secs, hidden_at = 0.0, None
    for ev in sorted(events, key=lambda e: e.get("ts", 0)):
        typ = ev.get("type", "?")
        counts[typ] = counts.get(typ, 0) + 1
        if typ == "tab_hidden":
            hidden_at = ev.get("ts")
        elif typ == "tab_visible" and hidden_at:
            hidden_secs += max(0, (ev.get("ts", 0) - hidden_at) / 1000)
            hidden_at = None
    flags = []
    if counts.get("tab_hidden", 0) >= 3 or hidden_secs > 30:
        flags.append(f"Left the interview tab {counts.get('tab_hidden', 0)} times ({int(hidden_secs)}s total)")
    if counts.get("fullscreen_exit", 0) >= 2:
        flags.append(f"Exited fullscreen {counts['fullscreen_exit']} times")
    if counts.get("no_face", 0) >= 3:
        flags.append("Camera showed no face several times")
    return {"counts": counts, "hidden_seconds": int(hidden_secs), "flags": flags}


async def _score_once(rec: dict, transcript: str) -> dict:
    if llm.MOCK:
        return _mock_score(rec)
    plan_view = {k: rec["plan"][k] for k in ("role", "competencies", "questions", "resume_claims_to_verify")}
    user = prompts.SCORE_USER_TEMPLATE.format(plan=json.dumps(plan_view, ensure_ascii=False), transcript=transcript)
    return await llm.complete_json(prompts.SCORE_SYSTEM, user, llm.SMART_MODEL, temperature=0.1, max_tokens=5000,
                                   timeout=180)


async def score_interview(rec: dict) -> dict:
    plan = rec["plan"]
    transcript = build_transcript(rec)
    passes = max(1, int(os.getenv("SCORING_PASSES", "1")))
    results = await asyncio.gather(*[_score_once(rec, transcript) for _ in range(passes)])
    rep = results[0]
    review = list(rep.get("human_review_reasons") or [])

    # consistency check across passes
    if passes > 1:
        by_q = {}
        for r in results:
            for qr in r.get("questions", []):
                if isinstance(qr.get("score"), (int, float)):
                    by_q.setdefault(qr["q_id"], []).append(qr["score"])
        for qr in rep.get("questions", []):
            vals = by_q.get(qr.get("q_id"), [])
            if len(vals) > 1:
                if max(vals) - min(vals) > 1:
                    review.append(f"{qr['q_id']}: scoring unstable across passes ({vals})")
                qr["score"] = round(sum(vals) / len(vals))

    # evidence verification: quotes must exist in what the candidate actually said
    cand_lines = [e["text"] for e in rec["state"]["log"] if e["role"] == "candidate"]
    qmap = {q["id"]: q for q in plan["questions"]}
    n_ev = n_ok = 0
    for qr in rep.get("questions", []):
        ok_any = False
        for ev in qr.get("evidence") or []:
            ev["verified"] = _verify_quote(ev.get("quote", ""), cand_lines)
            n_ev += 1
            if ev["verified"] != "unverified":
                n_ok += 1
                ok_any = True
        if isinstance(qr.get("score"), (int, float)) and qr["score"] > 1 and not ok_any:
            review.append(f"{qr.get('q_id')}: score {qr['score']} has no verifiable quote")
        q = qmap.get(qr.get("q_id"))
        if q:
            qr["ask"] = q["ask"]
            qr["type"] = q["type"]
            qr["competency_id"] = q.get("competency_id")
            if not q["scored"]:
                qr["score"] = None

    # weighted overall computed in code, not by the LLM
    comp_scores = {}
    for qr in rep.get("questions", []):
        if isinstance(qr.get("score"), (int, float)) and qr.get("competency_id"):
            comp_scores.setdefault(qr["competency_id"], []).append(qr["score"])
    num = den = 0.0
    for c in plan["competencies"]:
        vals = comp_scores.get(c["id"])
        if vals:
            num += c["weight"] * (sum(vals) / len(vals))
            den += c["weight"]
    q_scores = [qr["score"] for qr in rep.get("questions", []) if isinstance(qr.get("score"), (int, float))]
    overall = round(num / den, 2) if den else (round(sum(q_scores) / len(q_scores), 2) if q_scores else None)

    asked = {e["q_id"] for e in rec["state"]["log"] if e["role"] == "candidate"}
    missing = [q["id"] for q in plan["questions"] if q["id"] not in asked]
    if missing:
        review.append(f"Questions not reached: {', '.join(missing)}")
    if not rec["state"].get("ended"):
        review.append("Interview did not reach its normal end (dropped call or candidate left)")

    proctor = proctoring_summary(rec.get("events", []))
    review += proctor["flags"]

    rep["computed"] = {
        "overall": overall,
        "overall_pct": round((overall - 1) / 4 * 100) if overall else None,
        "questions_asked": len(asked), "questions_planned": len(plan["questions"]),
        "evidence_verified": f"{n_ok}/{n_ev}",
        "scoring_passes": passes,
        "avg_turn_latency_ms": _avg([e.get("judge_ms") for e in rec["state"]["log"] if e.get("judge_ms")]),
    }
    rep["proctoring"] = proctor
    rep["human_review_reasons"] = list(dict.fromkeys(review))
    rep["generated_at"] = time.time()
    return rep


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return int(sum(vals) / len(vals)) if vals else None


# ---------------------------------------------------------------------------
# Mocks (LLM_MOCK=1): let you click through the whole product with no API key
# ---------------------------------------------------------------------------
def _mock_plan(inp: dict) -> dict:
    hr = [q for q in (inp.get("questions") or []) if q.strip()]
    qs = [{"id": "q1", "type": "warmup", "ask": "To start, please introduce yourself in about a minute.",
           "scored": False, "good_answer_covers": [], "max_followups": 0, "time_budget_sec": 75, "competency_id": "c2"}]
    for i, t in enumerate(hr, start=2):
        qs.append({"id": f"q{i}", "type": "hr_mandatory", "ask": t, "scored": True, "competency_id": "c1",
                   "good_answer_covers": ["specific example", "their own role", "outcome"],
                   "max_followups": 1, "time_budget_sec": 150})
    qs.append({"id": f"q{len(qs)+1}", "type": "resume_probe", "competency_id": "c1", "scored": True,
               "ask": "Pick the most complex project on your resume. What exactly did you build, and what was hard about it?",
               "good_answer_covers": ["technical detail", "their contribution", "a problem solved"],
               "max_followups": 2, "time_budget_sec": 180})
    return {"company": inp.get("company", ""), "role": inp.get("role", ""),
            "candidate_name": inp.get("candidate_name", ""), "duration_min": inp.get("duration_min", 15),
            "competencies": [{"id": "c1", "name": "Role skills", "weight": 0.7, "anchors": {}},
                             {"id": "c2", "name": "Communication", "weight": 0.3, "anchors": {}}],
            "questions": qs, "keyterms": [], "company_facts": ["Mock mode: no real facts."],
            "resume_claims_to_verify": [], "do_not_ask": []}


def _mock_turn(ctx: dict) -> dict:
    said = ctx["said"].lower()
    allowed = ctx["allowed"]
    prog = "end" if "end" in allowed else "next_question"
    if "repeat" in said and "clarify_repeat" in allowed:
        return {"action": "clarify_repeat", "rephrase": "Sure. " + ctx["q"]["ask"]}
    if said.rstrip().endswith((" and", " so", " because")) and "invite_continue" in allowed:
        return {"action": "invite_continue", "reply": "Please go on."}
    if "follow_up" in allowed and ctx["fu_used"] == 0 and len(said.split()) < 25:
        return {"action": "follow_up", "followup": "Can you give me one specific example of that?",
                "covered": [], "note": "Short answer, probed for example."}
    return {"action": prog, "ack": "Thanks, that's clear.", "covered": [0], "note": "Answered."}


def _mock_score(rec: dict) -> dict:
    log_ = rec["state"]["log"]
    out = []
    for q in rec["plan"]["questions"]:
        lines = [e for e in log_ if e["role"] == "candidate" and e["q_id"] == q["id"]]
        out.append({"q_id": q["id"], "score": (3 if lines else None) if q["scored"] else None,
                    "evidence": [{"quote": lines[0]["text"][:80], "t": _mmss(lines[0]["t"])}] if lines else [],
                    "covered_points": [], "missed_points": [], "rationale": "Mock score."})
    return {"questions": out, "competencies": [], "resume_claims": [],
            "communication": {"score": 3, "rationale": "Mock."}, "strengths": ["Mock strength"],
            "concerns": ["Mock concern"], "red_flags": [], "recommendation": "maybe",
            "confidence": "low", "summary": "Mock mode report. Set LLM_MOCK=0 for real scoring.",
            "human_review_reasons": []}
