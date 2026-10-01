# TalentLoop

A hiring platform for small teams: detailed job descriptions, a careers page, a candidate pool, instant matching of
every resume against every job, AI match reports for each job's shortlist, and an AI voice interviewer for the first round.

## The hiring platform

- **Companies, sign-in and roles.** Anyone can sign up; that creates a company workspace with them as owner. Others join
  by invite link with a role: **Owner**, **Admin** (team and settings), **Recruiter** (HR: creates and publishes jobs,
  manages candidates), **Hiring manager** (sees only the jobs HR assigns), **Viewer** (read-only). Several people can
  share a role. People can belong to several companies and switch between them.
- **Per-job access.** HR creates a job and gives, say, the sales manager **editor** rights (writes and updates the JD,
  moves candidates; can't publish or delete) or **reviewer** rights (rates and comments). Every edit is in the job's activity log.
- **Job descriptions.** About 60 fields in 8 sections (basics, location and work model, pay and benefits, the role,
  requirements, hiring process and screening questions, posting, matching). Only 7 are required to publish. "Write with
  AI" drafts the summary and responsibilities; "Import JD file" prefills from an existing PDF or DOCX for free. One click
  gives a clean JD PDF and a public job post.
- **Candidates.** Bulk resume upload (PDF, DOCX, TXT, up to 500 at a time) with free parsing of name, email, phone,
  city, skills (about 300 skills with synonyms), years of experience and notice period, de-duplicated by email.
  Careers page applications with screening questions (a wrong answer to a must-answer question screens the person out,
  but keeps them on file), a talent pool, and a resume builder for candidates without one (turned into a PDF).
- **Matching built for low AI cost.** Stage 1 is free and instant: every candidate is scored against every open job on
  skills (must-haves and nice-to-haves), experience band, BM25 keyword relevance, location (with city aliases) and
  notice period and salary, with company-set weights and per-job screen-out rules. 2,000 resumes x 120 jobs rank in about
  5 seconds. Stage 2 writes an AI match report (verdict, strengths, gaps, risks, interview questions) **only for each job's
  top N** (3 to 50, default 5), cached by a hash of the job and the resume, and capped per run. The reverse view shows the
  best jobs for any candidate.
- **AI interviews** can be sent straight from a match; the JD, resume and the job's must-ask questions are filled in.
- **Platform admin** (emails in `PLATFORM_ADMIN_EMAILS`): every company with its users, jobs, resumes, applications,
  interviews, AI calls and last activity, every user with sign-in counts, and disable switches.
- **Sample data**: one click loads 6 jobs and 40 synthetic resumes; one click removes them.

Data lives in Postgres (Supabase) via `DATABASE_URL`, or SQLite on a laptop. Files (resumes, recordings) go to any
S3-compatible bucket (Supabase Storage, Backblaze B2). See `DEPLOY.md`.

## The AI interviewer

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
New interview ──> /api/plan (SMART_MODEL) ──> HR reviews/edits plan ──> candidate link
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
                                                              transcript ──> HR report
```

The interviewer's possible actions each turn are: follow up, next question, repeat or rephrase, invite them to continue (answer looked cut off), answer the candidate's question (only from JD facts; salary goes to HR), redirect (off-topic or manipulation), and end.

## Setup (about 20 minutes)

1. `cd talentloop-ai-interview && python -m venv .venv && source .venv/bin/activate` (Windows: `.venv\Scripts\activate`)
2. `pip install -r backend/requirements.txt`, then build the web interface once (needs Node 20+): `cd frontend && npm ci && npm run build && cd ..`. Rebuild after pulling changes to `frontend/`. (Docker and Render do this automatically.)
3. Start a tunnel: `cloudflared tunnel --url http://localhost:8000`, then copy the `https://....trycloudflare.com` URL.
4. `cp deploy/backend.env.example .env` and fill in `PUBLIC_URL`, `VAPI_PUBLIC_KEY`, `LLM_API_KEY` and `PLATFORM_ADMIN_EMAILS` (your email). Leave `DATABASE_URL` and `S3_*` empty to use local files. Hosting: see `DEPLOY.md`.
5. `uvicorn backend.main:app --host 0.0.0.0 --port 8000` (one worker only: interview locks live in process memory)
6. Open `http://localhost:8000`, click **Start free** and sign up. Load the sample data from the dashboard. No yellow warnings should show at the top (on a laptop, temporary storage warnings are expected).

Quick checks before spending money:
- `LLM_MOCK=1 python -m tests.test_flow` tests the whole interview flow with a fake AI. It should print `ALL CHECKS PASSED`.
- `python -m tests.test_platform` tests accounts, roles, jobs, candidates, applying, matching and a 2,000 x 120 scale run.
- `python -m tests.e2e_platform` and `python -m tests.e2e_browser` drive the real app in Chromium.
- `python -m tools.rehearse` runs a real-LLM interview where you **type** answers. It costs no Vapi minutes. Use it to tune `backend/prompts.py`.

Note: cloudflared quick-tunnel URLs change every restart. Update `PUBLIC_URL` and restart the server each time, or set up a named tunnel.

## Weekend plan

**Saturday night (setup and first call)**
- Get the tests passing, then do a text rehearsal with the sample data. Read every AI line. Is it natural? Are the follow-ups sharp?
- Do one real voice call yourself: New interview → pick a sample role → generate → create link → open the link in Chrome.
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
| AI vs your score | Dashboard: agreement line | ≥ 80% within ±1 |
| Evidence verified | Report: x/y verified | ≥ 90% |

If candidates keep getting cut off, set `ENDPOINTING_MODE=patient` in `.env` and restart.

## Showing it to people (demo script)

1. On the New interview page, paste their JD, resume and questions (or pick one of the 7 sample roles) → **Generate**. Show the plan: "HR approves exactly what gets asked."
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

## What HR gets

**Recordings**
- Candidate camera video **with both voices** (the candidate's mic and the AI interviewer mixed in the browser), uploaded in 5-second pieces during the call and repaired with ffmpeg afterwards, so it plays, shows its length and can be scrubbed.
- Candidate screen recording when screen sharing is on.
- Vapi's call audio, plus Vapi's cloud video as a backup when `VAPI_PRIVATE_KEY` is set.
- Click any transcript line, evidence quote or flagged event on the report to jump the video to that moment.

**Integrity (proctoring) report, available immediately, even if AI scoring fails**
- Risk level (low/medium/high) with plain-English reasons, and a timeline of every event linked to the question being asked.
- **Leaving the interview is confronted, not just logged.** When the candidate switches tab, window or app (or plugs in a second monitor), the AI interviewer says a warning out loud and the page shows it. After the HR-set number of warnings (default 2), the interviewer ends the interview and it is marked **Disqualified**. The count lives on the server, so reloading doesn't reset it, and a disqualified link can't be rejoined. The next link for the same email warns HR.
- **Screenshot of the screen at the moment of switching** (when screen sharing is on), paired with a camera photo, shown as "Flagged moments" on the report.
- **One screen only** (optional per interview): a second monitor blocks the start (`screen.isExtended`, Chrome/Edge) and counts as leaving if connected mid-interview.
- Tab switches and time away, other windows focused, full-screen exits, copy/paste/cut, right-click, shortcuts, Print Screen, suspected developer tools, a shrunk window.
- Face checks in the browser (MediaPipe, self-hosted): no face, more than one person. A snapshot is taken each time, plus a reference photo at the start and one every minute.
- Microphone muted (count and duration), voice detected while muted, camera or mic switched off, lost connection.
- Required entire-screen sharing (optional per interview): refuses windows and tabs, and records and blocks with an overlay when sharing stops.
- Every session's IP address and browser; a rejoin from a different device or network is flagged.

**Interview flow**
- Rejoin window after a drop (default 30 s, set per interview). After it, the server refuses to reopen the interview, closes it and scores what was done. A deliberate "End interview" can't be undone.
- Links can be scheduled (open-from time) and expire.
- A video-call interface: AI interviewer tile with a voice visualiser, the candidate's camera, their shared screen live, the **current question on screen** (follow-ups show which question they belong to), live captions, and icon controls (mic, camera locked on, screen share, captions, hang up). Works on phones when screen sharing isn't required.
- The candidate is **never told the length or the number of questions**, before or during the interview.
- Camera, microphone and screen sharing all stop when the interview ends.
- Natural voice: Vapi "Naina" (Indian English, Vapi's Version 2 model), plus a warmer interviewer script and conversational acknowledgements.
- Silence handling: gentle check-ins, then a polite hang-up after 2 minutes of silence.
- Optional questions are skipped automatically when time is short, so HR's mandatory questions are always asked.

**Reports and data**
- Download a **PDF report** (summary, integrity, snapshots, per-question scores with verified quotes, resume claims, sessions and consent, full transcript), the transcript (TXT), all data (JSON), or **everything in one ZIP** (PDF + transcript + data + all videos and snapshots). There's also a CSV export of all interviews.
- Charts: score by question (AI vs your score), competencies, time per question, and an integrity timeline with the interviewer's warnings. Questions are named by their text, never by an id like "q3".
- Per-question time, words and follow-ups, the candidate's share of talk time, and AI fallback count.
- HR scores per question, decision and notes, and calibration (AI vs HR agreement).
- Consent record (time, IP, browser), candidate feedback rating, a delete-everything button and an optional retention period (`RETENTION_DAYS`).
- Storage survives Render free-tier restarts via any S3-compatible bucket (Backblaze B2 free).

## Honest limitations

- **Data leaves India.** Audio goes through Vapi, Deepgram, the TTS provider and the LLM provider. The consent screen says so.
- **Cheating is detectable, not preventable.** A second phone out of camera view or a helper speaking quietly can't be fully caught by any browser. Voice-while-muted, face checks and resume-probe follow-ups are the practical defence. HR must watch flagged moments before concluding anything.
- **Browser limits.** Screen-share and multi-monitor checks need desktop Chrome or Edge. Safari/Firefox can take the interview, but some signals are missing.
- **English only.** Hindi and Gujarati interviews need different STT choices and testing (the PDF already renders Hindi/Gujarati names).
- **One server process.** Interview locks and rate limits live in memory, so run one instance. Interviews are JSON files mirrored to S3 (fine for a pilot); the hiring data is in the database.
- **Password reset is manual.** There's no email sending yet: an owner re-invites a person who forgot their password.
- **The Vapi config passes through the candidate's browser.** See `REVIEW.md` for the private-key hardening.

## Review status

Read `REVIEW.md` before running real candidates. Hosting: see `DEPLOY.md`. It lists what was fixed, what is still open, and what must be verified on a live Vapi call.

## Files

- `backend/brain.py`: the interview state machine, scoring and quote verification. The core.
- `backend/prompts.py`: all prompts. Tune here first.
- `backend/vapi_config.py`: voice, STT, turn-taking and end-call settings.
- `backend/main.py`: interview API, custom LLM endpoint, webhook, and serving the web app.
- `backend/db.py` (tables), `auth.py` (passwords, sessions, roles, per-job access), `api_accounts.py` (sign-up, team, settings, platform admin), `api_hiring.py` (jobs, candidates, applications, matching, dashboard, careers), `jd_schema.py` (every JD field), `matching.py` (two-stage matching), `resumes.py` and `skills.py` (free parsing), `docs_pdf.py` (JD and resume PDFs), `demo.py` (sample data).
- `frontend/`: the web interface (React + TypeScript + Tailwind, built with Vite into `frontend/dist`, which the server serves). Two pages: `index.html` is the whole app with its own routes (`/` landing, `/login`, `/signup`, `/invite/…`, `/app/…` workspace, `/admin`, `/careers/<company>`), and `/interview.html?id=` is the candidate call. Old `/dashboard.html`, `/hr.html` and `/report.html?id=` links redirect.
  - `frontend/src/app/`: workspace pages. `frontend/src/site/`: landing, sign-in, careers. `frontend/src/admin/`: platform admin.
  - `frontend/src/interview/engine.ts`: the candidate-side engine (devices, Vapi call, recording and upload, face checks, warnings, rejoin). `InterviewApp.tsx` is its UI.
  - `frontend/src/components/`: UI kit and charts. `frontend/src/lib/`: API client, router, session.
  - Local UI development: run the server on port 8000, then `cd frontend && npm run dev` (Vite proxies `/api` to it).
- `frontend/public/samples/`: sample JD, resume and HR questions for 7 roles (`index.json` lists them). `frontend/public/vendor/`: self-hosted Vapi SDK and face-detection model.
- `tools/rehearse.py`: typed rehearsal. `tests/test_flow.py`: end-to-end API test. `tests/e2e_browser.py`: real-Chromium test (warnings, disqualification, second screen, recordings).
