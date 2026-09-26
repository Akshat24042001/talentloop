# TalentLoop AI Interview PoC

An AI voice interviewer for first-round screening. HR gives it a JD, a resume and their questions. It builds an interview plan for HR to approve. It interviews the candidate in the browser with voice and camera, asks smart follow-ups, keeps time, and produces a scorecard where every score is backed by a quote from the candidate.

## Platform verdict

**Chosen: Vapi (web SDK) for voice, with this server plugged in as Vapi's "custom LLM".**

Vapi handles the hard real-time parts: browser audio, speech-to-text, text-to-speech, turn-taking and recording. Every word the interviewer says comes from `backend/brain.py`, so the interview logic stays yours and is portable.

| Option | Verdict | Why |
|---|---|---|
| **Vapi** | **Use now** | Custom LLM endpoint means your code controls the interview turn by turn. Endpointing rules let the AI wait longer when a candidate says "let me think". Deepgram Nova-3 with `en-IN` and keyterm boosting for tech terms. Mature web SDK. About $0.05/min platform fee plus providers. |
| OmniDimension | Not for this | You know it and it's Indian, with Sarvam STT. But its API only accepts a fixed list of models (no custom LLM), so control is prompt-only and you can't enforce question coverage or time. Its browser SDK is new (July 2026). Keep it for phone pre-screen calls, where it's strong. |
| Retell | Viable, no edge | Similar price and capability. Nothing it does beats Vapi for this job. |
| ElevenLabs Agents | Viable, no edge | Best voices, around $0.08/min plus LLM. Minute bundles push you onto a subscription. Voice quality isn't the bottleneck here. |
| LiveKit Agents (self-hosted) | Later | Most control, and data can stay closer to home. Too much infrastructure for a weekend. The brain in this repo moves over unchanged when volume or data residency demands it. |
| Speech-to-speech (OpenAI Realtime etc.) | No | Natural-sounding, but you lose turn-by-turn control of the question plan. |

## How it works

```
HR page ──> /api/plan (SMART_MODEL) ──> HR reviews/edits plan ──> candidate link
                                                                     │
Candidate browser (interview.html) ── Vapi web SDK ── Vapi cloud (STT, TTS, turn-taking)
                                                         │  every candidate turn
                                                         ▼
                                  POST /llm/{id}/{session_token}/chat/completions
                                  brain.handle_turn():
                                    code decides allowed actions (time, follow-up budget)
                                    FAST_MODEL judges answer, picks one action, writes words
                                    code composes reply (plan questions asked as written)
                                                         │
Call ends ──> /complete ──> score_interview (SMART_MODEL) ──> quotes verified against
                                                              transcript ──> report.html
```

The interviewer's possible actions each turn are: follow up, next question, repeat or rephrase, invite them to continue (answer looked cut off), answer the candidate's question (only from JD facts; salary goes to HR), redirect (off-topic or manipulation), and end.

## Setup (about 20 minutes)

1. `cd talentloop-ai-interview && python -m venv .venv && source .venv/bin/activate` (Windows: `.venv\Scripts\activate`)
2. `pip install -r backend/requirements.txt`
3. Start a tunnel: `cloudflared tunnel --url http://localhost:8000`, then copy the `https://....trycloudflare.com` URL.
4. `cp .env.example .env` and fill in `PUBLIC_URL`, `VAPI_PUBLIC_KEY`, `LLM_API_KEY` and `ADMIN_KEY`.
5. `uvicorn backend.main:app --host 0.0.0.0 --port 8000` (one worker only: interview locks live in process memory)
6. Open `http://localhost:8000` (the HR page). The top line must show no red warnings.

Quick checks before spending money:
- `LLM_MOCK=1 python -m tests.test_flow` tests the whole flow with a fake AI. It should print `ALL CHECKS PASSED`.
- `python -m tools.rehearse` runs a real-LLM interview where you **type** answers. It costs no Vapi minutes. Use it to tune `backend/prompts.py`.

Note: cloudflared quick-tunnel URLs change every restart. Update `PUBLIC_URL` and restart the server each time, or set up a named tunnel.

## Weekend plan

