# Stash Pending Work

Source reviewed: `stash_build_document.docx` in the repository root.

Verification snapshot:
- Backend tests: `python -m pytest tests` passed with 32 tests.
- Frontend build: `npm run build --prefix frontend` passed.
- Current branch has uncommitted implementation work, including the video URL analysis and LLM consistency changes.

## P0 - Must Fix Before Real Use

### 1. Implement the Telegram login API endpoint

Build document reference:
- Section 9.1: "Authentication uses the Telegram Login Widget."
- Section 11.3: `SECRET_KEY` is listed as a required environment variable for JWT/auth.

Current state:
- `frontend/src/api.ts` calls `POST /api/auth/telegram`.
- `frontend/src/components/TelegramLogin.tsx` expects `{ token: string }`.
- `backend/auth.py` has verification helpers, but there is no FastAPI router or `/api/auth/telegram` endpoint registered in `backend/main.py`.

Pending work:
- Add `backend/api/auth.py` with `POST /api/auth/telegram`.
- Verify Telegram Login Widget payload using `verify_telegram_login`.
- Issue a signed token using `SECRET_KEY`, or change the frontend/backend contract to consistently pass and verify the raw Telegram login payload.
- Include the auth router in `backend/main.py`.
- Add backend API tests for valid login, invalid hash, expired auth date, and missing payload.
- Add frontend handling for auth failures and token clearing.

Acceptance check:
- With `VITE_SKIP_AUTH=false`, Telegram login opens the dashboard and authenticated API requests succeed.

### 2. Store and render URL/reel thumbnails

Build document reference:
- Section 3: Instagram reel URL AI input includes "Title + description + thumbnail (vision)."
- Section 9.2: video/reel URL cards should show a thumbnail image.
- Section 10.1: "Thumbnail for URL artifacts" is fetched from OG metadata and stored as a URL string.

Current state:
- `backend/storage/r2.py` extracts `image_url` for URLs.
- `backend/tasks.py` does not persist `image_url`.
- `backend/storage/db.py` has no URL thumbnail column.
- `backend/api/serializers.py` exposes only `r2_url`, not a URL thumbnail.
- `frontend/src/components/ArtifactCard.tsx` renders URL artifacts as favicon/title/summary only.

Pending work:
- Add `thumbnail_url` or `source_thumbnail_url` to `artifacts`.
- Persist OG/oEmbed/yt-dlp thumbnail URLs during URL ingestion.
- Expose the thumbnail in API schemas.
- Render URL/reel cards with the thumbnail when available, with favicon fallback.
- Include URL thumbnails in category recent preview strips, not only R2 image thumbnails.
- Add tests for URL thumbnail extraction, persistence, serialization, and card rendering.

Acceptance check:
- Instagram, LinkedIn, YouTube, and generic webpage artifacts show a useful preview image when metadata provides one.

### 3. Add a real processing state for long video work

Build document reference:
- Section 5.2: video flow includes Whisper before final classification.
- Section 7.2: transcript is stored in `ai_transcript` and fed into classification.
- Section 14: if Whisper is slow, "defer classification until transcript is ready - show 'Processing' card in dashboard."

Current state:
- Small uploaded videos can be sent inline to Gemini for video analysis.
- Large uploaded videos are initially classified from an empty transcript, then `transcribe_and_update` may replace metadata later if confidence improves.
- There is no `processing` status on artifacts.
- The dashboard does not show a processing card/state.
- There is no first-frame extraction fallback from uploaded videos.

Pending work:
- Add artifact processing status, for example `processing | ready | failed`.
- For large uploaded videos, create a processing artifact first instead of classifying empty content.
- Run Whisper and/or Gemini video analysis, then finalize the artifact once meaningful metadata exists.
- Add failure status and retry/error visibility.
- Consider first-frame extraction for uploaded videos when full inline Gemini video is too large.
- Update dashboard cards and modal for processing/failed states.

Acceptance check:
- A large video upload never appears as a misleading empty or low-quality classification while transcription/video analysis is still pending.

## P1 - Required For v1 Completeness

### 4. Wire Tier 3 category evolution into the scheduled job

