# Deploy (Render, about 10 minutes)

The app is one Python server plus static pages. Render builds it from the `Dockerfile`, and `render.yaml` sets everything up.

## 1. Get the code into GitHub
Push this branch to `Akshat24042001/talentloop` (Claude's push needs the Claude GitHub App installed on the repo with write access).

## 2. Create the service
1. https://dashboard.render.com, then **New > Blueprint**, then pick the `talentloop` repo and this branch.
2. Render reads `render.yaml`. Fill the secret values it asks for:
   - `VAPI_PUBLIC_KEY`: Vapi dashboard > API Keys > **Public** key
   - `LLM_API_KEY`: your OpenAI key (or another OpenAI-compatible provider; then also set `LLM_BASE_URL`)
3. Click **Apply**. The first build takes 3 to 5 minutes.
4. `ADMIN_KEY` is generated for you. Copy it from **Environment**; the HR page asks for it once per browser tab.

You don't need to set `PUBLIC_URL`. The server takes it from Render's `RENDER_EXTERNAL_URL`.

## 3. Check it
- Open `https://<your-service>.onrender.com`. The top line of the HR page must show no red warnings.
- Load the sample data, generate a plan, create a link and open it in Chrome to run a real voice call.
- Then work through the checklist in `REVIEW.md` ("Verify on the first real Vapi call").

## Cost and plan notes
- `starter` plan with a 5 GB disk: about $7/month plus about $1.25/month for the disk. The disk keeps interviews and recordings across restarts and deploys.
- **Free plan:** change `plan: starter` to `plan: free` and delete the `disk:` block. It works for a click-through demo (set `LLM_MOCK=1` to run it with no API keys), but every restart wipes all interviews, and the service sleeps after 15 minutes idle (the first request then takes about a minute).
- Keep it to one instance and one worker. The interview locks live in process memory.

## Railway or Fly instead
Both run the same `Dockerfile`. Mount a volume at `/data` and set the same environment variables. On Railway, `PUBLIC_URL` is picked up from `RAILWAY_PUBLIC_DOMAIN`; on Fly, set `PUBLIC_URL` yourself.
