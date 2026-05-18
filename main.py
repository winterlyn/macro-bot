"""
main.py — FastAPI application entry point.

Lifespan:
  startup  → init DB → set Telegram webhook → init PTB
  shutdown → delete webhook → shutdown PTB

Endpoints:
  POST /telegram  → receive Telegram updates (webhook)
  GET  /health    → health check
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request, Response

from app.bot.setup import bot_app
from app.core.config import WITA, settings
from app.core.database import init_db
from telegram import Update

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
    logger.info("=== Macro Bot starting up ===")

    await init_db()
    logger.info("Database ready.")

    if settings.railway_public_url:
        webhook_url = f"{settings.railway_public_url.rstrip('/')}/telegram"
        await bot_app.bot.set_webhook(
            url=webhook_url,
            secret_token=settings.telegram_webhook_secret,
            allowed_updates=["message"],
        )
        logger.info("Telegram webhook → %s", webhook_url)
    else:
        logger.warning(
            "RAILWAY_PUBLIC_URL not set — webhook NOT registered. "
            "Set it in env vars after Railway assigns a domain, then redeploy."
        )

    await bot_app.initialize()
    logger.info("PTB Application ready.")

    yield  # ── Running ──────────────────────────────────────────────────

    # ── Shutdown ─────────────────────────────────────────────────────────
    logger.info("=== Macro Bot shutting down ===")
    try:
        await bot_app.bot.delete_webhook()
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not delete webhook on shutdown: %s", e)
    await bot_app.shutdown()
    logger.info("Shutdown complete.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Macro Tracker Bot",
    description="Telegram webhook endpoint for macro nutrition tracking.",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/telegram")
async def telegram_webhook(request: Request) -> Response:
    """Receive Telegram updates via webhook."""
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if secret != settings.telegram_webhook_secret:
        logger.warning("Webhook secret mismatch — request rejected.")
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        body = await request.json()
        update = Update.de_json(body, bot_app.bot)
        # Offload processing so we return 200 immediately (< Telegram's 5s timeout)
        asyncio.create_task(bot_app.process_update(update))
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to parse/queue update: %s", e, exc_info=True)

    return Response(content="ok", status_code=200)


@app.get("/health")
async def health_check() -> dict:
    """Health check — returns current server time in WITA."""
    return {
        "status": "ok",
        "timestamp": datetime.now(WITA).isoformat(),
    }
