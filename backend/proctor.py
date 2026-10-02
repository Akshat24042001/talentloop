"""Proctoring and interview analytics, computed from the event log at read time.

Available as soon as events exist, independent of AI scoring (which can fail or still be running).
Signals are evidence for a human to review, never an automatic verdict.
"""
import time

LABELS = {
    "tab_hidden": "Left the interview tab", "tab_visible": "Returned to the interview tab",
    "window_blur": "Switched to another window or app", "window_focus": "Came back to the interview window",
    "fullscreen_exit": "Exited full screen", "fullscreen_enter": "Entered full screen",
    "paste": "Pasted text", "copy": "Copied text", "cut": "Cut text", "context_menu": "Opened right-click menu",
    "shortcut": "Used a keyboard shortcut", "print_screen": "Pressed Print Screen",
    "multi_monitor": "More than one screen connected", "window_small": "Shrank the browser window",
    "screen_share_started": "Started screen sharing", "screen_share_stopped": "Stopped screen sharing",
    "screen_share_denied": "Refused screen sharing", "screen_share_not_monitor": "Shared a window/tab, not the whole screen",
    "mute_on": "Muted microphone", "mute_off": "Unmuted microphone",
    "face_missing_start": "No face visible on camera", "face_missing_end": "Face visible again",
    "multiple_faces": "More than one face on camera", "face_check_unavailable": "Face detection could not run",
    "network_offline": "Internet connection lost", "network_online": "Internet connection back",
    "call_start": "Call started", "call_end": "Call ended", "call_dropped": "Call dropped unexpectedly",
    "ended_by_candidate": "Candidate ended the interview", "recording_upload_failed": "Part of the recording failed to upload",
    "recorder_unsupported": "Browser could not record video", "ai_audio_not_recorded": "Interviewer voice could not be added to the recording",
    "session_start": "Joined the call", "device_changed": "Rejoined from a different device or browser",
    "ip_changed": "Rejoined from a different network (IP)", "reconnect_denied": "Tried to rejoin after the allowed window",
    "camera_off": "Camera stopped", "mic_off": "Microphone stopped", "devtools_suspected": "Browser developer tools may be open",
    "speaker_voice_while_muted": "Voice detected while muted",
    "integrity_warning": "Interviewer warned the candidate", "disqualified": "Interview stopped: rules broken after warnings",
    "multi_monitor_removed": "Second screen disconnected", "screen_changed": "Screen setup changed",
    "liveness_passed": "Passed the head-turn check", "liveness_failed": "Did not complete the head-turn check",
    "virtual_camera": "Virtual camera software in use", "identity_match": "Face matched the registration photo",
    "identity_mismatch": "Face did not match the registration photo", "person_changed": "A different face than at the start",
    "identity_check_unavailable": "Face match could not run", "answer_timing": "Answer timing",
    "answer_pattern": "Long silences before long, fluent answers (possible reading)", "second_voice": "Possible second voice in the room",
    "quick_switch": "Looked away from the interview briefly (tab or app)", "looking_away": "Head turned away from the screen for a while",
    "client_silent": "Interview page stopped reporting while the call went on (hidden, blocked or tampered)",
}
HIGH = {"integrity_warning", "disqualified", "multiple_faces", "screen_share_stopped", "paste", "device_changed", "screen_share_denied",
        "screen_share_not_monitor", "camera_off", "devtools_suspected", "speaker_voice_while_muted", "virtual_camera",
        "identity_mismatch", "person_changed", "client_silent"}
MEDIUM = {"tab_hidden", "window_blur", "fullscreen_exit", "copy", "cut", "shortcut", "multi_monitor", "print_screen",
          "face_missing_start", "ip_changed", "call_dropped", "reconnect_denied", "mute_on", "window_small",
          "context_menu", "mic_off", "liveness_failed", "answer_pattern", "second_voice", "quick_switch", "looking_away"}
PAIRS = {"tab_hidden": "tab_visible", "window_blur": "window_focus", "mute_on": "mute_off",
         "face_missing_start": "face_missing_end", "screen_share_stopped": "screen_share_started",
         "network_offline": "network_online"}


def _server_ts(ev: dict, rec: dict) -> float | None:
    """Event time on the server clock (seconds). Client clocks can be wrong by minutes, so the
    offset measured when events were posted is applied."""
    if isinstance(ev.get("server_ts"), (int, float)):
        return ev["server_ts"]
    ts = ev.get("ts")
    if not isinstance(ts, (int, float)):
        return None
    return (ts + (ev.get("offset_ms") or rec.get("clock_offset_ms") or 0)) / 1000


