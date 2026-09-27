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
import secrets
import time

from . import llm, prompts
from . import proctor as proctor_mod

log = logging.getLogger("brain")

END_PHRASE = "this concludes our interview"
CLOSING = ("That's everything I wanted to ask. Thanks so much for your time today, I really enjoyed the conversation. "
           "The HR team will go through it and get back to you soon. Take care, and " + END_PHRASE + ".")
TURN_TIMEOUT = float(os.getenv("TURN_TIMEOUT_SEC", "8"))
END_BUFFER_SEC = 40          # below this remaining time, wrap up
MAX_SESSIONS = int(os.getenv("MAX_RECONNECTS", "3")) + 1
QUESTION_TYPES = ("warmup", "hr_mandatory", "resume_probe", "jd_skill", "behavioral")
RECOMMENDATIONS = ("strong_yes", "yes", "maybe", "no")


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------
def _int(v, default: int) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def normalize_plan(plan: dict, duration_min: int | None = None) -> dict:
    """Make the plan safe to run no matter what the LLM (or HR edits) produced."""
    plan = copy.deepcopy(plan)
    if duration_min:
        plan["duration_min"] = _int(duration_min, 20)
    plan["duration_min"] = max(5, min(60, _int(plan.get("duration_min"), 20)))

    comps = [c for c in (plan.get("competencies") or []) if isinstance(c, dict)]
    if not comps:
        comps = [{"id": "c1", "name": "Overall fit", "weight": 1.0, "anchors": {}}]
    for i, c in enumerate(comps):
        c["id"] = str(c.get("id") or f"c{i+1}")
        c.setdefault("name", c["id"])
        c.setdefault("anchors", {})
        try:
            c["weight"] = max(0.0, float(c.get("weight", 0) or 0))
        except (TypeError, ValueError):
            c["weight"] = 0.0
    total_w = sum(c["weight"] for c in comps)
    for c in comps:
        c["weight"] = round(c["weight"] / total_w, 3) if total_w > 0 else round(1 / len(comps), 3)
    plan["competencies"] = comps
    comp_ids = {c["id"] for c in comps}

    qs = [q for q in plan.get("questions", []) if isinstance(q, dict) and str(q.get("ask") or "").strip()]
    if not qs:
        raise ValueError("Plan has no questions")
    seen = set()
    for i, q in enumerate(qs):
        qid = str(q.get("id") or f"q{i+1}")
        if qid in seen:
            qid = f"q{i+1}"
            while qid in seen:
                qid += "b"
        seen.add(qid)
        q["id"] = qid
        q["ask"] = str(q["ask"]).strip()
        q["type"] = q.get("type") if q.get("type") in QUESTION_TYPES else "jd_skill"
        q["scored"] = bool(q.get("scored", q["type"] != "warmup"))
        q["good_answer_covers"] = [str(x) for x in (q.get("good_answer_covers") or [])][:5]
        q["red_flags"] = [str(x) for x in (q.get("red_flags") or [])]
        q["max_followups"] = max(0, min(3, _int(q.get("max_followups"), 1)))
        q["time_budget_sec"] = max(45, min(420, _int(q.get("time_budget_sec"), 150)))
        if q.get("competency_id") not in comp_ids:  # otherwise the score silently drops out of the overall
            q["competency_id"] = comps[0]["id"]
    plan["questions"] = qs
    plan["keyterms"] = [str(k)[:50] for k in (plan.get("keyterms") or []) if str(k).strip()][:50]
    plan.setdefault("company_facts", [])
    plan.setdefault("resume_claims_to_verify", [])
    plan.setdefault("do_not_ask", [])
    return plan