Build document reference:
- Section 4.2: Tier 3 micro-clusters unlock after 50+ items in a sub-category and are automatic.
- Section 7.4: nightly job handles Tier 2/3 evolution.
- Phase 3: "Nightly sub-category clustering job."

Current state:
- `backend/ai/evolve.py` implements `run_tier3_evolution`.
- `backend/tasks.py` only calls `run_tier2_evolution` from `check_category_evolution`.
- No scheduled code path invokes Tier 3 evolution.

Pending work:
- Update `check_category_evolution` to scan large confirmed subcategories and call `run_tier3_evolution`.
- Add guardrails so Tier 3 does not repeatedly recluster the same items unnecessarily.
- Add tests for Tier 3 trigger threshold, no-op below threshold, and subcategory count refresh.

Acceptance check:
- A subcategory with 50+ artifacts automatically creates Tier 3 micro-clusters without Telegram confirmation.

### 5. Add dashboard auto-refresh or polling after Telegram ingest

Build document reference:
- Section 5.3: "Web dashboard reflects the new artifact on next refresh (or via polling)."

Current state:
- React Query fetches categories/artifacts when pages load.
- There is no periodic polling or push refresh for new Telegram saves.
- If the dashboard is already open while an artifact is forwarded, the user may need to manually refresh.

Pending work:
- Add sensible polling intervals for categories, stats, and active artifact lists.
- Keep polling light to preserve free-tier resources.
- Pause or slow polling when the tab is hidden.
- Add a manual refresh button if needed.

Acceptance check:
- Forwarding a new Telegram item appears on an open dashboard without a browser reload.

### 6. Complete low-confidence review workflow

Build document reference:
- Section 14: Gemini misclassification mitigation requires low-confidence flagging and quick re-categorize.
- Section 15: manual re-categorize must work and persist.

Current state:
- Low-confidence items are flagged in cards.
- Stats show `needs_review_count`.
- Manual re-categorize works from the modal.
- There is no dedicated "Needs review" queue/filter from the dashboard.

Pending work:
- Add an API filter for `needs_review=true` or a dedicated endpoint.
- Make the "Needs review" stat card clickable.
- Show a review queue optimized for fast category correction.
- Add tests for the filter and UI state.

Acceptance check:
- The user can open all low-confidence items in one view and correct them quickly.

### 7. Reconcile the build document with the new reel/video URL strategy

Build document reference:
- Section 2.2 says Stash v1 is "Not a video downloader for Instagram."
- Section 10.1 says Instagram/web URLs are stored as PostgreSQL URL references only.
- The current product requirement asks Stash to process actual social/reel video content, not only title/caption/URL metadata.

Current state:
- The code now includes bounded `yt-dlp` download support for public social video analysis.
- This intentionally differs from the original build document.

Pending work:
- Decide the official v1 policy for social/reel video URLs.
- Update the build document or add a repo policy doc describing:
  - allowed providers,
  - max duration and byte limits,
  - cookie requirements,
  - failure/fallback behavior,
  - privacy/storage behavior,
  - legal/platform risk boundaries.
- Ensure README and `.env.example` match the final policy.

Acceptance check:
- The repo has one clear source of truth for whether social video URL bytes are downloaded, analyzed, stored, or discarded.

### 8. Store URL source metadata more completely

Build document reference:
- Section 4.1: artifact metadata drives categorization and retrieval.
- Section 10.1: URL artifacts store metadata and thumbnail references.

Current state:
- URL extraction returns fields such as `site_name`, `resolved_url`, `image_url`, `video_url`, and rich extracted text.
- Artifact persistence stores only `raw_url`, AI fields, category IDs, and optional transcript/content details.
- The original extracted URL metadata is not retained for audit, display, or reprocessing.

Pending work:
- Add `source_metadata` JSONB or explicit columns for URL metadata.
- Store resolved URL, site name, image URL, video URL, extraction source, and content extraction status.
- Expose safe display fields in the API.
- Add migration and tests.

Acceptance check:
- A saved URL can be inspected later with its original extracted metadata, not only AI-generated fields.

## P2 - Deployment, QA, And Acceptance

### 9. Add migration execution to the deployment workflow

Build document reference:
- Section 11: Railway deployment runs FastAPI, worker, beat, Redis, and PostgreSQL.
- Section 15: "No data loss across Railway restarts."

