"""FastAPI application entrypoint for the Stash backend scaffold."""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from api.artifacts import router as artifacts_router
from api.artifacts import stats_router
from api.categories import router as categories_router
from api.digest import router as digest_router
from bot import (
    extract_message_payload,
    get_bot,
    handle_awaiting_edit_message,
    handle_subcategory_callback,
    register_webhook,
    send_error,
    send_processing_ack,
    send_unsupported,
)
from config import get_csv_env, get_env
from logging_config import structlog
from storage.db import SessionLocal
from storage.r2 import get_r2_client

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

REQUIRED_ENV_VARS = (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_WEBHOOK_URL",
    "GOOGLE_CLOUD_PROJECT",
    "VERTEX_REGION",
    "DATABASE_URL",
    "REDIS_URL",
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY",
    "R2_SECRET_KEY",
    "R2_BUCKET_NAME",
    "R2_BUCKET_ID",
    "SECRET_KEY",
    "DASHBOARD_URL",
    "YOUR_CHAT_ID",
    "CORS_ORIGINS",
)

app: FastAPI = FastAPI(title="Stash API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_csv_env("CORS_ORIGINS", required=True),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(categories_router)
app.include_router(artifacts_router)
app.include_router(stats_router)
app.include_router(digest_router)


def validate_environment() -> None:
    """Validate required production environment variables."""
    missing = [name for name in REQUIRED_ENV_VARS if not get_env(name)]
    for name in missing:
        logger.error("missing_required_environment_variable", env_var=name, duration_ms=0)
    if missing:
        raise SystemExit(1)


@app.get("/health")
def health_check() -> JSONResponse:
    """Check core runtime dependencies used by the Stash backend."""
    status: dict[str, str] = {}

    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            status["db"] = "ok"
        finally:
            db.close()
    except Exception:
        logger.exception("health_check_db_failed", duration_ms=0)
        status["db"] = "failed"

    try:
        from bot import get_redis_client

        get_redis_client().ping()
        status["redis"] = "ok"
    except Exception:
        logger.exception("health_check_redis_failed", duration_ms=0)
        status["redis"] = "failed"

    try:
        get_r2_client().head_bucket(Bucket=get_env("R2_BUCKET_NAME", required=True))
        status["r2"] = "ok"
    except Exception:
        logger.exception("health_check_r2_failed", duration_ms=0)
        status["r2"] = "failed"

    if all(value == "ok" for value in status.values()):
        return JSONResponse(status_code=200, content={"status": "ok", **status})

    failed = [name for name, value in status.items() if value != "ok"]
    return JSONResponse(status_code=503, content={"status": "failed", "failed": failed, **status})


@app.post("/webhook", response_model=None)
async def telegram_webhook(request: Request) -> dict[str, bool]:
    """Receive Telegram webhook updates and enqueue supported artifacts."""
    chat_id: int | None = None

    try:
        update_json = await request.json()

        from telegram import Update

        update = Update.de_json(update_json, get_bot())
        callback_query = update.callback_query
        if callback_query is not None:
            await handle_subcategory_callback(callback_query)
            return {"ok": True}

        message = update.effective_message
        if message is None:
            return {"ok": True}

        if await handle_awaiting_edit_message(message):
            return {"ok": True}

        payload = extract_message_payload(message)
        chat_id = payload["chat_id"]

        if payload["input_type"] == "unsupported":
            await send_unsupported(chat_id)
            return {"ok": True}

        from tasks import process_artifact

        process_artifact.delay(dict(payload))
        await send_processing_ack(chat_id)
    except Exception as exc:
        logger.exception("telegram_webhook_handling_failed", duration_ms=0)
        if chat_id is not None:
            try:
                await send_error(chat_id, "Please try again in a moment.")
            except Exception:
                logger.exception("telegram_error_response_failed", duration_ms=0)

    return {"ok": True}


@app.on_event("startup")
async def startup_event() -> None:
    """Register the Telegram webhook when a deployment URL is configured."""
    validate_environment()
    webhook_url = get_env("TELEGRAM_WEBHOOK_URL")
    if not webhook_url:
        logger.info("telegram_webhook_url_missing", duration_ms=0)
        return

    try:
        await register_webhook(webhook_url)
    except Exception:
        logger.exception("telegram_webhook_registration_failed", duration_ms=0)
