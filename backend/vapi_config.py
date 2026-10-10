"""Builds the transient Vapi assistant for one interview call.

Vapi handles: browser audio (WebRTC), speech-to-text, text-to-speech, turn-taking, recording.
Our server handles: every word the interviewer says (Vapi calls us as a "custom-llm").
"""
import os

from .brain import END_PHRASE, IDLE_LINES, SILENCE_LINE

THINKING_REGEX = (r"(let me think|let me see|give me a (second|moment|minute)|one (second|moment|minute)|"
                  r"hmm+|umm+|uhh+|how do i put|what i mean is|so basically|actually)\s*[.,]?\s*$")


ACK_PHRASES = ["okay", "ok", "yeah", "yes", "yep", "right", "sure", "mm-hmm", "uh-huh", "hmm", "i see", "got it", "alright",
               "haan", "theek hai", "ji"]
INTERRUPT_PHRASES = ["wait", "sorry", "excuse me", "stop", "one second", "hold on", "can you repeat", "pardon"]


def _env(k, d=""):
    return (os.getenv(k) or d).strip()       # an empty value means "use the default"


def public_url() -> str:
    """PUBLIC_URL if set, else the URL the hosting platform gives us (Render, Railway)."""
    url = _env("PUBLIC_URL") or _env("RENDER_EXTERNAL_URL")
    if not url and _env("RAILWAY_PUBLIC_DOMAIN"):
        url = "https://" + _env("RAILWAY_PUBLIC_DOMAIN")
    return url.rstrip("/")


# Interview languages: the major languages of India (the 2011 census's largest scheduled languages that Vapi's speech providers support).
# Checked against the Vapi server SDK's own API types (@vapi-ai/server-sdk 3.0.0): Azure speech-to-text accepts bn-IN, gu-IN, hi-IN,
# kn-IN, ml-IN, mr-IN, pa-IN, ta-IN, te-IN and ur-IN; Odia ("or") and Assamese ("as") are not in Azure's list but are in Soniox's.
# Deepgram Nova-3 takes "hi" and "multi" (Hindi-English code-switching). Voices are Azure neural voices (Vapi takes any Azure voice name).
# Not available on any Vapi speech provider today, so not offered: Maithili, Konkani, Santali, Dogri, Manipuri, Bodo.
# Override any language with STT_<CODE>="provider:model:language" and VOICE_<CODE>="provider:voiceId" (code upper-cased, '-' as '_').
# Verify each language on a live call before using it with candidates.
LANGUAGES = [  # code, English name, name in its own script
    ("en", "English", "English"), ("hi", "Hindi", "हिन्दी"), ("hi-en", "Hinglish (Hindi + English)", "Hinglish"),
    ("bn", "Bengali", "বাংলা"), ("mr", "Marathi", "मराठी"), ("te", "Telugu", "తెలుగు"), ("ta", "Tamil", "தமிழ்"),
    ("gu", "Gujarati", "ગુજરાતી"), ("ur", "Urdu", "اردو"), ("kn", "Kannada", "ಕನ್ನಡ"), ("or", "Odia", "ଓଡ଼ିଆ"),
    ("ml", "Malayalam", "മലയാളം"), ("pa", "Punjabi", "ਪੰਜਾਬੀ"), ("as", "Assamese", "অসমীয়া"),
]
LANGUAGE_CODES = [c for c, _, _ in LANGUAGES]
LANG_STT = {"en": ("deepgram", "nova-3", None), "hi": ("deepgram", "nova-3", "hi"), "hi-en": ("deepgram", "nova-3", "multi"),
            "ta": ("azure", "", "ta-IN"), "te": ("azure", "", "te-IN"), "kn": ("azure", "", "kn-IN"), "mr": ("azure", "", "mr-IN"),
            "bn": ("azure", "", "bn-IN"), "gu": ("azure", "", "gu-IN"), "ml": ("azure", "", "ml-IN"), "pa": ("azure", "", "pa-IN"),
            "ur": ("azure", "", "ur-IN"), "or": ("soniox", "stt-rt-v4", "or"), "as": ("soniox", "stt-rt-v4", "as")}
