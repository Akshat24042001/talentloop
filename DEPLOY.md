# Deploy for free (Render + OpenRouter)

## 1. OpenRouter (the AI)
1. Sign up at https://openrouter.ai and create a key under **Keys**. It starts with `sk-or-`.
2. Go to **Settings > Privacy** and turn on the option that allows **free model** endpoints that may train on or log prompts. Without it, free models return "No endpoints found matching your data policy" and every AI call fails.
3. Optional, strongly recommended: buy $10 of credit once. Free models stay free, but the daily cap goes from 50 to 1,000 requests. One interview uses about 25 to 35 requests, so without it you get 1 or 2 interviews a day.

## 2. Vapi (the voice)
Dashboard > **API Keys** > copy the **Public** key. Vapi is not free: it bills per minute, and new accounts get some trial credit. Check your balance before testing.

## 3. Supabase: the database and file storage (free)
Render's free plan wipes its disk every time the service sleeps (15 minutes idle) or redeploys. Supabase keeps
accounts, jobs, candidates and matches (Postgres) and resumes and recordings (Storage).

**Database**
1. Create a project at https://supabase.com (pick the region closest to your users, e.g. Mumbai `ap-south-1`).
2. **Connect** (top bar) > **Session pooler** > copy the URI. It looks like
   `postgresql://postgres.<project-ref>:[YOUR-PASSWORD]@aws-0-ap-south-1.pooler.supabase.com:5432/postgres`.
   Put your database password in it. This is `DATABASE_URL`. (Use the Session pooler: Render can't reach the direct
   connection, which is IPv6 only.) Tables are created automatically on first start.

**File storage (resumes, interview recordings)**
1. **Storage > New bucket**, name it `talentloop`, keep it **Private**.
2. **Storage > Settings > S3 Connection**: copy the **Endpoint** and **Region**, then **New access key**: copy the
   **Access key ID** and **Secret access key** (shown once).
3. These go into Render as `S3_BUCKET=talentloop`, `S3_ENDPOINT_URL` (the endpoint,
   `https://<project-ref>.supabase.co/storage/v1/s3`), `S3_REGION` (e.g. `ap-south-1`), `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`.

Free tier limits: 500 MB database (plenty: about 100,000 candidates), **1 GB of files** and **50 MB per file**.
Resumes are tiny (1,000 resumes is about 200 MB), but a 15-minute interview with camera and screen video is 30 to 60 MB,
so the free 1 GB holds roughly 15 to 30 recorded interviews. For more, upgrade Supabase (Pro: 100 GB) or point the
`S3_*` variables at Backblaze B2 (10 GB free) instead; the database can stay on Supabase either way.

Backblaze B2 instead of Supabase Storage: create a private bucket, an application key for it, and set `S3_BUCKET`,
`S3_ACCESS_KEY_ID` (keyID), `S3_SECRET_ACCESS_KEY` (applicationKey), `S3_ENDPOINT_URL` (`https://s3.<region>.backblazeb2.com`).

## 4. Render (the server), free plan
1. https://dashboard.render.com > **New +** > **Web Service** > pick `Akshat24042001/talentloop`.
2. Branch `main`, runtime **Docker**, instance type **Free**.
3. Environment variables:
   | Key | Value |
   |---|---|
   | `DATABASE_URL` | Supabase Session pooler URI (step 3) |
   | `PLATFORM_ADMIN_EMAILS` | your email (comma-separate several). Sign up with it to get the **Platform admin** console |
   | `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | step 3 |
   | `LLM_API_KEY` | your OpenRouter key |
   | `VAPI_PUBLIC_KEY` | your Vapi public key |
   | `VAPI_PRIVATE_KEY` | optional: Vapi **private** key, lets the server fetch Vapi's cloud video backup |
   | `ADMIN_KEY` | optional: only for scripts that call the API. Leave empty otherwise. Sign-in replaces it in the web app |
   | `SESSION_DAYS` | optional: how long people stay signed in (default 14) |
4. Advanced > Health Check Path: `/api/health`. Then click **Deploy**. The Docker build compiles the web interface first (Node), then builds the Python server; the first build takes a few minutes.

Or use **New + > Blueprint** with this repo (`render.yaml`, free plan) and fill in the values it asks for.

Don't set `PUBLIC_URL`, `LLM_BASE_URL`, `FAST_MODEL`, `SMART_MODEL` or `COOKIE_SECURE`. They are all automatic.

## 5. Check it
1. Open the service URL: you see the landing page. Click **Start free** and sign up with the email in `PLATFORM_ADMIN_EMAILS`.
2. The dashboard shows a yellow banner for any missing setting (temporary database, temporary file storage, missing keys).
   **Settings > System status** lists them all. No banner means everything is set.
3. Click **Load samples** for 6 jobs and 40 resumes, open a job, write the AI reports, and try an AI interview from a match.
4. **Platform admin** (sidebar) shows every company with its users, jobs, resumes, applications, interviews and sign-ins.

Who can sign up: anyone can create a company workspace and becomes its owner. Everyone else joins a company through
an invite link from its owner or admin (Team page), with a role. You can disable any company or user from Platform admin.

## What free costs you (read this)
- **Data:** free endpoints may log or train on prompts, and that includes resumes and interview transcripts. Test with your own or sample data only. For real candidates use paid models: set `FAST_MODEL=openai/gpt-4.1-mini` and `SMART_MODEL=openai/gpt-4.1` in Render (no code change) and add credit.
- **Storage:** Render free has no disk. With Supabase (step 3) everything is kept; without `DATABASE_URL` every account and job is wiped when the service sleeps or redeploys, and without `S3_*` resumes and recordings are.
- **Speed and reliability:** free models are shared and get rate-limited. Each live turn tries 3 models in turn, and if all fail the interviewer uses a safe fallback, which the report counts. Scoring uses two different models and flags any disagreement.
- **Free list changes:** OpenRouter adds and removes free models most weeks. At startup the server checks which ones exist and swaps in available ones. The HR page tells you when it did.

## Keep to one instance
Interview locks and sign-in rate limits live in process memory. Don't scale the service beyond one instance.