def _log(rec: dict) -> list[dict]:
    return (rec.get("state") or {}).get("log", [])


def interview_start(rec: dict) -> float | None:
    ts = [e["ts"] for e in _log(rec) if e.get("ts")]
    starts = [s.get("at") for s in rec.get("sessions", []) if s.get("at")]
    return min(ts + starts) if (ts or starts) else None


def question_at(rec: dict, ts: float) -> str | None:
    qid = None
    for e in _log(rec):
        if e.get("ts") and e["ts"] <= ts and e["role"] == "ai":
            qid = e.get("q_id")
    return qid


def _x(n: int, word: str = "time") -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def summary(rec: dict) -> dict:
    events = sorted([dict(e, _t=_server_ts(e, rec)) for e in rec.get("events", [])],
                    key=lambda e: (e["_t"] is None, e["_t"] or 0))
    start = interview_start(rec)
    end = max([e["_t"] for e in events if e["_t"]] + [e["ts"] for e in _log(rec) if e.get("ts")] or [time.time()])
    counts: dict[str, int] = {}
    open_: dict[str, float] = {}
    durations: dict[str, float] = {k: 0.0 for k in PAIRS}
    timeline = []
    per_q: dict[str, dict] = {}
    for e in events:
        typ = e.get("type", "?")
        counts[typ] = counts.get(typ, 0) + 1
        t = e["_t"]
        if t is not None:
            if typ in PAIRS:
                open_.setdefault(typ, t)
            for a, b in PAIRS.items():
                if typ == b and a in open_:
                    dur = max(0.0, t - open_.pop(a))
                    durations[a] += dur
                    e["_dur"] = dur
        sev = "high" if typ in HIGH else "medium" if typ in MEDIUM else "info"
        qid = question_at(rec, t) if t else None
        if sev != "info" and qid:
            pq = per_q.setdefault(qid, {"events": 0, "types": {}})
            pq["events"] += 1
            pq["types"][LABELS.get(typ, typ)] = pq["types"].get(LABELS.get(typ, typ), 0) + 1
        timeline.append({"type": typ, "label": LABELS.get(typ, typ), "severity": sev,
                         "t": round(t - start, 1) if (t and start) else None, "at": t, "q_id": qid,
                         "detail": e.get("detail", ""), "duration": round(e["_dur"], 1) if e.get("_dur") else None})
    for a, t0 in open_.items():  # never closed (e.g. tab still hidden when the call ended)
        durations[a] += max(0.0, end - t0)

    score, reasons = 0, []

    def add(points, why):
        nonlocal score
        score += points
        reasons.append(why)

    dq = rec.get("disqualified")
    warns = rec.get("warnings") or []
    if dq:
        add(10, f"Disqualified: {dq.get('reason', 'rules broken after warnings')}")
    elif warns:
        add(3 * len(warns), f"Warned by the interviewer {_x(len(warns))} for leaving the interview or a second screen")

    away = durations["tab_hidden"]
    if counts.get("tab_hidden", 0) >= 3 or away > 30:
        add(4 if away > 120 else 2, f"Left the interview tab {_x(counts.get('tab_hidden', 0))} ({int(away)}s away)")
    blur = durations["window_blur"]
    if blur > 20 or counts.get("window_blur", 0) >= 3:
        add(2, f"Another window or app had focus {_x(counts.get('window_blur', 0))} ({int(blur)}s)")
    if counts.get("multiple_faces"):
        add(4, f"More than one face seen on camera ({_x(counts['multiple_faces'])})")
    missing = durations["face_missing_start"]
    if missing > 15:
        add(4 if missing > 60 else 2, f"No face visible for {int(missing)}s in total")
    if counts.get("paste"):
        add(3, f"Pasted text {_x(counts['paste'])} during a voice interview")
    if counts.get("copy") or counts.get("cut"):
        add(1, "Copied text from the interview page")
    if counts.get("shortcut", 0) >= 3 or counts.get("print_screen"):
        add(1, "Used keyboard shortcuts / screenshots")
    if rec.get("settings", {}).get("require_screen_share"):
        off = durations["screen_share_stopped"]
        if counts.get("screen_share_stopped") or counts.get("screen_share_not_monitor"):
            add(4, f"Screen sharing interrupted {_x(counts.get('screen_share_stopped', 0))} ({int(off)}s without sharing)")
    if counts.get("multi_monitor"):
        add(2, "More than one screen was connected")
    if counts.get("device_changed"):
        add(3, "Rejoined from a different device or browser")
    if counts.get("ip_changed"):
        add(1, "Rejoined from a different network")
    muted = durations["mute_on"]
    if muted > 45:
        add(1, f"Microphone muted for {int(muted)}s in total")
    if counts.get("speaker_voice_while_muted"):
        add(3, "Voice picked up by the camera recording while the mic was muted")
    if counts.get("fullscreen_exit", 0) >= 2:
        add(1, f"Exited full screen {_x(counts['fullscreen_exit'])}")
    if counts.get("devtools_suspected"):
        add(3, "Browser developer tools may have been open")
    if counts.get("camera_off"):
        add(3, "Camera stopped during the interview")
    if counts.get("virtual_camera"):
        add(4, "A virtual camera (software video source) was used instead of a real camera")
    if counts.get("identity_mismatch"):
        add(5, "The face on camera did not match the registration photo")
    if counts.get("person_changed"):
        add(5, "A different face appeared than at the start of the interview")
    if counts.get("liveness_failed"):
        add(2, "Did not complete the head-turn liveness check")
    if counts.get("second_voice"):
        add(3 if counts["second_voice"] >= 2 else 2, f"Possible second voice in the room ({_x(counts['second_voice'])})")
    if counts.get("answer_pattern"):
        add(2, "Several long silences followed by long, fluent answers (possible reading)")
    risk = "high" if score >= 7 else "medium" if score >= 3 else "low"
    return {"risk": risk, "risk_points": score, "reasons": reasons, "counts": counts,
            "warnings": warns, "disqualified": dq,
            "durations": {k: int(v) for k, v in durations.items()},
            "hidden_seconds": int(away), "per_question": per_q,
            "timeline": [x for x in timeline if x["severity"] != "info" or x["type"] in
                         ("call_start", "call_end", "call_dropped", "session_start", "screen_share_started",
                          "face_missing_end", "tab_visible", "window_focus", "mute_off", "network_online",
                          "multi_monitor_removed")],
            # kept for the old report field name
            "flags": reasons}


