"""Builds the transient Vapi assistant for one interview call.

Vapi handles: browser audio (WebRTC), speech-to-text, text-to-speech, turn-taking, recording.
Our server handles: every word the interviewer says (Vapi calls us as a "custom-llm").
"""
import os

from .brain import END_PHRASE, IDLE_LINES, SILENCE_LINE

THINKING_REGEX = (r"(let me think|let me see|give me a (second|moment|minute)|one (second|moment|minute)|"
                  r"hmm+|umm+|uhh+|how do i put|what i mean is|so basically|actually)\s*[.,]?\s*$")


def _env(k, d=""):
    return os.getenv(k, d).strip()


def public_url() -> str:
    """PUBLIC_URL if set, else the URL the hosting platform gives us (Render, Railway)."""
    url = _env("PUBLIC_URL") or _env("RENDER_EXTERNAL_URL")
    if not url and _env("RAILWAY_PUBLIC_DOMAIN"):
        url = "https://" + _env("RAILWAY_PUBLIC_DOMAIN")
    return url.rstrip("/")


def build_assistant(iid: str, plan: dict, first_message: str, token: str) -> dict:
    """token: per-session secret placed in the LLM and webhook URLs, so a dead or duplicate call
    can't write into the current session. NOTE: this whole config passes through the candidate's
    browser (vapi.start), so the token is visible to the candidate. It protects against stale calls
    and people without the link, not against the candidate. See REVIEW.md for the private-key route."""
    public = public_url()
    if not public.startswith("https://"):
        raise RuntimeError("PUBLIC_URL must be your https tunnel URL (cloudflared/ngrok). Vapi must reach this server.")

    mode = _env("ENDPOINTING_MODE", "smart")  # smart | patient
    if mode == "patient":
        # Fixed, generous silence window after every AI question. Use if candidates get cut off.
        start_plan = {"waitSeconds": 0.6, "customEndpointingRules": [
            {"type": "customer", "regex": THINKING_REGEX, "regexOptions": [{"type": "ignore-case", "enabled": True}],
             "timeoutSeconds": 5.0},
            {"type": "assistant", "regex": ".", "timeoutSeconds": float(_env("PATIENT_TIMEOUT_SEC", "2.2"))},
        ]}
    else:
        # Context-aware end-of-turn model + extra patience when the candidate signals they are thinking.
        start_plan = {"waitSeconds": 0.8,
                      "smartEndpointingPlan": {"provider": _env("SMART_ENDPOINTING_PROVIDER", "livekit")},
                      "customEndpointingRules": [
                          {"type": "customer", "regex": THINKING_REGEX,
                           "regexOptions": [{"type": "ignore-case", "enabled": True}], "timeoutSeconds": 5.0}]}

    transcriber = {
        "provider": "deepgram",
        "model": _env("STT_MODEL", "nova-3"),
        "language": _env("STT_LANGUAGE", "en-IN"),
        "smartFormat": True,
    }
    kt = [k for k in plan.get("keyterms", []) if k][:50]
    if kt and _env("STT_KEYTERMS", "1") == "1":
        transcriber["keyterm"] = kt

    return {
        "name": "TalentLoop Interviewer",
        "firstMessage": first_message,
        "firstMessageMode": "assistant-speaks-first",
        "firstMessageInterruptionsEnabled": False,
        "model": {
            "provider": "custom-llm",
            "url": f"{public}/llm/{iid}/{token}",
            "model": "talentloop-interview-brain",
            "messages": [{"role": "system", "content": "Interview is orchestrated by the custom LLM server."}],
            "temperature": 0.3,
            # Free LLMs can be slow; our server itself falls back after TURN_TIMEOUT_SEC.
            "timeoutSeconds": 25,
        },
        "voice": build_voice(),
        "transcriber": transcriber,
        "startSpeakingPlan": start_plan,
        "stopSpeakingPlan": {"numWords": 3, "voiceSeconds": 0.3, "backoffSeconds": 1},
        "backgroundSpeechDenoisingPlan": {"smartDenoisingPlan": {"enabled": True}},
        "endCallPhrases": [END_PHRASE],
        "maxDurationSeconds": int(plan["duration_min"]) * 60 + 300,
        # Silence handling (Vapi moved this from silenceTimeoutSeconds/messagePlan to hooks).
        # Gentle nudges first; hang up only after a long silence (e.g. the candidate walked away).
        "hooks": [
            {"name": "idle_nudge", "on": "customer.speech.timeout",
             "options": {"timeoutSeconds": float(_env("IDLE_TIMEOUT_SEC", "25")), "triggerMaxCount": 2,
                         "triggerResetMode": "onUserSpeech"},
             "do": [{"type": "say", "exact": list(IDLE_LINES)}]},
            {"name": "silence_end", "on": "customer.speech.timeout",
             "options": {"timeoutSeconds": float(_env("SILENCE_TIMEOUT_SEC", "120")), "triggerMaxCount": 1,
                         "triggerResetMode": "never"},
             "do": [{"type": "say", "exact": SILENCE_LINE},
                    {"type": "tool", "tool": {"type": "endCall"}}]},
        ],
        "artifactPlan": {"recordingEnabled": True,
                         # Vapi's own cloud video (camera + both voices), a server-side backup of our recording.
                         "videoRecordingEnabled": _env("VAPI_VIDEO_RECORDING", "1") == "1"},
        "server": {"url": f"{public}/webhook/vapi/{iid}/{token}"},
        "serverMessages": ["end-of-call-report"],
        "metadata": {"interview_id": iid},
    }


def build_voice() -> dict:
    """Default: Vapi's own 'Naina' voice on their Version 2 model (female, Indian accent, the most
    natural option in Vapi's current catalogue, included in Vapi's price). Override with
    VOICE_PROVIDER / VOICE_ID (e.g. azure + en-IN-NeerjaNeural, or an 11labs voice)."""
    provider = _env("VOICE_PROVIDER", "vapi")
    voice_id = _env("VOICE_ID", "Naina" if provider == "vapi" else "")
    v = {"provider": provider, "voiceId": voice_id}
    if provider == "vapi":
        v["version"] = _env("VOICE_VERSION", "2")   # the spec defines version as the string "1" | "2" | "latest"
        v["language"] = "en"                         # V2 auto-detects language otherwise; pin English
    speed = _env("VOICE_SPEED")
    if speed:
        v["speed"] = float(speed)
    return v
