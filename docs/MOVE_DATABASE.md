# Moving the database next to the server (the big speed fix)

## Why pages are slow

The app server runs on Render in **Singapore**. The database (and file storage) is a Supabase project in **Mumbai
(ap-south-1)**. Every database query travels Singapore → Mumbai → Singapore. A page runs 2 to 26 queries, one after
another, so the trip is paid many times per page. Being close to the database yourself doesn't help: the server is
the one talking to it.

Measured in this repository with the real app and a local Postgres (same code, same data, same pages):

| Round trip to the database | 16 main pages, total | Example: candidate page |
|---|---|---|
| 50 ms (Singapore ↔ Mumbai) | 7.5 s | 0.69 s |
| 2 ms (same region) | 0.67 s | 0.06 s |

The database itself spends under 1 ms per query. Nearly all the time is distance. Render has no region in India, so the
fix is a Supabase project in **Singapore (Southeast Asia, ap-southeast-1)**, next to the Render service.

## Steps (about 30 minutes; the app is offline for the copy)

1. **New Supabase project** in region *Southeast Asia (Singapore)*. In it: create a Storage bucket with the same name
   as the old one, and create S3 access keys (Project Settings > Storage > S3 access keys).
2. **Pause the app** so nothing is written during the copy: Render > the service > Suspend (or scale to 0).
3. On your computer, with Python 3.11 and this repository (`pip install -r backend/requirements.txt`):
   ```
   python scripts/move_database.py --source "<old DATABASE_URL>" --target "<new Session pooler URI>"
   ```
   It refuses to write into a database that already has data and prints the row counts of both sides; they must match.
4. Copy the files:
   ```
   OLD_S3_ENDPOINT_URL=... OLD_S3_REGION=ap-south-1 OLD_S3_ACCESS_KEY_ID=... OLD_S3_SECRET_ACCESS_KEY=... OLD_S3_BUCKET=... \
   NEW_S3_ENDPOINT_URL=... NEW_S3_REGION=ap-southeast-1 NEW_S3_ACCESS_KEY_ID=... NEW_S3_SECRET_ACCESS_KEY=... NEW_S3_BUCKET=... \
   python scripts/move_storage.py
   ```
   Safe to run again; it skips files already copied and checks counts and sizes at the end.
5. On Render, change `DATABASE_URL`, `S3_ENDPOINT_URL`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` (and
   `S3_BUCKET` if the name changed) to the new project, then resume the service.
6. Sign in and open a few pages. Browser devtools > Network > any `/api/` request > Timing shows `Server-Timing`:
   the database time should now be a few milliseconds per query.
7. Keep the old project for a week, then delete it.

Everyone stays signed in and every emailed link keeps working: sessions and the link-signing key are copied with the data.

## Other speed facts

- **Render free plan sleeps** after about 15 minutes without traffic; the first visit then waits for it to start (often
  30 to 60 seconds). Ping `/api/ping` every 5 minutes (see docs/ENVIRONMENT.md) or use a paid instance.
- **Free instances have a small shared CPU**, so heavy work (resume parsing, PDF reports) is slower than on a laptop.
