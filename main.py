"""
main.py — FastAPI app with lifespan + Telegram webhook endpoint.
AI calls are offloaded via asyncio.create_task() so the endpoint
responds in <1s and never times out Telegram's 5-second window.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request, Response
from telegram import Update

from bot import bot_app
from config import WITA, settings
from database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────
    logger.info("Starting up…")

    # 1. Init DB
    await init_db()
    logger.info("Database initialised.")

    # 2. Set Telegram webhook
    if settings.railway_public_url:
        webhook_url = f"{settings.railway_public_url.rstrip('/')}/telegram"
        await bot_app.bot.set_webhook(
            url=webhook_url,
            secret_token=settings.telegram_webhook_secret,
            allowed_updates=["message"],
        )
        logger.info("Webhook set to %s", webhook_url)
    else:
        logger.warning(
            "RAILWAY_PUBLIC_URL not set — webhook NOT registered. "
            "Set it and redeploy after Railway assigns a URL."
        )

    # 3. Initialise PTB application (without starting polling)
    await bot_app.initialize()
    logger.info("PTB Application initialised.")

    yield  # ── App is running ──────────────────────────────────────────

    # ── Shutdown ─────────────────────────────────────────────────────────
    logger.info("Shutting down…")
    try:
        await bot_app.bot.delete_webhook()
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not delete webhook: %s", e)
    await bot_app.shutdown()
    logger.info("Shutdown complete.")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Macro Tracker Bot",
    description="Telegram webhook endpoint for macro nutrition tracking bot.",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/telegram")
async def telegram_webhook(request: Request) -> Response:
    """Receive Telegram updates via webhook."""
    # Security: validate secret token
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if secret != settings.telegram_webhook_secret:
        logger.warning("Invalid webhook secret token received.")
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        body = await request.json()
        update = Update.de_json(body, bot_app.bot)

        # Offload to background so we return 200 immediately
        asyncio.create_task(bot_app.process_update(update))

    except Exception as e:  # noqa: BLE001
        logger.error("Failed to parse/process update: %s", e, exc_info=True)
        # Still return 200 so Telegram doesn't retry
        return Response(content="ok", status_code=200)

    return Response(content="ok", status_code=200)


@app.get("/health")
async def health_check() -> dict:
    """Simple health check endpoint."""
    return {
        "status": "ok",
        "timestamp": datetime.now(WITA).isoformat(),
    }
