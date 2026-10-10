"""The interview brain.

Design principle: CODE controls the interview (which question, how many follow-ups, time),
the LLM only judges the latest answer and writes the words. This is what keeps a voice
interviewer from drifting, skipping questions or running over time.
"""
import asyncio
import copy
from collections import deque
import json
import logging
import os
import re
import secrets
import time
from difflib import SequenceMatcher

from . import llm, prompts
from . import proctor as proctor_mod

log = logging.getLogger("brain")

END_PHRASE = "this concludes our interview"
CLOSING = ("That's everything I wanted to ask. Thanks so much for your time today, I really enjoyed the conversation. "
           "The HR team will go through it and get back to you soon. Take care, and " + END_PHRASE + ".")
# Lines Vapi speaks by itself (silence hooks in vapi_config). They appear in the history but are not ours.
IDLE_LINES = ("Take your time. Just let me know when you're ready.", "No rush. Are you still with me?")
SILENCE_LINE = ("I haven't heard anything for a while, so I'll pause the interview here. "
                "If this was a connection problem, please rejoin right away.")
TURN_TIMEOUT = float(os.getenv("TURN_TIMEOUT_SEC", "8"))
END_BUFFER_SEC = 40          # below this remaining time, wrap up
OVERTIME_SEC = 180           # HR-mandatory questions still get asked up to this long past the planned length
MAX_SESSIONS = int(os.getenv("MAX_RECONNECTS", "5")) + 1
QUESTION_TYPES = ("warmup", "hr_mandatory", "resume_probe", "jd_skill", "behavioral")
DEEP_TYPES = ("resume_probe", "jd_skill", "behavioral")     # questions that deserve a real answer before moving on
GENERIC_PROBE = {
    "resume_probe": "Could you walk me through one specific example of that, what you did yourself and how it turned out?",
    "jd_skill": "Can you make that concrete for me, a real situation where you used it and what you did?",
    "behavioral": "Could you take me through one real situation, what happened, what you did, and the result?",
}
# Recent live turns (timestamp, ok, ms) so the platform admin sees when the interviewer's model is failing.
TURN_STATS: deque = deque(maxlen=500)


def turn_health(window_sec: int = 3600) -> dict:
    now = time.time()
    rows = [r for r in TURN_STATS if now - r[0] <= window_sec]
    failed = sum(1 for r in rows if not r[1])
    return {"turns": len(rows), "failed": failed, "avg_ms": round(sum(r[2] for r in rows) / len(rows)) if rows else 0}
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
    # Fit the per-question budgets into the interview length. Budgets steer follow-ups: an over-full plan would
    # spend its time on early follow-ups and then have to skip later questions in a rush.
    avail = plan["duration_min"] * 60 - END_BUFFER_SEC - 30
    total = sum(q["time_budget_sec"] for q in qs)
    if total > avail:
        flex = [q for q in qs if q["type"] != "hr_mandatory"]
        fixed = total - sum(q["time_budget_sec"] for q in flex)
        room = max(avail - fixed, 60 * len(flex))
        k = room / max(1, sum(q["time_budget_sec"] for q in flex))
        for q in flex:
            q["time_budget_sec"] = max(45 if q["type"] == "warmup" else 60, int(q["time_budget_sec"] * k))
    plan["questions"] = qs
    plan["keyterms"] = [str(k)[:50] for k in (plan.get("keyterms") or []) if str(k).strip()][:50]
    plan.setdefault("company_facts", [])
    plan.setdefault("resume_claims_to_verify", [])
    plan.setdefault("do_not_ask", [])
    return plan


def plan_warnings(plan: dict, hr_questions: list[str] | None = None) -> list[str]:
    """Things HR must look at before sending the link. Shown on the HR page."""
    w = list(plan.get("grounding_notes") or [])
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


PLAN_DEADLINE_SEC = float(os.getenv("PLAN_DEADLINE_SEC", "25"))     # HR always has a plan within ~30 s
PLAN_HEDGE_SEC = float(os.getenv("PLAN_HEDGE_SEC", "10"))           # start a second model if the first is slow


GENERIC_RESUME_PROBE = "Walk me through one piece of work from your resume that you're proud of. What exactly was your part in it?"
_STOP = {"you", "your", "the", "and", "what", "how", "when", "why", "tell", "walk", "me", "about", "did", "can", "could", "would"}


def ground_plan(plan: dict, inp: dict) -> dict:
    """Make the plan safe before any candidate hears it (flows send AI interviews without HR review):
    - a resume question that quotes a number or a name the resume and JD don't contain is a made-up claim,
      so it is replaced by an open question about their real work;
    - near-duplicate questions are dropped;
    - every question HR wrote is in the plan, as a must-ask question."""
    src = f"{inp.get('resume', '')}\n{inp.get('jd', '')}".lower()
    notes = list(plan.get("grounding_notes") or [])
    kept, seen = [], []
    for q in plan["questions"]:
        if q["type"] == "resume_probe":
            nums = [n.strip(".,%") for n in re.findall(r"\d[\d,.%]*", q["ask"])]
            names = [w for w in re.findall(r"(?<![.?!]\s)(?<!^)\b[A-Z][a-zA-Z0-9&+.-]{2,}", q["ask"]) if w.lower() not in _STOP]
            missing = [n for n in nums if n and n not in src] + [w for w in names if w.lower().strip(".") not in src]
            if missing:
                notes.append(f"Replaced a resume question that mentioned {', '.join(missing[:3])}, which isn't in the resume or JD.")
                q = {**q, "ask": GENERIC_RESUME_PROBE, "grounding_fixed": True}
        if q["type"] != "hr_mandatory" and any(_match_score(q["ask"], s) > 0.8 or _match_score(s, q["ask"]) > 0.8 for s in seen):
            notes.append(f"Dropped a repeated question: {q['ask'][:80]}")
            continue
        if q.get("grounding_fixed") and GENERIC_RESUME_PROBE in seen:
            continue
        seen.append(q["ask"])
        kept.append(q)
    for hq in [str(x).strip() for x in inp.get("questions") or [] if str(x).strip()]:
        if not any(_match_score(hq, q["ask"]) >= 0.6 or _match_score(q["ask"], hq) >= 0.6 or hq.lower() in q["ask"].lower() for q in kept):
            kept.append({"id": f"hr{len(kept) + 1}", "type": "hr_mandatory", "ask": hq, "scored": True, "competency_id": plan["competencies"][0]["id"],
                         "good_answer_covers": [], "red_flags": [], "max_followups": 1, "time_budget_sec": 90})
            notes.append(f"Added your question the plan had left out: {hq[:80]}")
    plan["questions"] = kept or plan["questions"]
    if notes:
        plan["grounding_notes"] = notes
    return plan


async def generate_plan(inp: dict) -> dict:
    plan = await _generate_plan(inp)
    try:
        return normalize_plan(ground_plan(plan, inp))
    except Exception:
        log.exception("plan grounding failed; using the plan as generated")
        return plan


