# Environment settings

Every setting the server reads. Set them in Render > the service > Environment. Never commit real values.

## Required for production

| Setting | What it does | Example |
|---|---|---|
| `DATABASE_URL` | Accounts, jobs, candidates. Supabase **Session pooler** URI (port 5432). | `postgresql://postgres.xxxx:PASSWORD@aws-0-ap-south-1.pooler.supabase.com:5432/postgres` |
| AI provider key(s) | At least one of `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `XAI_API_KEY` (Grok). The older `LLM_API_KEY` still works (`sk-or-...` = OpenRouter). Pick provider and models in Platform admin > AI models; providers without a key show there but are disabled. | |
| `VAPI_PUBLIC_KEY` | Browser voice interviews. | |
| `APP_URL` | The address people open; used in every emailed link. Without it links fall back to Render's own URL. | `https://talentloop-latest.onrender.com` |
| `PLATFORM_ADMIN_EMAILS` | Who gets the Platform admin console (comma-separated). | |
| `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Resumes, recordings, interview records, logos. Needed on Render's free plan (no disk): without it files are lost on every restart. | Supabase Storage S3 endpoint |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | **All emails**: invites, interview confirmations and reminders, calendar invites, sign-in codes for `/me`, referee requests, manager approvals. Without SMTP nothing is emailed; messages wait in Outbox. | Gmail: `smtp.gmail.com`, `587`, your address, an app password, `Hiring <you@company.com>` |
| `APP_ENV` | **Which environment this is.** `development` (default; also used for anything misspelled), `testing`, or `production`. See the table below. | `development` |
| `DEV_EMAIL_TO` | Outside production, the one inbox that receives every email. If empty, nothing is sent. | `you@gmail.com` |
### Development vs production

| | development / testing | production |
|---|---|---|
| Email | Only to `DEV_EMAIL_TO`, subject `[DEV for real@address]` | Real recipients |
| WhatsApp | Never sent | Sent |
| Sample candidates, dummy addresses (example.com, .test ...) | Never contacted | Never contacted |
| Sample data (Platform admin) | Available | Hidden and refused |
| Fake AI (`LLM_MOCK=1`) | Allowed | Ignored |
| API docs (`/docs`, `/openapi.json`) | On | Off (set `API_DOCS=1` to turn on) |
| "Development" badge on every page | Shown | Never |

Any new development-only feature should check `appenv.IS_PRODUCTION` (backend) or `useHealth().production` (frontend).

### Email with Resend

```
RESEND_API_KEY=<your Resend API key, re_...>
SMTP_FROM=TalentLoop <onboarding@resend.dev>
APP_ENV=development
DEV_EMAIL_TO=<the email your Resend account is registered with>
```

Mail goes over Resend's HTTPS API (port 443). Render's free instances block outbound SMTP ports 25, 465 and 587 (since
September 2025), so SMTP to smtp.resend.com can never connect there. Older setups with `SMTP_HOST=smtp.resend.com` and the
`re_` key in `SMTP_PASSWORD` are switched to the API automatically. Platform admin > Outbox > **Send a test email** sends
one email immediately and shows Resend's exact answer.

`onboarding@resend.dev` only delivers to the email address that owns the Resend account. To email anyone else (`APP_ENV=production`),
verify your own domain in Resend and change `SMTP_FROM` to an address on it. Messages held in development are not sent later
by switching to production; retry them one by one from Outbox if needed.

## Strongly recommended

| Setting | Why | Default |
|---|---|---|
| `FAST_MODEL` | Server default only: Platform admin > AI models overrides it. The model that runs live interview turns. Free models are slow and rate-limited; a paid fast model is the biggest reliability win for AI interviews. Comma-separated list = fallbacks in order. | free OpenRouter models |
| `SMART_MODEL` | Plans, scoring, reports. | free OpenRouter models |
| `VISION_MODEL` | Reads photo and scanned resumes; reviews live-task screenshots. Any OpenRouter model that accepts images (check "image" input on openrouter.ai/models). | off |
| `JWT_SECRET` | Signs API access tokens (JWT). Long random string (`openssl rand -hex 32`). If unset, a key derived from `URL_SECRET` / the stored key is used, which also works; changing it invalidates every access token (refresh tokens keep working). | derived |
| `JWT_ACCESS_MINUTES` | How long a JWT access token lasts before it must be refreshed. | `60` |
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

Development only (ignored when `APP_ENV=production`): `LLM_MOCK=1`, `ALLOW_SAMPLE_DATA=1`, `SKIP_EMAIL_VERIFICATION=1` (lets new accounts in without confirming their email; never set it on a server other people can reach). Test only: `WEB_DIR`.

## Keeping the free Render service awake

Ping `GET` or `HEAD https://<your app>/api/ping` every 5 minutes (cron-job.org, UptimeRobot, Better Stack, or a GitHub
Actions schedule). It answers without touching the database, so it costs nothing. `/healthz` is the same.
One service pinged around the clock uses about 744 of the 750 free instance hours a month, so do this for one free
service only. Pinging keeps it awake; it doesn't make the shared free CPU faster.

## Sign-up confirmation and API tokens

- New accounts must confirm their email with a 6-digit code before anything in the workspace opens. Invite links and
  password resets also count as confirmation (the email reached that inbox). Accounts that existed before this change
  were marked confirmed once. A platform admin can mark an account confirmed in Platform admin > Users.
- Signing up again with an address that was never confirmed replaces that unconfirmed account (and the company only it
  belonged to). So nobody can reserve someone else's email, including a `PLATFORM_ADMIN_EMAILS` address.
- The browser uses an HttpOnly cookie. API clients use JWT: `POST /api/auth/token` (email + password, or the OAuth2 form
  Swagger's **Authorize** button sends) returns `access_token` (JWT, `JWT_ACCESS_MINUTES`) and `refresh_token`
  (`SESSION_DAYS`). Send `Authorization: Bearer <access_token>`; renew with `POST /api/auth/token/refresh`. Each token is
  tied to a session, so sign-out, password change/reset and disabling the user revoke it immediately.

## Platform console (/admin)

Accounts in `PLATFORM_ADMIN_EMAILS` (or made platform admin in the console) get a separate console at `/admin`:
overview and analytics, every company (create with an owner invite, edit profile, disable, delete with typed confirmation, invite and manage members), every
person (roles, pause, confirm email, email a reset code, sign out everywhere, disable, admin rights, delete), candidates and jobs (view and edit; JD edits use the job schema), AI interviews (report, transcript, PDF), CSV reports of everything,
AI interviews, outbox (retry) and the audit log across all companies, plus platform settings (sign-ups open/closed, a
banner for every signed-in user, AI models, system status). Every change made there is written to the audit log as
"Platform admin" with the admin's email. Server keys are never shown or edited there: they stay in Render.
