# Hosting TalentLoop

TalentLoop has two parts:

- **Backend**: the FastAPI server (`backend/`). Accounts, jobs, candidates, matching, AI, interviews. Runs on Render.
- **Frontend**: the React website (`frontend/`). It has no secrets and needs no environment variables.

Pick one way to host them:

| | Option A: one Render service (recommended) | Option B: frontend on Vercel, backend on Render |
|---|---|---|
| Setup | One service, one address | Two services; Vercel forwards `/api` to Render |
| Speed | Pages load from Render (free plan sleeps after 15 min idle, first load about 30 s) | Pages load instantly from Vercel's CDN; data calls still wake Render |
| Env vars | Backend only | Backend, plus `BACKEND_URL` on Vercel |
| Uploads | No extra limits | Requests pass through Vercel; resume uploads are sent in batches of at most 4 MB to stay small. I couldn't confirm Vercel's body-size limit for forwarded requests, so a single resume over about 4 MB may fail on Vercel. Test a large file once |

Complete env files: `deploy/backend.env.example` (every backend setting, explained) and `deploy/frontend.env.example`.

---

## Step 1. Accounts you need (both options)

**OpenRouter (the AI)**
1. Sign up at https://openrouter.ai, then **Keys > Create key**. It starts with `sk-or-`. This is `LLM_API_KEY`.
2. **Settings > Privacy**: allow free model endpoints that may train on or log prompts. Without it free models fail with
   "No endpoints found matching your data policy".
3. Recommended: add $10 credit once. Free models stay free, but the daily cap goes from 50 to 1,000 requests.
   For real candidates, use paid models: `FAST_MODEL=openai/gpt-4.1-mini`, `SMART_MODEL=openai/gpt-4.1`.