async def _generate_plan(inp: dict) -> dict:
    """inp: company, role, candidate_name, duration_min, jd, resume, questions (list[str]).

    Speed: the fast model with reasoning off and a compact output; if it hasn't answered after PLAN_HEDGE_SEC a
    second model is asked in parallel and the first valid plan wins. At PLAN_DEADLINE_SEC a template plan built
    from the JD, resume and HR questions is returned instead (marked source=template, so HR knows to review it)."""
    if llm.MOCK:
        return normalize_plan(_mock_plan(inp))
    user = prompts.PLAN_USER_TEMPLATE.format(
        company=inp.get("company", ""), role=inp.get("role", ""),
        candidate_name=inp.get("candidate_name", ""), duration_min=inp.get("duration_min", 20),
        jd=_trim(inp.get("jd", ""), 7000), resume=_trim(inp.get("resume", ""), 7000),
        questions="\n".join(inp.get("questions") or []) or "(none provided)",
    )
    lang = (inp.get("language") or "en").lower()
    if lang != "en":
        user += f"\n\nWrite every question and keyterm in {prompts.LANGUAGE_NAMES.get(lang, lang)} as it is naturally spoken."
    models = llm.plan_models()
    loop = asyncio.get_running_loop()
    t0 = loop.time()

    async def attempt(model: str) -> dict:
        left = max(3.0, PLAN_DEADLINE_SEC - (loop.time() - t0))
        out = await llm.complete_json(prompts.PLAN_SYSTEM, user, model, temperature=0.3, max_tokens=2600,
                                      timeout=left, fallbacks=[], fast=True, backup=False)
        plan = normalize_plan(out, inp.get("duration_min"))
        plan["source"], plan["model"] = "ai", model
        return plan

    deadline, hedge_at = t0 + PLAN_DEADLINE_SEC, t0 + PLAN_HEDGE_SEC

    def start(model: str) -> asyncio.Task:
        t = asyncio.create_task(attempt(model))
        t.add_done_callback(lambda x: x.cancelled() or x.exception())   # a losing attempt's error is expected
        return t

    tasks = {start(models[0])}
    next_i, errors = 1, []
    try:
        while tasks:
            now = loop.time()
            if now >= deadline:
                break
            can_hedge = next_i < len(models) and len(tasks) < 2
            timeout = hedge_at - now if can_hedge and now < hedge_at else deadline - now
            done, _ = await asyncio.wait(tasks, timeout=max(0.05, timeout), return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                tasks.discard(t)
                try:
                    plan = t.result()
                    plan["generated_ms"] = int((loop.time() - t0) * 1000)
                    return plan
                except Exception as e:
                    errors.append(f"{type(e).__name__}: {str(e)[:160]}")
            now = loop.time()
            # the first model is slow (hedge time passed) or an attempt failed: ask the next model too
            if next_i < len(models) and len(tasks) < 2 and now < deadline - 3 and (now >= hedge_at or done):
                tasks.add(start(models[next_i]))
                next_i += 1
    finally:
        for t in tasks:
            t.cancel()
    log.warning("plan: AI did not deliver in %.0fs (%s); using the template plan", loop.time() - t0, "; ".join(errors) or "timeout")
    plan = normalize_plan(template_plan(inp))
    plan["source"] = "template"
    plan["fallback_reason"] = "The AI took too long or failed" + (f" ({errors[-1][:120]})" if errors else "") + "."
    plan["generated_ms"] = int((loop.time() - t0) * 1000)
    return plan


def _trim(text: str, n: int) -> str:
    """Keep the start and the end (skills and requirements often sit at the bottom of a JD)."""
    text = (text or "").strip()
    return text if len(text) <= n else text[: int(n * 0.7)] + "\n[...]\n" + text[-int(n * 0.3):]


_CLAIM_VERBS = re.compile(r"\b(built|led|designed|developed|launched|managed|reduced|increased|improved|migrated|owned|delivered|"
                          r"implemented|closed|grew|achieved|handled|trained|automated|created)\b", re.I)


def template_plan(inp: dict) -> dict:
    """A sound interview plan without AI: warm-up, every HR question, probes of concrete resume claims, the JD's
    must-have skills, one behavioural question. Used when the AI is slow or down."""
    from . import resumes as _res, skills as _sk
    role = inp.get("role") or "this role"
    dur = max(5, min(60, _int(inp.get("duration_min"), 15)))
    qs = [{"id": "q1", "type": "warmup", "ask": "To start, please introduce yourself in about a minute: your current role and what you enjoy about it.",
           "scored": False, "good_answer_covers": [], "max_followups": 0, "time_budget_sec": 75, "competency_id": "c2"}]
    for t in [q.strip() for q in (inp.get("questions") or []) if q.strip()]:
        qs.append({"type": "hr_mandatory", "ask": t, "scored": True, "competency_id": "c1", "max_followups": 1, "time_budget_sec": 120,
                   "good_answer_covers": ["a direct answer", "a specific example", "relevant detail"]})
    lines = [ln.strip(" -•*\t") for ln in (inp.get("resume") or "").splitlines()]
    claims = [ln for ln in lines if 25 <= len(ln) <= 160 and (_CLAIM_VERBS.search(ln) or re.search(r"\d+\s*%|\d{2,}", ln))][:2]
    for cl in claims:
        short = cl if len(cl) <= 90 else cl[:87].rsplit(" ", 1)[0] + "..."
        qs.append({"type": "resume_probe", "competency_id": "c1", "scored": True, "max_followups": 2, "time_budget_sec": 180,
                   "ask": f"Your resume says: \"{short}\". Walk me through what you did yourself and what the result was.",
                   "good_answer_covers": ["their own contribution", "how they did it", "a measurable result"]})
    jd_skills = sorted(_sk.extract(inp.get("jd") or ""))
    cv_skills = set(_res.parse(inp.get("resume") or "")["skills"])
    for skl in ([x for x in jd_skills if x in cv_skills] + [x for x in jd_skills if x not in cv_skills])[:3]:
        qs.append({"type": "jd_skill", "competency_id": "c1", "scored": True, "max_followups": 1, "time_budget_sec": 150,
                   "ask": f"Tell me about a recent piece of work where you used {skl}. What was the problem and what did you do?",
                   "good_answer_covers": [f"hands-on use of {skl}", "a concrete problem", "the outcome"]})
    qs.append({"type": "behavioral", "competency_id": "c3", "scored": True, "max_followups": 1, "time_budget_sec": 150,
               "ask": "Tell me about a time something went wrong at work. What happened, what did you do, and what was the result?",
               "good_answer_covers": ["a real situation", "their own actions", "what they learned"]})
    cap = dur * 60 * 0.85            # drop the lowest-value optional questions until it fits
    while sum(q["time_budget_sec"] for q in qs) > cap and any(q["type"] in ("behavioral", "jd_skill", "resume_probe") for q in qs[1:]):
        for kind in ("behavioral", "jd_skill", "resume_probe"):
            idx = [i for i, q in enumerate(qs) if q["type"] == kind]
            if idx:
                qs.pop(idx[-1])
                break
    for i, q in enumerate(qs, 1):
        q["id"] = f"q{i}"
    return {"company": inp.get("company", ""), "role": role, "candidate_name": inp.get("candidate_name", ""), "duration_min": dur,
            "competencies": [{"id": "c1", "name": "Role skills", "weight": 0.6, "anchors": {"1": "Vague or generic answers", "3": "Relevant experience, some depth", "5": "Specific, hands-on, measurable results"}},
                             {"id": "c2", "name": "Communication", "weight": 0.2, "anchors": {"1": "Hard to follow", "3": "Clear enough", "5": "Clear, structured, concise"}},
                             {"id": "c3", "name": "Problem solving and ownership", "weight": 0.2, "anchors": {"1": "Blames others, no actions", "3": "Some ownership", "5": "Owns the problem and the fix"}}],
            "questions": qs, "keyterms": jd_skills[:25] + [inp.get("candidate_name", "")], "company_facts": [],
            "resume_claims_to_verify": claims, "do_not_ask": ["age", "marital status", "religion", "caste", "health", "family plans"]}


# ---------------------------------------------------------------------------
# Live interview state machine
# ---------------------------------------------------------------------------
SNAPSHOTS_KEPT = 12


# Fixed lines the interviewer speaks, per language. English, Hindi and Hinglish are written here; other languages
# are translated once by the AI when an interview is created (localize_lines) and fall back to English.
# END_PHRASE stays in English in every language: Vapi hangs up when it hears it.
LINES = {
    "en": {
        "opening": ("Hi {name}, thanks for joining. I'm an AI interviewer, not a person, and I'll talk with you about the {role} role{company}. "
                    "This conversation is recorded and transcribed so the hiring team can review it, and a person makes the final decision. "
                    "If you're not comfortable being recorded, just say so and we'll stop here. If you'd like me to repeat anything, just ask."),
        "practice": "Before we begin, here's a quick practice question that doesn't count, just to check we can hear each other well. How is your day going so far?",
        "after_practice": "Thanks, I can hear you clearly. That one didn't count. Now let's begin.",
        "start": "Okay, let's get started.",
        "welcome_back": "Welcome back {name}. It looks like we got disconnected. Let's continue from where we stopped.",
        "declined": ("No problem at all, {name}. I'll stop here and let the hiring team know you'd prefer a different format, "
                     "such as an interview with a person. Thank you for your time, and " + END_PHRASE + "."),
        "closing": CLOSING,
    },
    "hi": {
        "opening": ("नमस्ते {name}, जुड़ने के लिए धन्यवाद। मैं एक AI इंटरव्यूअर हूँ, कोई इंसान नहीं, और हम {role} रोल{company} के बारे में बात करेंगे। "
                    "यह बातचीत रिकॉर्ड और ट्रांसक्राइब की जाती है ताकि हायरिंग टीम इसे देख सके, और आख़िरी फ़ैसला एक इंसान लेता है। "
                    "अगर आप रिकॉर्डिंग से सहज नहीं हैं, तो बस बता दीजिए, हम यहीं रोक देंगे। कुछ दोबारा सुनना हो तो बेझिझक कहिए।"),
        "practice": "शुरू करने से पहले एक छोटा सा अभ्यास सवाल, जो गिना नहीं जाएगा, बस यह देखने के लिए कि आवाज़ ठीक आ रही है। आपका दिन अब तक कैसा रहा?",
        "after_practice": "धन्यवाद, आपकी आवाज़ साफ़ आ रही है। वह सवाल गिना नहीं गया। अब शुरू करते हैं।",
        "start": "ठीक है, शुरू करते हैं।",
        "welcome_back": "वापस आने के लिए धन्यवाद {name}। लगता है कनेक्शन टूट गया था। जहाँ रुके थे वहीं से आगे बढ़ते हैं।",
        "declined": "कोई बात नहीं {name}। मैं यहीं रोक रहा हूँ और हायरिंग टीम को बता दूँगा कि आप किसी और तरीके से, जैसे किसी इंसान के साथ, इंटरव्यू देना चाहेंगे। धन्यवाद, and " + END_PHRASE + ".",
        "closing": "मेरे सारे सवाल हो गए। अपना समय देने के लिए बहुत धन्यवाद। हायरिंग टीम इसे देखकर जल्द आपसे संपर्क करेगी। ध्यान रखिए, and " + END_PHRASE + ".",
    },
    "hi-en": {
        "opening": ("Hi {name}, join karne ke liye thanks. Main ek AI interviewer hoon, koi insaan nahi, aur hum {role} role{company} ke baare mein baat karenge. "
                    "Yeh conversation record aur transcribe hoti hai taaki hiring team ise review kar sake, aur final decision ek insaan leta hai. "
                    "Agar aap recording se comfortable nahi hain, toh bas bata dijiye, hum yahin rok denge. Kuch repeat karna ho toh bol dijiye. "
                    "Aap Hindi, English ya dono mix karke jawab de sakte hain."),
        "practice": "Shuru karne se pehle ek chhota practice question, jo count nahi hoga, bas yeh check karne ke liye ki awaaz theek aa rahi hai. Aapka din ab tak kaisa raha?",
        "after_practice": "Thanks, aapki awaaz clear aa rahi hai. Woh question count nahi hua. Ab shuru karte hain.",
        "start": "Theek hai, shuru karte hain.",
        "welcome_back": "Welcome back {name}. Lagta hai connection toot gaya tha. Jahan ruke the wahin se continue karte hain.",
        "declined": "Koi baat nahi {name}. Main yahin rok raha hoon aur hiring team ko bata doonga ki aap kisi aur format mein, jaise kisi insaan ke saath, interview dena chahenge. Thank you, and " + END_PHRASE + ".",
        "closing": "Mere saare questions ho gaye. Apna time dene ke liye bahut thanks. Hiring team ise review karke jaldi aapse contact karegi. Take care, and " + END_PHRASE + ".",
    },
}
_LINE_CACHE: dict[str, dict] = {}


def lines_for(rec: dict | None) -> dict:
    lang = ((rec or {}).get("settings") or {}).get("language") or "en"
    return {**LINES["en"], **LINES.get(lang, {}), **((rec or {}).get("lines") or {})}


async def localize_lines(language: str) -> dict:
    """Fixed lines for languages without a written set: translated once by the AI (cached), else English."""
    lang = (language or "en").lower()
    if lang in LINES or llm.MOCK:
        return {}
    if lang in _LINE_CACHE:
        return _LINE_CACHE[lang]
    name = prompts.LANGUAGE_NAMES.get(lang, lang)
    src = {k: v for k, v in LINES["en"].items()}
    try:
        out = await llm.complete_json(
            "Translate the values of this JSON object into natural spoken " + name + " for a polite job interview. Keep {name}, {role} "
            "and {company} placeholders exactly. Keep the English phrase '" + END_PHRASE + "' unchanged at the end where it appears. "
            "Output ONLY the JSON object with the same keys.", json.dumps(src, ensure_ascii=False), llm.FAST_MODEL, temperature=0.2,
            max_tokens=1500, timeout=30)
        good = {k: str(v) for k, v in (out or {}).items() if k in src and isinstance(v, str) and v.strip()
                and all(ph in v for ph in ("{name}", "{role}", "{company}") if ph in src[k])
                and (END_PHRASE not in src[k] or END_PHRASE in v)}
    except Exception as e:
        log.warning("could not translate interview lines to %s: %s", lang, e)
        good = {}
    _LINE_CACHE[lang] = good
    return good


async def translate_plan(plan: dict, from_lang: str, to_lang: str) -> dict:
    """The interview plan with every question spoken in to_lang: same questions, same order, same meaning (HR's must-ask questions keep
    their meaning word for word). Raises ValueError when a usable translation cannot be made, so the candidate is told instead of hearing
    a half-translated interview."""
    out = copy.deepcopy(plan)
    if from_lang == to_lang:
        return out
    if llm.MOCK:
        out["language"] = to_lang
        return out
    name = prompts.LANGUAGE_NAMES.get(to_lang, to_lang)
    src = {q["id"]: q["ask"] for q in plan["questions"]}
    system = ("You translate job interview questions for a voice interviewer. Translate each value into natural, polite spoken " + name +
              ", as an experienced interviewer from that region would say it aloud. Keep the exact meaning and every detail (names, numbers, "
              "tools, company and product names stay as they are, technical terms may stay in English where speakers normally say them in "
              "English). One question per value, no extra words. Output ONLY a JSON object with the same keys.")
    try:
        got = await llm.complete_json(system, json.dumps(src, ensure_ascii=False), llm.FAST_MODEL, temperature=0.2, max_tokens=2500, timeout=45)
    except Exception as e:
        raise ValueError(f"translation failed: {e}")
    if not isinstance(got, dict) or set(got) != set(src) or not all(isinstance(v, str) and len(v.strip()) >= 3 for v in got.values()):
        raise ValueError("translation incomplete")
    for q in out["questions"]:
        q["ask"] = " ".join(got[q["id"]].split())
    out["language"] = to_lang
    return out


def add_practice(plan: dict, rec: dict | None) -> None:
    """An unscored practice question first, so candidates can check their audio and settle in."""
    qs = plan.get("questions") or []
    if not qs or qs[0].get("practice"):
        return
    qs.insert(0, {"id": "practice", "type": "warmup", "practice": True, "ask": lines_for(rec)["practice"], "scored": False,
                  "competency_id": qs[0].get("competency_id") or "c1", "good_answer_covers": [], "red_flags": [], "max_followups": 0,
                  "time_budget_sec": 40})


# Saying no to recording at the start of the interview (English, Hindi, Hinglish).
_DECLINE_RE = re.compile(
    r"(\b(i\s+)?(do\s+not|don'?t|dont)\s+(consent|agree|want\s+(this|it|to\s+be)\s+record)|\bnot\s+(ok(ay)?|comfortable)\s+(with\s+)?(being\s+)?record"
    r"|\b(no|stop|don'?t|do\s+not)\s+(the\s+)?record(ing)?\b|\brecord(ing)?\s+(mat|nahi|nahin|na)\b|\bcomfortable\s+nahi"
    r"|रिकॉर्ड(िंग)?\s*(मत|नहीं)|सहज\s*नहीं|सहमत\s*नहीं)", re.I)


def declines_recording(said: str) -> bool:
    return bool(_DECLINE_RE.search(said or ""))


def _first_name(plan: dict) -> str:
    name = (plan.get("candidate_name") or "").strip()
    return name.split()[0] if name else "there"


def opening_message(plan: dict, rec: dict | None = None) -> str:
    """AI disclosure and recording consent first, then the practice question (or the first question)."""
    L = lines_for(rec)
    q0 = plan["questions"][0]
    company = f" at {plan['company']}" if plan.get("company") else ""
    intro = L["opening"].format(name=_first_name(plan), role=plan.get("role") or "open", company=company)
    return f"{intro} {q0['ask'] if q0.get('practice') else L['start'] + ' ' + q0['ask']}"


def _display(q: dict, text: str | None = None, kind: str = "question") -> dict:
    """What the candidate's screen shows while the interviewer asks it."""
    return {"q_id": q["id"], "main": q["ask"], "text": text or q["ask"], "kind": kind}


def question_label(plan: dict, qid: str, width: int = 70) -> str:
    """Human-readable name for a question in HR-facing text (never a bare id like 'q3')."""
    for i, q in enumerate(plan.get("questions", []), 1):
        if q["id"] == qid:
            ask = q["ask"] if len(q["ask"]) <= width else q["ask"][:width - 1].rstrip() + "…"
            return f'Question {i} ("{ask}")'
    return f"Question {qid}"


# ---------------------------------------------------------------------------
# Integrity warnings: the interviewer confronts the candidate, then ends the interview
# ---------------------------------------------------------------------------
VIOLATION_WHAT = {
    "tab_hidden": "left the interview screen",
    "window_blur": "switched to another window",
    "multi_monitor": "connected a second screen",
    "fullscreen_exit": "left full screen and didn't come back",
    "quick_switches": "kept switching away from the interview screen",
    "left_camera": "stepped out of the camera view",
    "multiple_people": "had someone else in view of the camera",
    "phone_visible": "had a phone in view of the camera",
    "earphones": "were wearing earphones or earbuds",
}
STAY = {"left_camera": "Please stay in view of the camera until we finish.",
        "multiple_people": "Please make sure you're alone for the rest of the interview.",
        "phone_visible": "Please put your phone away, out of reach, for the rest of the interview.",
        "earphones": "Please take out any earphones or earbuds and use your device's speaker for the rest of the interview."}
_ORD = {2: "second", 3: "third", 4: "fourth", 5: "fifth"}


def integrity_message(plan: dict, kind: str, n: int, max_warnings: int, question: str = "") -> tuple[str, bool]:
    """n = this violation's number (1-based). Returns (words to speak, terminate).
    A warning interrupts the interviewer (often mid-question) and after it Vapi just waits for the candidate,
    so it must end by asking the current question again, or the interview silently stalls."""
    name = _first_name(plan)
    again = f" Let's pick up where we were. {question}" if question else " Let's continue."
    what = VIOLATION_WHAT.get(kind, "broke the interview rules")
    if n > max_warnings:
        after = " after your final warning" if max_warnings else ""
        return (f"{name}, you {what}{after}. I'm sorry, but I have to stop the interview here. "
                f"The hiring team will be informed, and {END_PHRASE}."), True
    if n == max_warnings:
        lead = f"{name}, you {what}." if n == 1 else f"{name}, you {what}. That's the {_ORD.get(n, f'{n}th')} warning."
        return (f"{lead} This is your final warning. If it happens once more, "
                f"I'll have to end the interview. {STAY.get(kind, 'Please stay on this screen.')}{again}"), False
    return (f"{name}, I noticed you {what} just now. {STAY.get(kind, 'Please stay on this interview screen until we finish.')} "
            f"This has been noted for the hiring team.{again}"), False


def reminder_message(plan: dict, kind: str, question: str = "") -> str:
    """A friendly spoken reminder for camera-based signals (never ends the interview)."""
    name = _first_name(plan)
    what = {"left_camera": "I can't see you on camera right now. Please stay in view",
            "multiple_people": "It looks like someone else is in view. Please make sure you're on your own",
            "phone_visible": "I can see a phone. Please put it away, out of reach",
            "earphones": "It looks like you're wearing earphones. Please take them out and use your device's speaker",
            "second_voice": "I can hear another voice besides yours. Please make sure you're alone and answer in your own words",
            "quick_switches": "Please keep this interview screen in front of you"}.get(kind, "Please stay focused on the interview")
    again = f" Let's continue. {question}" if question else ""
    return f"{name}, quick reminder: {what}.{again}"


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
        first = f"{lines_for(rec)['welcome_back'].format(name=_first_name(plan))} {q['ask']}"
        st["display"] = _display(q)
        action = "resume"
    else:
        tokens = (st or {}).get("tokens", [])
        st = {"session": (st or {}).get("session", 0) + 1, "reconnects": 0, "q_idx": 0, "fu_used": 0,
              "stall": 0, "covered": {}, "notes": {}, "skipped": [], "judge_failures": 0,
              "ended": False, "active_before": 0.0, "last_active": 0.0, "q_started_active": 0.0,
              "session_started": now, "log": [], "tokens": tokens, "seq": 0,
              "display": _display(plan["questions"][0])}
        first = opening_message(plan, rec)
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


_NUMBER_WORDS = set("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
                    "sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred "
                    "thousand lakh lakhs crore million billion point and percent".split())
MATCH_MIN = 0.8


def _tokens(s: str) -> list[str]:
    # Numbers are dropped on both sides: the voice pipeline may spell them out ("5 days" -> "five days").
    return [w for w in _norm(s).split() if w not in _NUMBER_WORDS and not any(ch.isdigit() for ch in w)]


def _match_score(ours: str, heard: str) -> float:
    """How surely an assistant message in Vapi's history is a line we produced (0..1).
    Vapi may keep only the part actually spoken (the candidate interrupted), and may keep the text as it was
    formatted for speech (numbers spelled out, punctuation changed), so an exact comparison is not enough."""
    a, b = _norm(ours), _norm(heard)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if len(b) >= 12 and a.startswith(b):
        return 0.99
    ta, tb = _tokens(ours), _tokens(heard)
    if len(tb) < 3 or not ta:
        return 0.0
    full = SequenceMatcher(None, ta, tb, autojunk=False).ratio()
    prefix = SequenceMatcher(None, ta[:len(tb)], tb, autojunk=False).ratio() if len(tb) < len(ta) else 0.0
    return max(full, prefix)


def _same_utterance(ours: str, heard: str) -> bool:
    return _match_score(ours, heard) >= MATCH_MIN


def _user_text_after(messages: list[dict], i: int) -> str:
    return " ".join(_content(m) for m in messages[i + 1:] if m.get("role") == "user" and _content(m))


def _locate(rec: dict, messages: list[dict]) -> tuple[dict | None, str, bool]:
    """Find the state the candidate is actually replying to, and what they said since.

    Vapi's message history is the source of truth for what was really spoken. We walk its
    assistant messages from newest to oldest and match them to our snapshots. This handles:
      * re-requests for the same turn (candidate kept talking, text got longer),
      * a reply we generated that Vapi threw away unspoken (it is not in the history, so the
        state it produced is ignored instead of silently skipping a question),
      * idle prompts spoken by Vapi itself ("Take your time...") and the interviewer's integrity warnings,
        which we recognise and skip.
    An assistant line we cannot place is NOT skipped: skipping it used to rebuild the turn from an older
    question, and because the re-asked line was unrecognisable too, the interviewer asked the same question
    forever. Such a line is almost always our own latest reply, reworded by the voice pipeline, so the turn
    builds on the committed state instead.
    Returns (base_state, candidate_text, matched)."""
    snaps = rec.get("snapshots") or []
    others = list(IDLE_LINES) + [SILENCE_LINE] + [w.get("say", "") for w in (rec.get("warnings") or []) + (rec.get("reminders") or [])]
    ai_pos = [i for i, m in enumerate(messages) if m.get("role") == "assistant" and _content(m)]
    for rank in range(len(ai_pos) - 1, -1, -1):
        i = ai_pos[rank]
        heard = _content(messages[i])
        # A warning repeats the current question, so recognise it before comparing with our question lines.
        if any(_match_score(o, heard) >= 0.9 for o in others if o):
            continue
        scored = [(_match_score(s["state"].get("last_say", ""), heard), s) for s in reversed(snaps)]
        best = max([sc for sc, _ in scored] or [0.0])
        if best >= MATCH_MIN:
            hits = [s for sc, s in scored if sc >= best - 0.02]          # newest first on ties
            exact = [s for s in hits if s["state"].get("ai_n") == rank + 1]
            return (exact or hits)[0]["state"], _user_text_after(messages, i), True
        if any(_match_score(o, heard) >= 0.7 for o in others if o):
            continue
        if rec.get("state"):
            log.warning("[%s] unrecognised interviewer line in Vapi history (%r); building on the current state",
                        rec.get("id"), heard[:80])
            return rec["state"], _user_text_after(messages, i), False
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
    mandatory_left = any(x["type"] == "hr_mandatory" for x in qs[st["q_idx"] + 1:])
    if remaining <= END_BUFFER_SEC:
        # Out of time: HR's must-ask questions are still asked (up to OVERTIME_SEC past the end), never skipped.
        if mandatory_left and remaining > -OVERTIME_SEC:
            return ["next_question"], "next_question"
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


def _recent(st: dict, k: int = 8) -> str:
    lines = []
    for e in st["log"][-k:]:
        who = "INTERVIEWER" if e["role"] == "ai" else "CANDIDATE"
        lines.append(f"{who}: {e['text'][:500]}")
    return "\n".join(lines)


def answer_so_far(st: dict, q_id: str, said: str) -> str:
    """All of the candidate's words on the current main question, including its follow-ups: the speech-to-text often cuts one answer
    into several turns, and judging only the last piece makes a complete answer look thin (and a thin one look complete)."""
    start = 0
    for i, e in enumerate(st["log"]):
        if e["role"] == "ai" and e.get("action") == "next_question":
            start = i + 1                               # the interviewer moved on here: earlier turns belong to earlier questions
    parts = [e["text"] for e in st["log"][start:] if e["role"] == "candidate" and e.get("q_id") == q_id]
    parts.append(said)
    return " ".join(parts)[-2500:]


def followups_asked(st: dict, q_id: str) -> list[str]:
    return [e["text"] for e in st["log"] if e["role"] == "ai" and e.get("action") == "follow_up" and e.get("q_id") == q_id][-3:]


async def _judge(st: dict, plan: dict, said: str, allowed: list[str], faq: list | None = None, lang: str = "en",
                 cut_off: bool = False, unheard: str = "") -> dict:
    q = plan["questions"][st["q_idx"]]
    ctx = {
        "allowed": allowed, "q": q, "said": said,
        "fu_used": st["fu_used"], "already": st["covered"].get(q["id"], []),
    }
    if llm.MOCK:
        return _mock_turn(ctx)
    user = prompts.TURN_USER_TEMPLATE.format(
        allowed=json.dumps(allowed), role=plan.get("role", ""),
        facts=json.dumps(plan.get("company_facts", [])[:8], ensure_ascii=False),
        faq=json.dumps([{"q": f.get("q"), "a": f.get("a")} for f in (faq or [])][:30], ensure_ascii=False),
        language=prompts.LANGUAGE_NAMES.get(lang, lang),
        question=q["ask"], covers=json.dumps(q["good_answer_covers"]),
        already=json.dumps(ctx["already"]), fu_used=st["fu_used"], fu_max=q["max_followups"],
        next_q=(plan["questions"][st["q_idx"] + 1]["ask"] if st["q_idx"] + 1 < len(plan["questions"]) else "(none, this is the last question)"),
        recent=_recent(st), said=said[:2500], accommodation=plan.get("accommodation") or "(none)",
        so_far=answer_so_far(st, q["id"], said), fu_asked=json.dumps(followups_asked(st, q["id"]), ensure_ascii=False),
        uncovered=json.dumps([c for i, c in enumerate(q["good_answer_covers"]) if i not in ctx["already"]][:4], ensure_ascii=False),
        claims=json.dumps((plan.get("resume_claims_to_verify") or [])[:4], ensure_ascii=False),
        cut_off=("yes: the candidate started talking before you finished. They did NOT hear: " + json.dumps(unheard[:300], ensure_ascii=False)) if cut_off else "no",
    )
    return await asyncio.wait_for(
        llm.complete_json(prompts.TURN_SYSTEM, user, llm.FAST_MODEL, temperature=0.3, max_tokens=420,
                          timeout=TURN_TIMEOUT, backup=False),
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
    cur_q = plan["questions"][base["q_idx"]]
    cur_text = (base.get("display") or {}).get("text") or cur_q["ask"]
    # Barge-in: the candidate spoke while the interviewer was still talking, so Vapi stopped the voice and kept only the words actually
    # spoken. The interviewer must react to the interruption like a person would, not carry on as if its whole line was heard.
    last_ai = next((_content(m) for m in reversed(messages) if m.get("role") == "assistant" and _content(m)), "")
    cut_off = bool(last_ai and base.get("last_say")) and _match_score(base["last_say"], last_ai) >= MATCH_MIN \
        and len(_norm(last_ai)) < 0.8 * len(_norm(base["last_say"]))
    if cut_off and HOLD_ON.match(said.strip()):
        return {"reply": "Sure, go ahead. I'm listening."}
    if cut_off and GO_ON.match(said.strip()):
        return {"reply": f"Sure. {cur_text}"}
    # The interviewer's own voice coming back through the speakers is not an answer.
    if base.get("last_say") and _match_score(base["last_say"], said) >= 0.75:
        rec["echo_hits"] = rec.get("echo_hits", 0) + 1
        log.info("[%s] echo of our own line ignored", rec["id"])
        return {"reply": "I think I'm hearing my own voice. Headphones help. Please go ahead whenever you're ready." if rec["echo_hits"] <= 2
                else "Please go ahead."}
    # "Okay", "hmm", "yeah sure" while listening is a backchannel, not an answer (unless the question is a yes/no one).
    if BACKCHANNEL.match(said.strip()) and not YES_NO_START.match(cur_text.strip()) and cur_q.get("type") != "warmup":
        return {"reply": f"Take your time. {cur_text}" if len(said.split()) <= 3 else "Please go on."}
    st = copy.deepcopy(base)
    active = st["active_before"] + (time.time() - st["session_started"])
    allowed, progress = _allowed_actions(st, plan, active)
    rec["turn_seq"] = rec.get("turn_seq", 0) + 1
    out = {"st": st, "said": said, "active": active, "allowed": allowed, "progress": progress, "ts": time.time(),
           "req": rec["turn_seq"], "ai_n": sum(1 for m in messages if m.get("role") == "assistant" and _content(m)) + 1,
           "lang": (rec.get("settings") or {}).get("language") or "en", "faq": rec.get("company_faq") or [], "lines": lines_for(rec),
           "cut_off": cut_off, "unheard": (base.get("last_say") or "")[len(last_ai):] if cut_off else ""}
    first_turn = not any(e["role"] == "candidate" for e in st["log"])
    if first_turn and declines_recording(said):
        out["fixed"] = {"action": "declined"}
    elif plan["questions"][st["q_idx"]].get("practice"):
        out["fixed"] = {"action": progress if progress == "end" else "next_question", "ack": out["lines"]["after_practice"]}
    return out


async def judge_turn(prep: dict, plan: dict) -> tuple[dict, int, bool]:
    """Phase 2 (NO lock held): ask the LLM. Never raises."""
    t0 = time.time()
    failed = False
    if prep.get("fixed"):
        return dict(prep["fixed"]), 0, False
    try:
        d = await _judge(prep["st"], plan, prep["said"], prep["allowed"], prep.get("faq") or [], prep.get("lang") or "en",
                         prep.get("cut_off", False), prep.get("unheard", ""))
        if not isinstance(d, dict):
            raise ValueError("judge returned non-object")
    except Exception as e:  # never let the interview stall on an LLM failure
        failed = True
        d = _fallback(prep, plan)
        log.warning("judge failed (%s); falling back to %s", e, d["action"])
    ms = int((time.time() - t0) * 1000)
    TURN_STATS.append((time.time(), not failed, ms))
    return d, ms, failed


def _fallback(prep: dict, plan: dict) -> dict:
    """What to do when the live model fails or times out. Moving on is the LAST resort: a failing model must
    not turn into an interviewer that races through the questions."""
    st, said, allowed = prep["st"], prep["said"], prep["allowed"]
    q = plan["questions"][st["q_idx"]]
    words = len(said.split())
    if re.search(r"\b(repeat|say that again|didn'?t (get|catch|understand)|pardon|sorry\?)", said, re.I) and "clarify_repeat" in allowed:
        return {"action": "clarify_repeat", "rephrase": "Sure. " + q["ask"]}
    if _looks_cut_off(said) and "invite_continue" in allowed:
        return {"action": "invite_continue", "reply": "Please go on, I'm listening."}
    if q["type"] in DEEP_TYPES and words < 40 and "follow_up" in allowed and not _gives_up(said):
        return {"action": "follow_up", "followup": GENERIC_PROBE[q["type"]], "note": "Short answer; probed (live AI unavailable)."}
    if words < 6 and "invite_continue" in allowed and st["stall"] < 1 and not _gives_up(said):
        return {"action": "invite_continue", "reply": "Take your time. Could you tell me a bit more?"}
    return {"action": prep["progress"], "ack": "Thank you, that's helpful."}


# ---------------------------------------------------------------------------
# Guard rails on every string the model writes. The model decides; these make sure what is spoken can't
# derail the interview: an ack never asks something new, a follow-up is one real question on this topic,
# answers about the company only use approved facts, and anything else returns to the current question.
# ---------------------------------------------------------------------------
PROTECTED = re.compile(r"\b(age|how old|married|marital|husband|wife|children|kids|pregnan|religio|caste|god|pray|"
                       r"disabilit|health|illness|medical|nationality|politic|sexual|boyfriend|girlfriend)\b", re.I)
BACKCHANNEL = re.compile(r"^(?:(?:ok(?:ay)?|yeah|yes|yep|yup|right|sure|hmm+|mm+|uh[- ]?huh|alright|all right|got it|i see|"
                         r"cool|fine|great|go ahead|haan|ha|ji|theek hai|accha)[\s,.!]*){1,3}$", re.I)
HOLD_ON = re.compile(r"^(?:(?:sorry|wait|hold on|one (?:second|sec|moment|minute)|just a (?:second|sec|moment)|excuse me|actually|ek minute|ruko|"
                     r"can i (?:say|add) something|let me (?:say|add) something)[\s,.!]*){1,3}$", re.I)
GO_ON = re.compile(r"^(?:(?:sorry|okay|ok|yes|please)[\s,.]*)*(?:go on|go ahead|continue|carry on|please continue|you were saying|"
                   r"what were you saying|finish (?:your|the) question|complete (?:your|the) question)[\s,.!?]*$", re.I)
YES_NO_START = re.compile(r"^(?:do|does|did|are|is|was|were|can|could|will|would|have|has|had|should)\b", re.I)


def _sentences(s: str) -> list[str]:
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+", s or "") if x.strip()]


def safe_ack(s) -> str:
    """At most two short statements, no questions (a question in an ack makes the candidate answer it instead)."""
    out = [x for x in _sentences(_clean(s)) if "?" not in x][:2]
    txt = " ".join(out)
    return txt if txt and len(txt.split()) <= 30 else "Thank you."


def safe_followup(s, q: dict) -> str:
    """One question, on topic, not about protected traits, not a repeat of the original question."""
    f = _clean(s)
    qs = [x for x in _sentences(f) if x.endswith("?")]
    if not qs:
        return ""
    f = qs[0] if len(qs[0].split()) >= 4 else " ".join(qs[:2])
    if len(f.split()) > 40 or PROTECTED.search(f) or _match_score(q["ask"], f) > 0.85:
        return ""
    return f


def grounded(text: str, sources: list[str]) -> bool:
    """Every number in `text` (salary, dates, counts) must appear in the approved sources."""
    src = " ".join(sources).lower()
    nums = re.findall(r"\d[\d,.]*", text or "")
    return all(n.strip(".,") in src for n in nums)


def safe_reply(s, current: str, facts: list[str]) -> str:
    """A short answer that only uses approved facts, then back to the current question."""
    r = " ".join(_sentences(_clean(s))[:3])
    if not r or len(r.split()) > 70 or not grounded(r, facts):
        r = "That's a good question for the hiring team, and they'll follow up with you on it."
    if "?" not in r[-200:]:
        r = f"{r} Coming back to the interview: {current}"
    return r


def _gives_up(said: str) -> bool:
    return bool(re.search(r"\b(don'?t know|not sure|no idea|skip|pass|haven'?t (done|worked)|no experience|move on|next question)\b", said, re.I))


def apply_turn(rec: dict, prep: dict, d: dict, latency_ms: int, failed: bool) -> str:
    """Phase 3 (under the lock): turn the decision into words and commit the new state."""
    plan = rec["plan"]
    qs = plan["questions"]
    st, said, active, allowed, progress = prep["st"], prep["said"], prep["active"], prep["allowed"], prep["progress"]
    q = qs[st["q_idx"]]

    L = prep.get("lines") or lines_for(rec)
    if d.get("action") == "declined":
        rec["consent_declined"] = {"at": time.time(), "said": said[:300]}
        say = L["declined"].format(name=_first_name(plan))
        st["ended"] = True
        st["display"] = {"q_id": q["id"], "main": "", "text": "", "kind": "closing"}
        st["log"].append({"role": "candidate", "text": said, "q_id": q["id"], "t": round(active), "ts": prep.get("ts", time.time())})
        st["log"].append({"role": "ai", "text": say, "q_id": q["id"], "action": "end", "t": round(active), "ts": time.time(), "judge_ms": 0})
        st["last_active"], st["last_say"], st["ai_n"] = active, say, prep["ai_n"]
        rec["committed_req"] = max(prep["req"], rec.get("committed_req", 0))
        st["seq"] = max(x["seq"] for x in rec.get("snapshots") or [{"seq": 0}]) + 1
        rec.setdefault("snapshots", []).append(_snap(st))
        rec["state"] = st
        rec["status"] = "completed"
        return say
    if d.get("action") not in allowed:            # a confused model must not move the interview on by accident
        log.warning("[%s] judge chose %r (allowed %s); using the safe fallback", rec.get("id"), d.get("action"), allowed)
        d = {**_fallback(prep, plan), "covered": d.get("covered"), "note": d.get("note")}
    action = d.get("action") if d.get("action") in allowed else progress
    if action == "follow_up":
        fu = safe_followup(d.get("followup"), q)
        if fu:
            d = {**d, "followup": fu}
        elif q["type"] in DEEP_TYPES and not _gives_up(said):
            d = {**d, "followup": GENERIC_PROBE[q["type"]]}
        else:
            action = progress
    # Don't rush: a short answer to a substantive question, given in a fraction of its time, gets one probe
    # (or a nudge) before the interview moves on. This also covers a candidate cut off by end-of-speech detection.
    q_time = active - st.get("q_started_active", active)
    words = len(said.split())
    if action == "next_question" and q["type"] in DEEP_TYPES and not _gives_up(said) and q_time < q["time_budget_sec"] * 0.4 \
            and (words < 20 or (failed and words < 40)):
        if "follow_up" in allowed:
            action, d = "follow_up", {**d, "followup": _clean(d.get("followup")) or GENERIC_PROBE[q["type"]]}
        elif "invite_continue" in allowed and st["stall"] < 1 and words < 12:
            action, d = "invite_continue", {**d, "reply": "Take your time. Is there anything you'd like to add?"}
    # A confident-sounding but generic answer is not enough: the model said "move on", yet fewer than half of the key points were
    # addressed and it wrote a usable probe for the gap. Ask it while follow-ups remain.
    if action == "next_question" and q["type"] in DEEP_TYPES and "follow_up" in allowed and not _gives_up(said):
        covers = q.get("good_answer_covers") or []
        got = set(st["covered"].get(q["id"], [])) | {i for i in (d.get("covered") or []) if isinstance(i, int)}
        probe = safe_followup(d.get("followup"), q)
        if covers and len(got) * 2 < len(covers) and probe:
            action, d = "follow_up", {**d, "followup": probe, "note": (d.get("note") or "") + " Key points still missing; probed."}
    ack = safe_ack(d.get("ack"))
    current_q = (st.get("display") or {}).get("text") or q["ask"]
    facts = [str(x) for x in plan.get("company_facts") or []] + [f"{x.get('q', '')} {x.get('a', '')}" for x in prep.get("faq") or []]

    if action == "next_question":
        nxt = _next_index(st, plan, active)
        if nxt is None:
            action = "end"
    if action == "invite_continue":
        r = _clean(d.get("reply"))
        say = r if r and len(r.split()) <= 20 else "Please go on, I'm listening."
        st["stall"] += 1
    elif action == "follow_up":
        say = _clean(d.get("followup"))
        st["fu_used"] += 1
        st["stall"] = 0
        st["display"] = _display(q, say, "follow_up")
    elif action == "clarify_repeat":
        rp = _clean(d.get("rephrase"))
        say = rp if rp and "?" in rp and len(rp.split()) <= 60 and not PROTECTED.search(rp) else "Sure. " + current_q
        st["stall"] += 1
        if (st.get("display") or {}).get("kind") != "follow_up":
            st["display"] = _display(q, re.sub(r"^(sure|okay|of course|no problem)[.,!]?\s+", "", say, flags=re.I),
                                     "rephrase")
    elif action == "answer_candidate_question":
        say = safe_reply(d.get("reply"), current_q, facts)
        st["stall"] += 1
    elif action == "redirect":
        r = " ".join(_sentences(_clean(d.get("reply")))[:1])
        say = f"{r if r and '?' not in r and len(r.split()) <= 25 else 'Let us stay with the interview.'} {current_q}"
        st["stall"] += 1
    elif action == "next_question":
        skipped_now = nxt > st["q_idx"] + 1
        st["q_idx"] = nxt
        nq = qs[nxt]
        prefix = ("In the interest of time, let's move on. " if skipped_now else "") + ("Final question. " if nxt == len(qs) - 1 else "")
        say = f"{ack} {prefix}{nq['ask']}"
        st["fu_used"] = 0
        st["stall"] = 0
        st["q_started_active"] = active
        st["display"] = _display(nq)
    else:  # end
        say = f"{ack} {L['closing']}"
        st["ended"] = True
        st["display"] = {"q_id": q["id"], "main": "", "text": "", "kind": "closing"}

    cov = set(st["covered"].get(q["id"], []))
    for i in d.get("covered") or []:
        if isinstance(i, int) and 0 <= i < len(q["good_answer_covers"]):
            cov.add(i)
    st["covered"][q["id"]] = sorted(cov)
    if d.get("note"):
        st["notes"].setdefault(q["id"], []).append(_clean(d["note"])[:200])
    if d.get("signal") in ("scripted", "contradiction") and not q.get("practice") and q.get("type") != "warmup":
        st.setdefault("signals", []).append({"q_id": q["id"], "kind": d["signal"], "detail": _clean(str(d.get("signal_detail") or ""))[:160],
                                             "t": round(active)})
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
    plan_view["live_interviewer_signals"] = ((rec.get("state") or {}).get("signals") or [])[:12]
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
                review.append(f"{question_label(plan, q['id'])}: scoring model returned no score")
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
                    review.append(f"{question_label(plan, qr['q_id'])}: scoring unstable across passes ({vals})")
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
        if not cand_lines and qr["score"] is not None:
            # never asked or never answered: nothing to score, whatever the model says
            review.append(f"{question_label(plan, qr['q_id'])}: not answered in the interview, so not scored")
            qr["score"], qr["unscored_reason"] = None, "not answered"
        elif qr["score"] is not None and qr["score"] > 1 and not ok_any:
            # a score the transcript can't back is withheld, not counted: a person decides
            review.append(f"{question_label(plan, qr['q_id'])}: the AI's score ({qr['score']}) had no quote found in the transcript; not counted")
            qr["score"], qr["unscored_reason"] = None, "no verifiable evidence"
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
        review.append("Skipped to save time: " + "; ".join(question_label(plan, x) for x in skipped))
    if missing:
        review.append("Questions not reached: " + "; ".join(question_label(plan, x) for x in missing))
    dq = rec.get("disqualified")
    if dq:
        review.insert(0, f"DISQUALIFIED: {dq.get('reason', 'interview ended for integrity violations')}")
    elif not st.get("ended"):
        review.append("Interview did not reach its normal end (dropped call or candidate left)")
    if st.get("judge_failures"):
        review.append(f"Live AI failed on {st['judge_failures']} turn(s); the interviewer used a safe fallback")
    if st.get("reconnects"):
        review.append(f"Call reconnected {st['reconnects']} time(s)")

    au = rep.get("authenticity") if isinstance(rep.get("authenticity"), dict) else {}
    lines = [e["text"] for e in st["log"] if e["role"] == "candidate"]
    sigs = [x for x in (au.get("signals") or []) if isinstance(x, dict) and x.get("sign")]
    for x in sigs:                                     # a sign is only as good as its quote
        x["verified"] = _verify_quote(str(x.get("quote") or ""), lines) if x.get("quote") else "unverified"
    level = au.get("level") if au.get("level") in ("natural", "some_signs", "likely_assisted") else "natural"
    if level == "likely_assisted" and sum(1 for x in sigs if x["verified"] != "unverified") < 2:
        level = "some_signs"                           # "likely" needs two signs backed by real quotes
    rep["authenticity"] = {"level": level, "signals": sigs[:6], "note": str(au.get("note") or "")[:400]}
    if level != "natural":
        review.append("Answers may not be the candidate's own (" + ("likely" if level == "likely_assisted" else "some signs")
                      + "): " + "; ".join(x["sign"][:80] for x in sigs[:3]))

    proctor = proctor_mod.summary(rec)
    other = [r for r in proctor["reasons"] if not r.startswith("Disqualified")]
    if other:
        review.append(f"Integrity risk {proctor['risk'].upper()}: " + "; ".join(other))

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