Current state:
- Alembic migrations exist.
- `railway.toml` starts the web, worker, and beat services.
- No deployment step automatically runs `alembic upgrade head`.

Pending work:
- Add a documented release command or Railway-safe migration process.
- Decide whether migrations run manually, in CI/CD, or as a one-off Railway job.
- Update `scripts/check_deploy.py` and README with the chosen process.

Acceptance check:
- A fresh Railway database reaches Alembic head before workers process artifacts.

### 10. Finish production frontend deployment wiring

Build document reference:
- Section 9: React web dashboard is part of v1.
- Section 11: deployment is Railway-based.

Current state:
- Frontend builds successfully.
- `frontend/Dockerfile` exists.
- Root `railway.toml` points to `backend/Dockerfile` for the build.
- The backend and frontend deployment relationship is not fully documented as separate Railway services or static hosting.

Pending work:
- Choose final frontend hosting: Railway service, Vercel/static host, or backend-served static assets.
- Set production `VITE_API_URL`, `VITE_SKIP_AUTH=false`, and `VITE_TELEGRAM_BOT_NAME`.
- Document CORS settings for the production frontend origin.
- Add deploy checks for frontend environment readiness.

Acceptance check:
- Production dashboard loads, authenticates, and calls the production API without CORS/auth failures.

### 11. Add seeded Tier 1 categories or explicitly remove that requirement

Build document reference:
- Section 4.2: Tier 1 starts with approximately 8 broad categories such as Coding, Food & Recipes, Learning/Education, Design & UX, Fitness, Business/Career, Mental models, Other.

Current state:
- Categories are created dynamically from Gemini output.
- There is no seed migration or startup seed for the broad Tier 1 category set.

Pending work:
- Either add a seed migration/task for the broad v1 categories, or update the spec to say the first categories are fully dynamic.
- If seeding, make it idempotent and safe to rerun.

Acceptance check:
- New installs either start with the documented broad categories or the documentation no longer claims they do.

### 12. Add an exact acceptance-test runbook for v1

Build document reference:
- Section 15 technical acceptance criteria:
  - forward any of the 6 input types,
  - >80% classification accuracy on 20 spot-checked items,
  - dashboard loads categories in <1 second,
  - search returns relevant results for 3 queries,
  - weekly digest arrives Sunday,
  - manual re-categorize persists,
  - no data loss across Railway restarts.

Current state:
- Unit/backend tests pass.
- Frontend build passes.
- There is no documented staging acceptance checklist or repeatable end-to-end validation script.

Pending work:
- Create a staging test checklist covering all 6 input types.
- Add sample test artifacts and expected outcomes.
- Measure dashboard category API latency.
- Verify weekly digest with a manual trigger or preview route.
- Verify Railway restart persistence.
- Capture results in a release checklist.

Acceptance check:
- Before v1 release, the acceptance checklist can be run and signed off without relying on memory.

### 13. Decide whether semantic search is v1 or post-v1

Build document reference:
- Section 1.2 asks for search "by meaning."
- Section 9.2/9.3 specifies PostgreSQL full-text search.
- Section 16 lists semantic/vector search as post-v1 future scope.

Current state:
- Search uses PostgreSQL full-text search over title, summary, tags, and transcript.
- No embeddings or pgvector exist.

Pending work:
- Treat semantic/vector search as post-v1 unless the product requirement changes.
- If moved into v1, add embeddings, pgvector, backfill jobs, and hybrid ranking.

Acceptance check:
- The v1 release criteria clearly state whether full-text search is sufficient.

## Already Covered Or Mostly Covered

- Telegram webhook ingestion and immediate processing acknowledgement are implemented.
- Celery worker and beat tasks exist.
- R2 upload/download/delete support exists for binary media.
- Gemini classification supports text, image, URL metadata, transcript, and current video-byte analysis paths.
- LLM consistency controls and `ai_audit` are now implemented.
- Manual re-categorization records `user_corrections`.
- Few-shot prompt examples are generated from repeated corrections.
- Tier 2 proposal, Telegram confirmation, skip, and edit-name flows exist.
- Weekly digest query, formatter, scheduled task, and preview API exist.
- Backend tests and frontend production build pass locally.
