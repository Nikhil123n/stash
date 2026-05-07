# Render Backend Deployment

Use normal Render resources for Stash. Do not deploy the root repo as a Render Blueprint.

The better split is:

- Frontend: Vercel
- Backend API: Render web service
- Database: Render Postgres, Neon, or Supabase
- Redis queue: Render Key Value or Upstash Redis
- Worker and scheduler: separate worker services when you are ready for a paid production setup

## Current Recommended Path

For a low-cost prototype, deploy only the backend API on Render and use separately created database and Redis resources.

1. Delete any failed Render Blueprint stack created from this repo.
2. Keep the existing Vercel frontend deployment.
3. In Render, create a Postgres database, or use Neon/Supabase Postgres.
4. In Render, create Key Value, or use Upstash Redis.
5. In Render, create a **Web Service** for `stash-api`.
6. Connect `https://github.com/Nikhil123n/stash`.
7. Use Docker deployment with:
   - Dockerfile path: `backend/Dockerfile`
   - Docker context: `.`
   - Health check path: `/health`
8. Leave the Render start command empty so the Dockerfile `CMD` is used.
9. Add backend environment variables manually.
10. Add the Google service account JSON as a Render Secret File named `gcp-service-account.json`.
11. Set Vercel `VITE_API_URL` to the Render backend URL and redeploy the frontend.

## Backend Environment

Set these on the Render `stash-api` web service:

- `DATABASE_URL`: database connection string
- `REDIS_URL`: Redis or Render Key Value connection string
- `TELEGRAM_BOT_TOKEN`: Telegram bot token
- `TELEGRAM_WEBHOOK_URL`: `https://<render-api-host>/webhook`
- `YOUR_CHAT_ID`: Telegram chat ID
- `GOOGLE_CLOUD_PROJECT`: Vertex AI project ID
- `GOOGLE_APPLICATION_CREDENTIALS`: `/etc/secrets/gcp-service-account.json`
- `VERTEX_REGION`: `us-central1`
- `GEMINI_MODEL`: `gemini-2.5-flash`
- `GEMINI_VIDEO_MODEL`: `gemini-2.5-pro`
- `GEMINI_INLINE_VIDEO_MAX_BYTES`: `18000000`
- `GEMINI_TRANSCRIPTION_INLINE_MAX_BYTES`: `18000000`
- `R2_ACCOUNT_ID`: Cloudflare R2 account ID
- `R2_ACCESS_KEY`: Cloudflare R2 access key
- `R2_SECRET_KEY`: Cloudflare R2 secret key
- `R2_BUCKET_NAME`: Cloudflare R2 bucket name
- `R2_BUCKET_ID`: Cloudflare R2 public bucket ID
- `SECRET_KEY`: long random JWT signing secret
- `DASHBOARD_URL`: `https://stash-two-zeta.vercel.app`
- `CORS_ORIGINS`: `https://stash-two-zeta.vercel.app`
- `SKIP_AUTH`: `false`
- `DASHBOARD_ALLOWED_CHAT_IDS`: your Telegram chat ID, or a comma-separated allowlist
- `DASHBOARD_MAGIC_LINK_TTL_SECONDS`: `600`
- `DASHBOARD_SESSION_TTL_SECONDS`: `2592000`
- `VIDEO_URL_ANALYSIS_ENABLED`: `true`
- `VIDEO_URL_MAX_BYTES`: `18000000`
- `VIDEO_URL_MAX_DURATION_SECONDS`: `180`
- `VIDEO_URL_DOWNLOAD_FORMAT`: `bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4][height<=720]/best[height<=720]/best`
- `YTDLP_SOCKET_TIMEOUT_SECONDS`: `15`
- `YTDLP_RETRIES`: `2`
- `YTDLP_FRAGMENT_RETRIES`: `2`
- `STASH_TMP_DIR`: `/tmp`
- `RUN_MIGRATIONS_ON_START`: `true` for the first deploy, then `false` after migrations succeed

## Worker Reality

Stash uses Celery for Telegram artifact processing. The clean production setup is:

- `stash-api`: Render web service
- `stash-worker`: Render background worker running `celery -A tasks worker --loglevel=info --concurrency=2`
- `stash-beat`: Render background worker running `celery -A tasks beat --loglevel=info`

Render free plans do not support background workers. If you only deploy `stash-api` on Render free, webhook requests can enqueue jobs, but nothing will process the queue unless a worker is running somewhere.

For prototype testing, run the worker locally against the deployed `REDIS_URL` and `DATABASE_URL`:

```bash
cd backend
celery -A tasks worker --loglevel=info --concurrency=1
```

Run Beat locally only when you need scheduled digest/category evolution jobs:

```bash
cd backend
celery -A tasks beat --loglevel=info
```

For production, use paid Render worker services or move workers to another host that supports long-running background processes.

## Post-Deploy Checks

After deployment, run:

```bash
curl https://<render-api-host>/health
```

Expected healthy response:

```json
{"status":"ok","db":"ok","redis":"ok","r2":"ok"}
```

If `/health` returns 503, fix the named dependency first. A failed `r2` check usually means the R2 bucket name or credentials are wrong.
