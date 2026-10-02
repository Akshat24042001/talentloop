"""Communication signals from what the candidate said: computed from the words and the timeline only.

Deterministic and explainable: every number can be traced to the transcript. No AI is involved and nothing is
inferred from the face or the voice (emotion recognition from biometrics in recruitment is prohibited in the EU,
AI Act art. 5(1)(f), and unreliable anywhere). These are cues for a person to look at, never a score.
"""
import re

FILLERS = re.compile(r"\b(um+|uh+|erm+|hmm+|like|you know|basically|actually|sort of|kind of|i mean)\b", re.I)
HEDGES = re.compile(r"\b(maybe|perhaps|probably|i think|i guess|i suppose|not sure|i'm not sure|might|possibly|somewhat)\b", re.I)
OWN_I = re.compile(r"\bi (built|led|designed|wrote|created|owned|decided|implemented|fixed|drove|managed|delivered|improved|reduced|increased)\b", re.I)
OWN_WE = re.compile(r"\bwe (built|led|designed|wrote|created|owned|decided|implemented|fixed|drove|managed|delivered|improved|reduced|increased)\b", re.I)
SPECIFIC = re.compile(r"\b\d[\d,.]*\s*(%|percent|ms|seconds?|minutes?|hours?|days?|weeks?|months?|years?|lakhs?|crores?|k\b|users|customers|people|x\b)", re.I)
POS = re.compile(r"\b(enjoy|enjoyed|love|loved|excited|proud|happy|glad|great|learned|interesting|grateful|motivated)\b", re.I)
NEG = re.compile(r"\b(hate|hated|terrible|awful|frustrat\w*|annoy\w*|angry|stupid|bad manager|toxic|boring|stress\w*)\b", re.I)


def _rate(n: int, words: int) -> float:
    return round(100 * n / words, 1) if words else 0.0


def analyze(rec: dict) -> dict | None:
    st = rec.get("state") or {}
    log = [e for e in st.get("log") or [] if e.get("text")]
    cand = [e for e in log if e["role"] == "candidate"]
    if not cand:
        return None
    ai = [e for e in log if e["role"] == "ai"]
    cw = sum(len(e["text"].split()) for e in cand)
    aw = sum(len(e["text"].split()) for e in ai)
    text = " ".join(e["text"] for e in cand)
    per_q: dict[str, list[str]] = {}
    for e in cand:
        per_q.setdefault(e.get("q_id") or "", []).append(e["text"])
    lengths = [len(" ".join(v).split()) for v in per_q.values()]
    own_i, own_we = len(OWN_I.findall(text)), len(OWN_WE.findall(text))
    pos, neg = len(POS.findall(text)), len(NEG.findall(text))
    timing = [x for x in (rec.get("events") or []) if x.get("type") == "answer_timing"]
    signals = {
        "candidate_share": round(100 * cw / (cw + aw)) if cw + aw else 0,
        "words": cw,
        "answers": len(per_q),
        "avg_answer_words": round(sum(lengths) / len(lengths)) if lengths else 0,
        "short_answers": sum(1 for n in lengths if n < 15),
        "filler_per_100": _rate(len(FILLERS.findall(text)), cw),
        "hedge_per_100": _rate(len(HEDGES.findall(text)), cw),
        "specifics": len(SPECIFIC.findall(text)),
        "ownership": {"i": own_i, "we": own_we},
        "tone": "positive" if pos > neg + 1 else "negative" if neg > pos + 1 else "neutral",
        "tone_words": {"positive": pos, "negative": neg},
        "questions_asked": sum(1 for e in cand if e["text"].strip().endswith("?")),
        "timed_answers": len(timing),
    }
    notes = []
    if signals["short_answers"] >= max(2, len(lengths) // 2):
        notes.append("Many answers were short (under 15 words): check whether follow-ups got more depth.")
    if signals["filler_per_100"] >= 8:
        notes.append("Frequent filler words. Often nerves or second-language speaking; not a skill signal on its own.")
    if signals["hedge_per_100"] >= 4:
        notes.append("Many hedges (maybe, I think, not sure) in the answers.")
    if own_we >= 3 and own_i == 0:
        notes.append("Described work as 'we' throughout, never 'I': ask what they personally did.")
    if signals["specifics"] >= 3:
        notes.append(f"Gave {signals['specifics']} concrete figures (numbers, durations, scale).")
    if neg > pos + 1:
        notes.append("Some negative language about past work or people.")
    signals["notes"] = notes
    return signals