def plan_warnings(plan: dict, hr_questions: list[str] | None = None) -> list[str]:
    """Things HR must look at before sending the link. Shown on the HR page."""
    w = []
    qs = plan["questions"]
    n_hr = len([x for x in (hr_questions or []) if str(x).strip()])
    n_mand = sum(1 for q in qs if q["type"] == "hr_mandatory")
    if n_hr and n_mand != n_hr:
        w.append(f"You gave {n_hr} HR questions but the plan has {n_mand} marked hr_mandatory. "
                 "Check none were dropped or merged.")
    budget = sum(q["time_budget_sec"] for q in qs)
    cap = plan["duration_min"] * 60
    if budget > cap * 0.9:
        w.append(f"Question time budgets add up to {round(budget / 60, 1)} of {plan['duration_min']} minutes. "
                 "Optional questions will be skipped automatically if time runs short.")
    long_q = [q["id"] for q in qs if len(q["ask"].split()) > 40]
    if long_q:
        w.append(f"Very long spoken questions (hard to hold in your head): {', '.join(long_q)}")
    if qs[0]["type"] != "warmup":
        w.append("First question is not a warm-up. Candidates perform worse when the first question is scored.")
    return w


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
SNAPSHOTS_KEPT = 12


def _first_name(plan: dict) -> str:
    name = (plan.get("candidate_name") or "").strip()
    return name.split()[0] if name else "there"


def opening_message(plan: dict) -> str:
    q0 = plan["questions"][0]["ask"]
    company = f" at {plan['company']}" if plan.get("company") else ""
    return (f"Hi {_first_name(plan)}, thanks for joining! I'm the AI interviewer for the {plan.get('role', 'open')} "
            f"role{company}. We'll talk for about {plan['duration_min']} minutes. There are no trick questions, "
            "so just answer the way you normally would, and take a moment to think whenever you need to. "
            "If you'd like me to repeat anything, just ask. Okay, let's get started. " + q0)


def _snap(st: dict) -> dict:
    return {"seq": st["seq"], "state": copy.deepcopy(st)}


def start_session(rec: dict) -> str:
    """Called when a (re)connecting candidate starts a call. Returns the first message to speak.

    Every call gets a fresh session number and a fresh secret token. The token is part of the
    custom-LLM URL, so requests from an older, dead call can never touch the current state.
    A session in which the candidate never spoke (mic failed, Vapi failed to start, page
    refreshed) does not count as a reconnect and restarts the interview cleanly."""
    plan = rec["plan"]
    now = time.time()
    st = rec.get("state")
    if st and st.get("ended"):
        raise ValueError("Interview already completed")
    spoke = bool(st) and any(e["role"] == "candidate" for e in st.get("log", []))
    if st and spoke:
        if st.get("reconnects", 0) + 1 >= MAX_SESSIONS:
            raise ValueError("Too many reconnects. Please contact HR.")
        st["reconnects"] = st.get("reconnects", 0) + 1
        st["session"] += 1
        st["active_before"] = st.get("last_active", 0.0)
        st["session_started"] = now
        st["stall"] = 0
        q = plan["questions"][st["q_idx"]]
        first = (f"Welcome back {_first_name(plan)}. It looks like we got disconnected. "
                 f"Let's continue from where we stopped. {q['ask']}")
        action = "resume"
    else:
        tokens = (st or {}).get("tokens", [])
        st = {"session": (st or {}).get("session", 0) + 1, "reconnects": 0, "q_idx": 0, "fu_used": 0,
              "stall": 0, "covered": {}, "notes": {}, "skipped": [], "judge_failures": 0,
              "ended": False, "active_before": 0.0, "last_active": 0.0, "q_started_active": 0.0,
              "session_started": now, "log": [], "tokens": tokens, "seq": 0}
        first = opening_message(plan)
        action = "open"
    st["token"] = secrets.token_urlsafe(16)
    st["tokens"] = (st.get("tokens") or [])[-10:] + [st["token"]]
    st["seq"] = st.get("seq", 0) + 1
    st["last_say"] = first
    st["ai_n"] = 1
    st["log"].append({"role": "ai", "text": first, "q_id": plan["questions"][st["q_idx"]]["id"],
                      "action": action, "t": round(st["active_before"]), "ts": now})
    rec["state"] = st
    rec["snapshots"] = [_snap(st)]
    rec["committed_seq"] = st["seq"]
    rec["status"] = "in_progress"
    return first


def _content(m: dict) -> str:
    c = m.get("content")
    if isinstance(c, list):
        c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return (c or "").strip()


