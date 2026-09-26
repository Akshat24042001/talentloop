"""Builds the transient Vapi assistant for one interview call.

Vapi handles: browser audio (WebRTC), speech-to-text, text-to-speech, turn-taking, recording.
Our server handles: every word the interviewer says (Vapi calls us as a "custom-llm").
"""
import os

from .brain import END_PHRASE

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
        },
        "voice": {"provider": _env("VOICE_PROVIDER", "azure"), "voiceId": _env("VOICE_ID", "en-IN-NeerjaNeural")},
        "transcriber": transcriber,
        "startSpeakingPlan": start_plan,
        "stopSpeakingPlan": {"numWords": 3, "voiceSeconds": 0.3, "backoffSeconds": 1},
        "backgroundSpeechDenoisingPlan": {"smartDenoisingPlan": {"enabled": True}},
        "endCallPhrases": [END_PHRASE],
        "maxDurationSeconds": int(plan["duration_min"]) * 60 + 300,
        # Vapi's default hangs up after 30 s of silence. A candidate thinking about a hard question
        # would get disconnected. Nudge gently instead and only hang up after a long silence.
        "silenceTimeoutSeconds": int(_env("SILENCE_TIMEOUT_SEC", "120")),
        "messagePlan": {
            "idleMessages": ["Take your time. Let me know when you're ready to answer.",
                             "Are you still there? You can also say skip if you'd like to move on."],
            "idleTimeoutSeconds": float(_env("IDLE_TIMEOUT_SEC", "25")),
            "idleMessageMaxSpokenCount": 2,
        },
        "artifactPlan": {"recordingEnabled": True},
        "server": {"url": f"{public}/webhook/vapi/{iid}/{token}"},
        "serverMessages": ["end-of-call-report"],
        "metadata": {"interview_id": iid},
    }