def stats(rec: dict) -> dict:
    """Per-question time and words, talk ratio. Uses active interview seconds (t) from the log."""
    lg = _log(rec)
    qs = rec["plan"]["questions"]
    out, first_t = [], {}
    for e in lg:
        if e["role"] == "ai" and e.get("q_id") not in first_t:
            first_t[e["q_id"]] = e.get("t", 0)
    order = [q["id"] for q in qs if q["id"] in first_t]
    last_t = max([e.get("t", 0) for e in lg] or [0])
    cand_words = ai_words = 0
    for i, qid in enumerate(order):
        start = first_t[qid]
        stop = first_t[order[i + 1]] if i + 1 < len(order) else last_t
        answers = [e for e in lg if e["role"] == "candidate" and e.get("q_id") == qid]
        words = sum(len(e["text"].split()) for e in answers)
        out.append({"q_id": qid, "seconds": max(0, int(stop - start)), "answer_words": words,
                    "turns": len(answers),
                    "followups": sum(1 for e in lg if e["role"] == "ai" and e.get("q_id") == qid and e.get("action") == "follow_up"),
                    "repeats": sum(1 for e in lg if e["role"] == "ai" and e.get("q_id") == qid and e.get("action") == "clarify_repeat")})
    for e in lg:
        n = len(e["text"].split())
        if e["role"] == "candidate":
            cand_words += n
        else:
            ai_words += n
    answers = [len(e["text"].split()) for e in lg if e["role"] == "candidate"]
    st = rec.get("state") or {}
    return {"per_question": out, "candidate_words": cand_words, "interviewer_words": ai_words,
            "candidate_talk_share": round(cand_words / (cand_words + ai_words) * 100) if (cand_words + ai_words) else None,
            "avg_answer_words": round(sum(answers) / len(answers)) if answers else None,
            "active_minutes": round(last_t / 60, 1), "reconnects": st.get("reconnects", 0),
            "skipped": st.get("skipped", []), "judge_failures": st.get("judge_failures", 0)}