def _same_utterance(ours: str, heard: str) -> bool:
    """Does an assistant message in Vapi's history correspond to a line we produced?
    Vapi keeps only the part actually spoken when the candidate interrupts, so allow a prefix."""
    a, b = _norm(ours), _norm(heard)
    if not a or not b:
        return False
    return a == b or (len(b) >= 12 and a.startswith(b))


def _locate(rec: dict, messages: list[dict]) -> tuple[dict | None, str, bool]:
    """Find the state the candidate is actually replying to, and what they said since.

    Vapi's message history is the source of truth for what was really spoken. We walk its
    assistant messages from newest to oldest and match them to our snapshots. This handles:
      * re-requests for the same turn (candidate kept talking, text got longer),
      * a reply we generated that Vapi threw away unspoken (it is not in the history, so the
        state it produced is ignored instead of silently skipping a question),
      * idle prompts spoken by Vapi itself ("Take your time...") that we never produced.
    Returns (base_state, candidate_text, matched)."""
    snaps = rec.get("snapshots") or []
    ai_pos = [i for i, m in enumerate(messages) if m.get("role") == "assistant" and _content(m)]
    for rank in range(len(ai_pos) - 1, -1, -1):
        i = ai_pos[rank]
        heard = _content(messages[i])
        hits = [s for s in reversed(snaps) if _same_utterance(s["state"].get("last_say", ""), heard)]
        if not hits:
            continue
        exact = [s for s in hits if s["state"].get("ai_n") == rank + 1]
        base = (exact or hits)[0]["state"]
        said = " ".join(_content(m) for m in messages[i + 1:] if m.get("role") == "user" and _content(m))
        return base, said, True
    # Nothing matched. Fall back to the committed state and trailing user text.
    parts = []
    for m in reversed(messages):
        if m.get("role") == "assistant":
            break
        if m.get("role") == "user":
            parts.append(_content(m))
    base = snaps[0]["state"] if (not ai_pos and snaps) else rec.get("state")
    return base, " ".join(reversed([p for p in parts if p])), False


def _remaining_mandatory_sec(plan: dict, after_idx: int) -> float:
    """Minimum time still needed for HR-mandatory questions after index after_idx."""
    return sum(min(q["time_budget_sec"], 90) for q in plan["questions"][after_idx + 1:]
               if q["type"] == "hr_mandatory")


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
    spare = remaining - END_BUFFER_SEC - _remaining_mandatory_sec(plan, st["q_idx"])
    if st["fu_used"] < q["max_followups"] and q_time < q["time_budget_sec"] * 1.25 and spare > 90:
        allowed.append("follow_up")
    return allowed, progress


def _next_index(st: dict, plan: dict, active: float) -> int | None:
    """Next question to ask, skipping optional questions when time is short so that
    HR-mandatory questions are always reached. None means there is nothing left to ask."""
    qs = plan["questions"]
    i = st["q_idx"] + 1
    while i < len(qs):
        remaining = plan["duration_min"] * 60 - active - END_BUFFER_SEC
        if qs[i]["type"] == "hr_mandatory" or remaining - _remaining_mandatory_sec(plan, i) >= 60:
            return i
        st["skipped"].append(qs[i]["id"])
        i += 1
    return None


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
        next_q=(plan["questions"][st["q_idx"] + 1]["ask"] if st["q_idx"] + 1 < len(plan["questions"]) else "(none, this is the last question)"),
        recent=_recent(st), said=said[:2500],
    )
    return await asyncio.wait_for(
        llm.complete_json(prompts.TURN_SYSTEM, user, llm.FAST_MODEL, temperature=0.3, max_tokens=300,
                          timeout=TURN_TIMEOUT),
        timeout=TURN_TIMEOUT + 1,
    )


_END_RE = re.compile(re.escape(END_PHRASE), re.I)


def _clean(s) -> str:
    s = re.sub(r"[*#_`>\[\]]", "", str(s or "")).strip()
    return _END_RE.sub("", s).strip()