**Vapi (the interview voice)**
Dashboard > **API Keys** > copy the **Public** key: `VAPI_PUBLIC_KEY`. Optionally copy the **Private** key:
`VAPI_PRIVATE_KEY` (lets the server fetch Vapi's cloud video backup). Vapi bills per minute after the trial credit.

**Supabase (database and file storage)**
1. https://supabase.com > **New project**. Region: closest to your users (e.g. Mumbai). Save the database password.
   **Put the Render service in the same region, or the nearest one Render offers.** Every page load makes several
   database calls, and each crosses the distance between the two: a mismatch such as Render Oregon with Supabase
   Mumbai adds roughly a quarter of a second per call and makes lists feel slow. Check Render's region list when you
   create the service; if it has no Mumbai region, Singapore is the nearest for Supabase Mumbai.
2. Database: top bar **Connect** > **Session pooler** > copy the URI and put your password in it:
   `postgresql://postgres.<project-ref>:<password>@aws-0-ap-south-1.pooler.supabase.com:5432/postgres` = `DATABASE_URL`.
   Use the Session pooler: Render can't reach the direct connection (IPv6 only). Tables are created automatically.
3. Storage: **Storage > New bucket**, name `talentloop`, **Private**.
4. **Storage > Settings > S3 Connection**: copy **Endpoint** (`S3_ENDPOINT_URL`) and **Region** (`S3_REGION`).
   Click **New access key**, copy **Access key ID** (`S3_ACCESS_KEY_ID`) and **Secret access key** (`S3_SECRET_ACCESS_KEY`).
   Set `S3_BUCKET=talentloop`.

Supabase free limits: 500 MB database (about 100,000 candidates), 1 GB of files, 50 MB per file. Resumes are small
(1,000 is about 200 MB), but one recorded 15-minute interview is 30 to 60 MB, so 1 GB holds about 15 to 30 interviews.
For more, upgrade Supabase or point the `S3_*` settings at Backblaze B2 (10 GB free): endpoint
`https://s3.<region>.backblazeb2.com`, keyID and applicationKey as the access keys.

**Optional services (add any time; each feature switches on when its settings are present)**

| Feature | Where to get it | Settings |
|---|---|---|
| Emails to candidates, managers and interviewers (invites, reminders, calendar invites, closures) | Any SMTP provider: Google Workspace or Gmail with an app password (smtp.gmail.com, 587), Zoho, Amazon SES, Brevo | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` |
| WhatsApp messages | Meta WhatsApp Cloud API: a phone number ID, a permanent token, and an **approved template** whose body is one variable, `{{1}}` | `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_TEMPLATE`, `WHATSAPP_TEMPLATE_LANG`, `WHATSAPP_API_VERSION` |
| Server transcription of video introductions, role tasks and interviewer recordings | https://deepgram.com > API key | `DEEPGRAM_API_KEY` |
| "Call me": the AI interviewer phones the candidate | Vapi > Phone Numbers > import or buy a number, copy its ID | `VAPI_PRIVATE_KEY`, `VAPI_PHONE_NUMBER_ID` |
| Resumes emailed to a careers mailbox become candidates | Any IMAP mailbox (Gmail needs IMAP on and an app password); use one dedicated to applications | `IMAP_HOST`, `IMAP_USER`, `IMAP_PASSWORD`, `IMAP_ORG_SLUG`, optional `IMAP_PORT`, `IMAP_FOLDER`, `IMAP_EVERY_SEC` |

Without SMTP or WhatsApp nothing is lost: messages wait in **Outbox** (and HR can copy every candidate link from
the pipeline), and can be retried once a channel is set up. Other interview languages need no account: pick the
language on the AI interview round; `STT_<LANG>` / `VOICE_<LANG>` override the defaults (see the env file).

---

## Option A: everything on one Render service (recommended)

1. https://dashboard.render.com > **New +** > **Web Service** > connect GitHub > pick `Akshat24042001/talentloop`.
2. Settings: Branch `main`, Language/Runtime **Docker**, **Region: the same as your Supabase project** (see Step 1),
   Instance type **Free** (or Starter for no sleeping). An existing service can't change region: create a new one in
   the right region, copy the environment, then delete the old one.
3. **Environment** > add these (values from Step 1):

   | Key | Value |
   |---|---|
   | `DATABASE_URL` | Supabase Session pooler URI |
   | `PLATFORM_ADMIN_EMAILS` | your email |
   | `S3_BUCKET` | `talentloop` |
   | `S3_ENDPOINT_URL` | `https://<project-ref>.supabase.co/storage/v1/s3` |
   | `S3_REGION` | e.g. `ap-south-1` |
   | `S3_ACCESS_KEY_ID` | Supabase S3 access key ID |
   | `S3_SECRET_ACCESS_KEY` | Supabase S3 secret |
   | `LLM_API_KEY` | OpenRouter key |
   | `LLM_MOCK` | `0` |
   | `VAPI_PUBLIC_KEY` | Vapi public key |
   | `VAPI_PRIVATE_KEY` | optional |
   | `FAST_MODEL`, `SMART_MODEL` | optional: paid models for real candidates |
   | `SMTP_*`, `WHATSAPP_*`, `DEEPGRAM_API_KEY`, `VAPI_PHONE_NUMBER_ID`, `IMAP_*` | optional: see "Optional services" above |

   Don't set `PUBLIC_URL`, `APP_URL`, `DATA_DIR`, `PORT` or `COOKIE_SECURE`: they're automatic. `ADMIN_KEY` is no longer
   needed (people sign in); delete it unless a script uses the API.
4. **Advanced > Health Check Path**: `/api/health`. Click **Create Web Service**. The first build takes about 5 minutes
   (it builds the website with Node, then the Python server). Every push to `main` redeploys.
5. Custom domain (optional): Render > Settings > **Custom Domains** > add e.g. `app.talentloop.in` and create the CNAME
   it shows at your domain registrar. Nothing else changes.

Or **New + > Blueprint** with this repo: `render.yaml` creates the service and asks for the same values.

---

## Option B: frontend on Vercel, backend on Render

**B1. Backend on Render.** Do Option A steps 1 to 4 exactly (it still serves the website too; candidate links keep
working either way). Note the service address, e.g. `https://talentloop-ai-interview.onrender.com`.

**B2. Frontend on Vercel.**
1. https://vercel.com > **Add New > Project** > import `Akshat24042001/talentloop`.
2. **Root Directory**: `frontend`. Framework preset: **Vite** (or Other). Build command, output (`dist`) and install
   command are read from `vercel.json`; don't change them.
3. **Environment Variables**: add `BACKEND_URL` = your Render address (e.g. `https://talentloop-ai-interview.onrender.com`)
   for Production, Preview and Development.
4. **Deploy**. You get an address like `https://talentloop.vercel.app` (add your own domain under **Settings > Domains**).
   If you add or change `BACKEND_URL` later, redeploy (Deployments > ... > Redeploy).

**B3. Tell the backend the website address.** Render > Environment > add `APP_URL` = your Vercel address
(e.g. `https://talentloop.vercel.app`, no trailing slash). Save; Render redeploys. Candidate interview links now use it.

How it works: the browser only talks to the Vercel address. A small Vercel middleware (`frontend/middleware.ts`) forwards
`/api/...` and `/media/...` to `BACKEND_URL`, so
sign-in cookies belong to the Vercel address and no CORS setup is needed. Vapi talks to Render directly during
interviews (Render's own address, detected automatically).

---

## Step 2. Check it (both options)

1. Open your address: you see the landing page. **Start free** > sign up **with the email in `PLATFORM_ADMIN_EMAILS`**.
2. The dashboard shows a yellow banner for anything missing (temporary database, temporary file storage, missing keys).
   **Settings > System status** lists every check. No banner = done.
3. **Load samples** (6 jobs, 40 resumes) > open a job > **Write 5 AI reports** > **Interview** on a match > take the
   interview in Chrome.
4. Sidebar **Platform admin**: every company with users, jobs, resumes, applications, interviews and sign-ins.
5. Remove the samples later: Settings > Data > **Remove sample data**.

Who can sign up: anyone, which creates their own company with them as owner. Everyone else joins a company through an
invite link from its owner or admin (Team page). You can disable any company or user from Platform admin.

## Local development

```
cp deploy/backend.env.example .env     # fill in; leave DATABASE_URL and S3_* empty to use local files
pip install -r backend/requirements.txt
cd frontend && npm ci && npm run build && cd ..
uvicorn backend.main:app --port 8000   # open http://localhost:8000
```
For live UI editing run `cd frontend && npm run dev` as well (Vite forwards `/api` to port 8000). Voice interviews from a
laptop need a public tunnel (`cloudflared tunnel --url http://localhost:8000`) set as `PUBLIC_URL`.

## What free costs you
- **Data:** free AI endpoints may log or train on prompts, including resumes and transcripts. Use paid models for real candidates.
- **Sleep:** Render free sleeps after 15 minutes idle; the first request then takes about 30 seconds. Starter ($7/month) doesn't sleep.
- **Storage:** without `DATABASE_URL` every account and job is wiped when Render restarts; without `S3_*`, resumes and recordings are.
- **Reliability:** free models get rate-limited. Each live turn tries 3 models, then a safe fallback line.

## Keep to one instance
Interview locks, sign-in rate limits and the background worker (messages, deadlines, retention, mailbox import) live
in one process. Don't scale the backend beyond one instance.

## Free plan and background work
The background worker sends messages, applies deadlines and reminders, scores recordings, applies each company's
retention settings and imports the mailbox. On Render's free plan the service sleeps after 15 minutes without
visitors, and the worker sleeps with it: queued messages and reminders go out when the next visitor wakes it. Use the
Starter plan (or an uptime pinger hitting `/api/health`) when candidates are moving through flows.
