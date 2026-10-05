# Environment settings

Every setting the server reads. Set them in Render > the service > Environment. Never commit real values.

## Required for production

| Setting | What it does | Example |
|---|---|---|
| `DATABASE_URL` | Accounts, jobs, candidates. Supabase **Session pooler** URI (port 5432). | `postgresql://postgres.xxxx:PASSWORD@aws-0-ap-south-1.pooler.supabase.com:5432/postgres` |
| `LLM_API_KEY` | AI (OpenRouter `sk-or-...` or OpenAI). | |
| `VAPI_PUBLIC_KEY` | Browser voice interviews. | |
| `APP_URL` | The address people open; used in every emailed link. Without it links fall back to Render's own URL. | `https://talentloop-latest.onrender.com` |
| `PLATFORM_ADMIN_EMAILS` | Who gets the Platform admin console (comma-separated). | |
| `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Resumes, recordings, interview records, logos. Needed on Render's free plan (no disk): without it files are lost on every restart. | Supabase Storage S3 endpoint |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | **All emails**: invites, interview confirmations and reminders, calendar invites, sign-in codes for `/me`, referee requests, manager approvals. Without SMTP nothing is emailed; messages wait in Outbox. | Gmail: `smtp.gmail.com`, `587`, your address, an app password, `Hiring <you@company.com>` |

## Strongly recommended

| Setting | Why | Default |
|---|---|---|
| `FAST_MODEL` | The model that runs live interview turns. Free models are slow and rate-limited; a paid fast model is the biggest reliability win for AI interviews. Comma-separated list = fallbacks in order. | free OpenRouter models |
| `SMART_MODEL` | Plans, scoring, reports. | free OpenRouter models |
| `VISION_MODEL` | Reads photo and scanned resumes; reviews live-task screenshots. Any OpenRouter model that accepts images (check "image" input on openrouter.ai/models). | off |
| `URL_SECRET` | Long random string that signs links (`openssl rand -hex 32`). If unset, one is generated and kept in the database, which also works. | stored in DB |
| `AI_SLOT_CAPACITY` | How many booked AI interviews may overlap; set to your Vapi plan's concurrent-call limit. | `10` |

## Optional services

| Setting | Turns on |
|---|---|
| `VAPI_PRIVATE_KEY`, `VAPI_PHONE_NUMBER_ID` | AI interviews by phone call ("Call my phone instead"). |
| `DEEPGRAM_API_KEY` | Server transcription of video introductions and role tasks (otherwise the browser transcript is used). |
| `PEOPLE_DATA_API_KEY` | Resume check: compare current company, past employers and schools with public records (People Data Labs). |
| `GITHUB_TOKEN` | Resume check: GitHub lookups above 60 per hour. |
| `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_TEMPLATE`, `WHATSAPP_TEMPLATE_LANG`, `WHATSAPP_API_VERSION` | WhatsApp messages to candidates. |
| `IMAP_HOST`, `IMAP_USER`, `IMAP_PASSWORD`, `IMAP_ORG_SLUG`, `IMAP_PORT`, `IMAP_FOLDER` | Import resumes emailed to a mailbox. |
| `ADMIN_KEY` | API access for scripts (header `X-Admin-Key`). |

## Tuning (leave unset unless you need to)

`PUBLIC_URL` (Render fills it), `COOKIE_SECURE` (`auto`), `SESSION_DAYS` (14), `RETENTION_DAYS` (0 = keep), `REPORT_TZ`
(Asia/Kolkata, exports only; emails use the company's time zone in Settings), `SLOW_REQUEST_MS` (1500), `LOG_LEVEL`,
`TURN_TIMEOUT_SEC` (8), `MAX_RECONNECTS` (5), `RECONNECT_WINDOW_SEC` (90), `PLAN_MODEL`, `PLAN_DEADLINE_SEC`,
`SCORING_PASSES`, `LLM_BASE_URL`, `LLM_JSON_MODE`, `STT_MODEL`, `STT_LANGUAGE`, `MEDIA_CAP_MB`, `S3_PREFIX`,
`S3_PATH_STYLE`, `PERSISTENT_DISK`, `DATA_DIR` (`/data`), `SWEEP_EVERY_SEC`, `MESSAGES_EVERY_SEC`,
`RETENTION_EVERY_SEC`, `FINISH_DELAY_SEC`.

Test only, never in production: `LLM_MOCK=1`, `ALLOW_SAMPLE_DATA=1`, `WEB_DIR`.

## Keeping the free Render service awake

Ping `GET` or `HEAD https://<your app>/api/ping` every 5 minutes (cron-job.org, UptimeRobot, Better Stack, or a GitHub
Actions schedule). It answers without touching the database, so it costs nothing. `/healthz` is the same.
One service pinged around the clock uses about 744 of the 750 free instance hours a month, so do this for one free
service only. Pinging keeps it awake; it doesn't make the shared free CPU faster.