def _looks_cut_off(said: str) -> bool:
    return bool(re.search(r"\b(and|so|but|because|or|like|then|which|that)\W*$", said.strip(), re.I))


def prepare_turn(rec: dict, messages: list[dict]) -> dict:
    """Phase 1 (under the interview lock, fast): decide which state this request builds on.
    Returns either {"reply": str} for an immediate answer, or a context for the LLM judge."""
    plan = rec["plan"]
    cur = rec["state"]
    base, said, matched = _locate(rec, messages)
    if base is None:
        base = cur
    if not matched:
        log.warning("[%s] could not match Vapi history to a snapshot; using committed state", rec["id"])
    if base.get("ended"):
        return {"reply": "Thank you, " + END_PHRASE + "."}
    if not said:
        return {"reply": base.get("last_say") or plan["questions"][base["q_idx"]]["ask"]}
    st = copy.deepcopy(base)
    active = st["active_before"] + (time.time() - st["session_started"])
    allowed, progress = _allowed_actions(st, plan, active)
    rec["turn_seq"] = rec.get("turn_seq", 0) + 1
    return {"st": st, "said": said, "active": active, "allowed": allowed, "progress": progress, "ts": time.time(),
            "req": rec["turn_seq"], "ai_n": sum(1 for m in messages if m.get("role") == "assistant" and _content(m)) + 1}


async def judge_turn(prep: dict, plan: dict) -> tuple[dict, int, bool]:
    """Phase 2 (NO lock held): ask the LLM. Never raises."""
    t0 = time.time()
    failed = False
    try:
        d = await _judge(prep["st"], plan, prep["said"], prep["allowed"])
        if not isinstance(d, dict):
            raise ValueError("judge returned non-object")
    except Exception as e:  # never let the interview stall on an LLM failure
        failed = True
        if _looks_cut_off(prep["said"]) and "invite_continue" in prep["allowed"]:
            d = {"action": "invite_continue"}
        else:
            d = {"action": prep["progress"], "ack": "Thank you."}
        log.warning("judge failed (%s); falling back to %s", e, d["action"])
    return d, int((time.time() - t0) * 1000), failed


def apply_turn(rec: dict, prep: dict, d: dict, latency_ms: int, failed: bool) -> str:
    """Phase 3 (under the lock): turn the decision into words and commit the new state."""
    plan = rec["plan"]
    qs = plan["questions"]
    st, said, active, allowed, progress = prep["st"], prep["said"], prep["active"], prep["allowed"], prep["progress"]
    q = qs[st["q_idx"]]

    action = d.get("action") if d.get("action") in allowed else progress
    if action == "follow_up" and not _clean(d.get("followup")):
        action = progress
    ack = _clean(d.get("ack")) or "Thank you."

    if action == "next_question":
        nxt = _next_index(st, plan, active)
        if nxt is None:
            action = "end"
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
        st["q_idx"] = nxt
        nq = qs[nxt]
        prefix = "Final question. " if nxt == len(qs) - 1 else ""
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
    if failed:
        st["judge_failures"] = st.get("judge_failures", 0) + 1

    now = time.time()
    st["log"].append({"role": "candidate", "text": said, "q_id": q["id"], "t": round(active),
                      "ts": prep.get("ts", now)})
    st["log"].append({"role": "ai", "text": say, "q_id": qs[st["q_idx"]]["id"], "action": action,
                      "t": round(active), "ts": now, "judge_ms": latency_ms, **({"fallback": True} if failed else {})})
    st["last_active"] = active
    st["last_say"] = say
    st["ai_n"] = prep["ai_n"]

    # A newer request for this call already committed: this one is stale (Vapi has moved on).
    if prep["req"] < rec.get("committed_req", 0):
        return say
    rec["committed_req"] = prep["req"]
    st["seq"] = max(s["seq"] for s in rec.get("snapshots") or [{"seq": 0}]) + 1
    rec.setdefault("snapshots", []).append(_snap(st))
    rec["snapshots"] = rec["snapshots"][-SNAPSHOTS_KEPT:]
    rec["state"] = st
    if st["ended"]:
        rec["status"] = "completed"
    return say


