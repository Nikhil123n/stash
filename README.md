# Stash

Stash is a personal AI-powered content organization system. Forward URLs, images, videos, and text to a Telegram bot; Stash stores the artifact, classifies it with Gemini Flash, and exposes a searchable dashboard.

## Prerequisites

- Python 3.11
- Node.js 20
- Docker and Docker Compose
- Telegram bot token from BotFather
- Google Cloud project with Vertex AI enabled
- Cloudflare R2 bucket and API token
- PostgreSQL and Redis, locally via Docker Compose or managed by Railway

## Local Development

Copy the backend environment file and fill in secrets:

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

Start local infrastructure and services:

```bash
docker compose up --build
```

Run database migrations from the backend directory:

```bash
cd backend
alembic upgrade head
```

Start the frontend during development:

```bash
cd frontend
npm install
npm run dev
```

The API runs on `http://localhost:8000` and the Vite frontend runs on `http://localhost:5173`.

## Environment Variables

Backend variables live in `backend/.env`.

Required production variables:

- `TELEGRAM_BOT_TOKEN`: Bot token from BotFather.
- `TELEGRAM_WEBHOOK_URL`: Public webhook URL ending in `/webhook`.
- `YOUR_CHAT_ID`: Telegram chat ID for subcategory proposals and weekly digests.
- `GOOGLE_CLOUD_PROJECT`: Vertex AI project ID.
- `VERTEX_REGION`: Vertex region, usually `us-central1`.
- `DATABASE_URL`: PostgreSQL URL.
- `REDIS_URL`: Redis URL.
- `R2_ACCOUNT_ID`, `R2_ACCESS_KEY`, `R2_SECRET_KEY`: Cloudflare R2 credentials.
- `R2_BUCKET_NAME`, `R2_BUCKET_ID`: R2 storage bucket and public bucket ID.
- `SECRET_KEY`: JWT signing key.
- `DASHBOARD_URL`: Public frontend URL used in digest messages.
- `CORS_ORIGINS`: Comma-separated dashboard origins allowed to call the API.
- `GEMINI_MODEL`: Vertex AI Gemini model used for classification.

Local-only helpers:

- `SKIP_AUTH=true` disables dashboard auth locally.
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` configure the local Compose database.
- `WHISPER_MODEL`, `WHISPER_MIN_AVAILABLE_MEMORY_BYTES`, and `STASH_TMP_DIR` configure local video transcription.
- `YTDLP_COOKIES_BROWSER` or `YTDLP_COOKIES_FILE` can be set when public video metadata extraction needs cookies.

Frontend variables live in `frontend/.env`.

- `VITE_API_URL`: API base URL.
- `VITE_SKIP_AUTH`: Set to `true` only for local dashboard auth bypass.
- `VITE_TELEGRAM_BOT_NAME`: Telegram bot name for the login widget.

Never commit real `.env` files. Use `.env.example` files for safe placeholders only.

## Deploying to Railway

Create Railway services for:

- `web`: FastAPI API using `backend/Dockerfile`.
- `worker`: Celery worker using the same image.
- `beat`: Celery Beat scheduler using the same image.
- Railway Redis.
- Railway PostgreSQL.

The service commands are defined in `railway.toml`.

Before deploying, run:

```bash
python scripts/check_deploy.py
```

Then apply migrations against the production database:

```bash
cd backend
alembic upgrade head
```

After deployment, verify:

```bash
curl https://your-api.railway.app/health
```

Expected response:

```json
{"status":"ok","db":"ok","redis":"ok","r2":"ok"}
```

## How To Use

Forward content to your Telegram bot:

- Instagram, LinkedIn, or regular URLs.
- Screenshots and images.
- Video files.
- Plain text snippets.

The bot replies immediately with `Got it, processing...`, then sends a saved confirmation after Celery finishes classification and storage.

Open the dashboard to browse categories, search artifacts, view details, re-categorize items, or delete stale saves.

## Dynamic Categories

Stash starts with AI-generated top-level categories. As a category grows:

- At 10+ uncategorized items, the nightly evolution task proposes Tier 2 subcategories in Telegram.
- You can apply, skip for 30 days, or edit proposed names.
- At 50+ items in a subcategory, Tier 3 micro-clusters can be created automatically.

Manual dashboard corrections are stored as learning signals. When the same correction pattern appears at least three times, Stash creates a few-shot prompt example so future Gemini classifications are steered toward your preferences.

## Troubleshooting

`/health` returns 503:
Check the failed component names in the response. DB usually means `DATABASE_URL`; Redis means `REDIS_URL`; R2 means bucket credentials or bucket name.

Telegram webhook does not fire:
Confirm `TELEGRAM_WEBHOOK_URL` is public HTTPS and ends with `/webhook`. Check Railway logs for webhook registration failures.

Artifacts stay in processing:
Check Celery worker logs and Redis connectivity. The webhook only enqueues work; classification happens in the worker.

Video transcription fails:
Whisper needs memory and `ffmpeg`. The runtime image installs `ffmpeg`; if memory is below 800 MB, transcription is skipped and logged.

Gemini errors:
Verify `GOOGLE_CLOUD_PROJECT`, `VERTEX_REGION`, and Vertex AI permissions. Quota errors are wrapped as classification errors in worker logs.

R2 images do not load:
Check `R2_BUCKET_ID` and that the bucket public URL is enabled. Stored object keys are private unless the public bucket URL is configured.