**Saturday night (setup and first call)**
- Get the tests passing, then do a text rehearsal with the sample data. Read every AI line. Is it natural? Are the follow-ups sharp?
- Do one real voice call yourself: HR page → sample data → generate → create link → open the link in Chrome.
- If Vapi rejects the call config, open browser devtools. The error names the field. The likeliest culprit is the voice: set `VOICE_PROVIDER`/`VOICE_ID` to any voice from your Vapi dashboard.

**Sunday (real people)**
- Load one real RAC JD, real resumes and their question set.
- Run 8 to 10 interviews with real people: Cosmos students, friends, anyone with Gujarati- or Hindi-accented English. Mix quiet and noisy rooms, laptop and phone.
- After each call, fill the log below. Then score each answer yourself on the report page. This builds the calibration number.

**What to measure (the PoC passes only if these hold)**

| Metric | Where to see it | Pass |
|---|---|---|
| Candidate cut off mid-answer | Transcript: `invite_continue` actions, candidates complaining | ≤ 1 per interview |
| Key terms misheard (tools, names) | Transcript vs what they said | Rare, and never changes meaning |
| All planned questions asked | Report: questions asked x/y | 100% when on time |
| Follow-ups relevant, not repetitive | Read the transcript | Your judgment, honestly |
| Turn latency | Report: avg live turn latency (LLM only) | < 1500 ms |
| AI vs your score | HR page: calibration line | ≥ 80% within ±1 |
| Evidence verified | Report: x/y verified | ≥ 90% |

If candidates keep getting cut off, set `ENDPOINTING_MODE=patient` in `.env` and restart.

## Showing it to people (demo script)

1. On the HR page, paste their JD, resume and questions → **Generate**. Show the plan: "HR approves exactly what gets asked."
2. **Create the link** and have someone take the interview live on their own laptop.
3. Deliberately test it in front of them. Give a vague answer (watch the follow-up), say "can you repeat that", and ask "what's the salary?".
4. Open the report: recommendation, per-question scores, evidence quotes with timestamps, resume claims checked, flags.
5. Close with: "The AI never rejects anyone. HR decides. We measure how often it agrees with your team."

## Tuning knobs (.env)

- `FAST_MODEL`: the live turn model. Speed matters more than brilliance. `gpt-4.1-mini` is the default.
- `SMART_MODEL`: plan and scoring. Quality matters. `gpt-4.1` is the default.
- `ENDPOINTING_MODE` / `PATIENT_TIMEOUT_SEC`: how long the AI waits before speaking.
- `STT_LANGUAGE`: `en-IN` default. Try `multi` if candidates code-switch into Hindi.
- `SCORING_PASSES=2`: scores twice and flags unstable scores. Costs twice as much.

## Honest limitations of this PoC

- **Data leaves India.** Audio goes through Vapi, Deepgram, the TTS provider and the LLM provider. The consent screen says so. Fully on-prem is not possible at this quality today; say that to RAC upfront.
- **Cheating is detectable, not preventable.** You get tab switches, fullscreen exits and video. Resume-probe follow-ups are the real defence. There is no face detection yet.
- **English only.** Hindi and Gujarati interviews need different STT and TTS choices and fresh testing.
- **Storage is JSON files** on one machine, and there is no HR login beyond `ADMIN_KEY`. That's fine for a pilot, not for production.
- **Recordings on Vapi are temporary.** This server copies the call audio when the end-of-call webhook arrives. The candidate's camera video is uploaded from the browser at the end.
- **Latency.** Each turn waits for the silence window plus about 1 second of LLM time. That's acceptable for an interview, but measure it.

## Review status

Read `REVIEW.md` before running real candidates. Hosting: see `DEPLOY.md`. It lists what was fixed, what is still open, and what must be verified on a live Vapi call.

## Files

- `backend/brain.py`: the interview state machine, scoring and quote verification. The core.
- `backend/prompts.py`: all prompts. Tune here first.
- `backend/vapi_config.py`: voice, STT, turn-taking and end-call settings.
- `backend/main.py`: API, custom LLM endpoint and webhook.
- `web/hr.html`, `web/interview.html`, `web/report.html`: the three screens.
- `tools/rehearse.py`: typed rehearsal. `tests/test_flow.py`: end-to-end test.