LANG_VOICE = {"hi": ("azure", "hi-IN-SwaraNeural"), "ta": ("azure", "ta-IN-PallaviNeural"), "te": ("azure", "te-IN-ShrutiNeural"),
              "kn": ("azure", "kn-IN-SapnaNeural"), "mr": ("azure", "mr-IN-AarohiNeural"), "bn": ("azure", "bn-IN-TanishaaNeural"),
              "gu": ("azure", "gu-IN-DhwaniNeural"), "ml": ("azure", "ml-IN-SobhanaNeural"), "pa": ("azure", "pa-IN-VaaniNeural"),
              "ur": ("azure", "ur-IN-GulNeural"), "or": ("azure", "or-IN-SubhasiniNeural"), "as": ("azure", "as-IN-YashicaNeural")}


def _lang_env(prefix: str, lang: str) -> list[str] | None:
    v = _env(f"{prefix}_{lang.upper().replace('-', '_')}")
    return v.split(":") if v else None


def build_transcriber(plan: dict, language: str = "en") -> dict:
    over = _lang_env("STT", language)
    provider, model, code = (over + ["", "", ""])[:3] if over else LANG_STT.get(language, LANG_STT["en"])
    if provider == "deepgram":
        t = {"provider": "deepgram", "model": model or _env("STT_MODEL", "nova-3"), "language": code or _env("STT_LANGUAGE", "en-IN"), "smartFormat": True}
        kt = [k for k in plan.get("keyterms", []) if k][:50]
        if kt and _env("STT_KEYTERMS", "1") == "1" and t["language"] != "multi":
            t["keyterm"] = kt
        return t
    t = {"provider": provider, "language": code}
    if model:
        t["model"] = model
    return t


def build_assistant(iid: str, plan: dict, first_message: str, token: str, language: str = "en", phone: bool = False) -> dict:
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
        start_plan = {"waitSeconds": float(_env("START_WAIT_SEC", "0.6")),
                      "smartEndpointingPlan": {"provider": _env("SMART_ENDPOINTING_PROVIDER", "livekit")},
                      "customEndpointingRules": [
                          {"type": "customer", "regex": THINKING_REGEX,
                           "regexOptions": [{"type": "ignore-case", "enabled": True}], "timeoutSeconds": 5.0}]}

    transcriber = build_transcriber(plan, language)

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
        "voice": build_voice(language),
        "transcriber": transcriber,
        "startSpeakingPlan": start_plan,
        # Backchannels ("okay", "mm-hmm") never cut the interviewer off mid-question; "wait" or "sorry" always do.
        # Fields per Vapi's voice pipeline docs (stopSpeakingPlan.acknowledgementPhrases / interruptionPhrases).
        # Barge-in: one real word from the candidate (0.2 s of voice) stops the interviewer at once, as a person would. Backchannels
        # ("okay", "hmm") are excluded by acknowledgementPhrases, so listening noises don't cut a question off. Tune with BARGE_IN_WORDS.
        "stopSpeakingPlan": {"numWords": int(_env("BARGE_IN_WORDS", "1")), "voiceSeconds": float(_env("BARGE_IN_VOICE_SEC", "0.2")),
                             "backoffSeconds": float(_env("BARGE_IN_BACKOFF_SEC", "0.8")),
                             "acknowledgementPhrases": ACK_PHRASES, "interruptionPhrases": INTERRUPT_PHRASES},
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
                         "videoRecordingEnabled": _env("VAPI_VIDEO_RECORDING", "1") == "1" and not phone},
        "server": {"url": f"{public}/webhook/vapi/{iid}/{token}"},
        "serverMessages": ["end-of-call-report"],
        "metadata": {"interview_id": iid, "channel": "phone" if phone else "web", "language": language},
    }


def build_voice(language: str = "en") -> dict:
    """Default: Vapi's own 'Naina' voice on their Version 2 model (female, Indian accent, the most
    natural option in Vapi's current catalogue, included in Vapi's price). Override with
    VOICE_PROVIDER / VOICE_ID (e.g. azure + en-IN-NeerjaNeural, or an 11labs voice)."""
    over = _lang_env("VOICE", language) if language != "en" else None
    if over or language in LANG_VOICE:
        provider, voice_id = (over[0], ":".join(over[1:])) if over else LANG_VOICE[language]
        return {"provider": provider, "voiceId": voice_id}
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