async def handle_turn(rec: dict, messages: list[dict]) -> str:
    """Single-call convenience (no lock splitting). The server uses the three phases directly."""
    if rec.get("state") is None:
        start_session(rec)
    prep = prepare_turn(rec, messages)
    if "reply" in prep:
        return prep["reply"]
    d, ms, failed = await judge_turn(prep, rec["plan"])
    return apply_turn(rec, prep, d, ms, failed)


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


def proctoring_summary(rec: dict) -> dict:
    return proctor_mod.summary(rec)


async def _score_once(rec: dict, transcript: str, model: str) -> dict:
    if llm.MOCK:
        return _mock_score(rec)
    plan_view = {k: rec["plan"][k] for k in ("role", "competencies", "questions", "resume_claims_to_verify")}
    user = prompts.SCORE_USER_TEMPLATE.format(plan=json.dumps(plan_view, ensure_ascii=False), transcript=transcript)
    out = await llm.complete_json(prompts.SCORE_SYSTEM, user, model, temperature=0.1, max_tokens=6000,
                                  timeout=240)
    if not isinstance(out.get("questions"), list) or not out["questions"]:
        raise ValueError(f"{model} returned a report without per-question scores")
    out["_model"] = model
    return out


def _coerce_score(v):
    if v is None or v == "":
        return None
    try:
        return max(1, min(5, int(round(float(v)))))
    except (TypeError, ValueError):
        return None


