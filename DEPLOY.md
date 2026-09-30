# Deploy for free (Render + OpenRouter)

## 1. OpenRouter (the AI)
1. Sign up at https://openrouter.ai and create a key under **Keys**. It starts with `sk-or-`.
2. Go to **Settings > Privacy** and turn on the option that allows **free model** endpoints that may train on or log prompts. Without it, free models return "No endpoints found matching your data policy" and every AI call fails.
3. Optional, strongly recommended: buy $10 of credit once. Free models stay free, but the daily cap goes from 50 to 1,000 requests. One interview uses about 25 to 35 requests, so without it you get 1 or 2 interviews a day.

## 2. Vapi (the voice)
Dashboard > **API Keys** > copy the **Public** key. Vapi is not free: it bills per minute, and new accounts get some trial credit. Check your balance before testing.

## 3. Storage that survives restarts (Backblaze B2, free, no card)
Render's free plan wipes its disk every time the service sleeps (15 minutes idle) or redeploys. Without
this step, **interviews, reports and recordings disappear**. B2 gives 10 GB free.
1. Sign up at https://www.backblaze.com/sign-up/cloud-storage.
2. **Buckets > Create a Bucket**. Pick a unique name, set Files **Private**. Note the bucket's **Endpoint**
   (for example `s3.us-west-004.backblazeb2.com`).
3. **Application Keys > Add a New Application Key**. Allow access to that bucket only, Read and Write.
   Copy the **keyID** and **applicationKey** (it's shown once).
4. You'll put these in Render in step 4: `S3_BUCKET`, `S3_ACCESS_KEY_ID` (keyID), `S3_SECRET_ACCESS_KEY`
   (applicationKey), `S3_ENDPOINT_URL` (`https://` + the endpoint).

About 10 GB holds roughly 250 to 400 fifteen-minute interviews with camera and screen video.

## 4. Render (the server), free plan
1. https://dashboard.render.com > **New +** > **Web Service** > pick `Akshat24042001/talentloop`.
2. Branch `main`, runtime **Docker**, instance type **Free**.
3. Environment variables:
   | Key | Value |
   |---|---|
   | `LLM_API_KEY` | your OpenRouter key |
   | `VAPI_PUBLIC_KEY` | your Vapi public key |
   | `ADMIN_KEY` | a random string of 20+ characters (your HR password) |
   | `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_ENDPOINT_URL` | from step 3 |
   | `VAPI_PRIVATE_KEY` | optional: Vapi **private** key, lets the server fetch Vapi's cloud video backup |
4. Advanced > Health Check Path: `/api/health`. Then click **Deploy**. The Docker build compiles the web interface first (Node), then builds the Python server; the first build takes a few minutes.

Or use **New + > Blueprint** with this repo: `render.yaml` is set to the free plan and generates `ADMIN_KEY` for you.

Don't set `PUBLIC_URL`, `LLM_BASE_URL`, `FAST_MODEL` or `SMART_MODEL`. They are all automatic.

## 5. Check it
Open the service URL. The top line of the HR page shows the models in use, the storage status and warnings (yellow warnings about free models are expected; red means something is broken, e.g. "Storage is temporary" if step 3 is missing). Then load the sample data, generate a plan, create a link and take the interview in Chrome.

## What free costs you (read this)
- **Data:** free endpoints may log or train on prompts, and that includes resumes and interview transcripts. Test with your own or sample data only. For real candidates use paid models: set `FAST_MODEL=openai/gpt-4.1-mini` and `SMART_MODEL=openai/gpt-4.1` in Render (no code change) and add credit.
- **Storage:** Render free has no disk. With the B2 bucket from step 3 everything is kept; without it, interviews are wiped when the service sleeps or redeploys.
- **Speed and reliability:** free models are shared and get rate-limited. Each live turn tries 3 models in turn, and if all fail the interviewer uses a safe fallback, which the report counts. Scoring uses two different models and flags any disagreement.
- **Free list changes:** OpenRouter adds and removes free models most weeks. At startup the server checks which ones exist and swaps in available ones. The HR page tells you when it did.

## Keep to one instance
The interview locks live in process memory. Don't scale the service beyond one instance.