async def score_interview(rec: dict) -> dict:
    plan = rec["plan"]
    st = rec["state"]
    transcript = build_transcript(rec)
    passes = max(1, int(os.getenv("SCORING_PASSES") or llm.default_scoring_passes()))
    models = llm.scoring_models(passes)
    raw = await asyncio.gather(*[_score_once(rec, transcript, m) for m in models], return_exceptions=True)
    results = [r for r in raw if isinstance(r, dict)]
    failed_passes = [f"{m}: {r}" for m, r in zip(models, raw) if not isinstance(r, dict)]
    if not results:
        raise RuntimeError("All scoring passes failed: " + " | ".join(failed_passes)[:500])
    passes = len(results)
    for r in results:
        r["questions"] = [qr for qr in (r.get("questions") or []) if isinstance(qr, dict)]
        for qr in r["questions"]:
            qr["q_id"] = str(qr.get("q_id", ""))
            qr["score"] = _coerce_score(qr.get("score"))
    rep = results[0]
    review = [str(x) for x in (rep.get("human_review_reasons") or [])]
    if failed_passes:
        review.append(f"{len(failed_passes)} scoring model(s) failed; report is based on {passes} model(s)")
    recs = [r.get("recommendation") for r in results if r.get("recommendation") in RECOMMENDATIONS]
    if len(set(recs)) > 1:
        review.append(f"Scoring models disagree on the recommendation ({', '.join(recs)}). Read the answers yourself.")
    qmap = {q["id"]: q for q in plan["questions"]}

    # drop questions the model invented, add ones it forgot
    rep["questions"] = [qr for qr in rep["questions"] if qr["q_id"] in qmap]
    got = {qr["q_id"] for qr in rep["questions"]}
    for q in plan["questions"]:
        if q["id"] not in got:
            rep["questions"].append({"q_id": q["id"], "score": None, "evidence": [], "covered_points": [],
                                     "missed_points": [], "rationale": "Not returned by the scoring model."})
            if q["scored"]:
                review.append(f"{q['id']}: scoring model returned no score")
    order = {q["id"]: i for i, q in enumerate(plan["questions"])}
    rep["questions"].sort(key=lambda qr: order[qr["q_id"]])

    # consistency check across passes
    if passes > 1:
        by_q = {}
        for r in results:
            for qr in r.get("questions", []):
                if qr["score"] is not None:
                    by_q.setdefault(qr["q_id"], []).append(qr["score"])
        for qr in rep["questions"]:
            vals = by_q.get(qr["q_id"], [])
            if len(vals) > 1:
                if max(vals) - min(vals) > 1:
                    review.append(f"{qr['q_id']}: scoring unstable across passes ({vals})")
                qr["score"] = round(sum(vals) / len(vals))

    # evidence verification: quotes must exist in what the candidate actually said
    n_ev = n_ok = 0
    for qr in rep["questions"]:
        q = qmap[qr["q_id"]]
        cand_lines = [e["text"] for e in st["log"] if e["role"] == "candidate" and e["q_id"] == qr["q_id"]]
        all_lines = [e["text"] for e in st["log"] if e["role"] == "candidate"]
        ok_any = False
        qr["evidence"] = [ev for ev in (qr.get("evidence") or []) if isinstance(ev, dict)]
        for ev in qr["evidence"]:
            ev["verified"] = _verify_quote(ev.get("quote", ""), cand_lines)
            if ev["verified"] == "unverified" and _verify_quote(ev.get("quote", ""), all_lines) != "unverified":
                ev["verified"] = "other_question"  # real quote, but from a different answer
            n_ev += 1
            if ev["verified"] != "unverified":
                n_ok += 1
                ok_any = True
        if qr["score"] is not None and qr["score"] > 1 and not ok_any:
            review.append(f"{qr['q_id']}: score {qr['score']} has no verifiable quote")
        qr["ask"] = q["ask"]
        qr["type"] = q["type"]
        qr["competency_id"] = q.get("competency_id")
        if not q["scored"]:
            qr["score"] = None

    # weighted overall computed in code, not by the LLM
    comp_scores = {}
    for qr in rep["questions"]:
        if qr["score"] is not None and qr.get("competency_id"):
            comp_scores.setdefault(qr["competency_id"], []).append(qr["score"])
    num = den = 0.0
    for c in plan["competencies"]:
        vals = comp_scores.get(c["id"])
        if vals:
            num += c["weight"] * (sum(vals) / len(vals))
            den += c["weight"]
    q_scores = [qr["score"] for qr in rep["questions"] if qr["score"] is not None]
    overall = round(num / den, 2) if den else (round(sum(q_scores) / len(q_scores), 2) if q_scores else None)

    if rep.get("recommendation") not in RECOMMENDATIONS:
        review.append(f"Scoring model gave an invalid recommendation ({rep.get('recommendation')!r})")
        rep["recommendation"] = "maybe"
    if overall is not None and ((overall < 2.5 and rep["recommendation"] in ("yes", "strong_yes")) or
                                (overall >= 4 and rep["recommendation"] == "no")):
        review.append(f"Recommendation '{rep['recommendation']}' does not match the computed score {overall}")

    asked = {e["q_id"] for e in st["log"] if e["role"] == "candidate"}
    skipped = [x for x in st.get("skipped", []) if x not in asked]
    missing = [q["id"] for q in plan["questions"] if q["id"] not in asked and q["id"] not in skipped]
    if skipped:
        review.append(f"Skipped to save time: {', '.join(skipped)}")
    if missing:
        review.append(f"Questions not reached: {', '.join(missing)}")
    if not st.get("ended"):
        review.append("Interview did not reach its normal end (dropped call or candidate left)")
    if st.get("judge_failures"):
        review.append(f"Live AI failed on {st['judge_failures']} turn(s); the interviewer used a safe fallback")
    if st.get("reconnects"):
        review.append(f"Call reconnected {st['reconnects']} time(s)")

    proctor = proctor_mod.summary(rec)
    if proctor["reasons"]:
        review.append(f"Integrity risk {proctor['risk'].upper()}: " + "; ".join(proctor["reasons"]))

    rep["computed"] = {
        "overall": overall,
        "overall_pct": round((overall - 1) / 4 * 100) if overall is not None else None,
        "questions_asked": len(asked), "questions_planned": len(plan["questions"]),
        "evidence_verified": f"{n_ok}/{n_ev}",
        "scoring_passes": passes,
        "scoring_models": [r.get("_model") for r in results if r.get("_model")],
        "avg_turn_latency_ms": _avg([e.get("judge_ms") for e in st["log"] if e.get("judge_ms") is not None]),
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
