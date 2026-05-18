"""
app/bot/handlers.py — Photo and text message handlers.

handle_photo  → download image, analyze, save, reply
handle_text   → shortcut keywords + free-text food description
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.bot.commands import (
    cmd_delete,
    cmd_help,
    cmd_history,
    cmd_reset,
    cmd_total,
)
from app.bot.utils import format_food_reply, is_authorized
from app.core.database import (
    get_daily_target,
    get_today_totals,
    is_duplicate_update,
    save_food_log,
)
from app.services.ai_analyzer import analyze_food

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Photo handler
# ---------------------------------------------------------------------------


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming photos: download → analyze → save → reply."""
    if not is_authorized(update):
        return
    if await is_duplicate_update(update.update_id):
        logger.info("Duplicate update_id %d — skipped.", update.update_id)
        return

    try:
        # Highest resolution = last element in photo array
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = bytes(await file.download_as_bytearray())
        caption = update.message.caption or None

        await update.message.reply_text("🔍 Menganalisis foto...")
        result = await analyze_food(image_bytes=image_bytes, text_input=caption)

        if "error" in result:
            if result["error"] == "no_food":
                await update.message.reply_text("❌ Foto tidak mengandung makanan.")
            else:
                await update.message.reply_text(
                    "⚠️ Analisis gagal. Coba foto ulang atau ketik nama makanannya."
                )
            return

        await save_food_log(result, image_used=True, update_id=update.update_id)
        totals = await get_today_totals()
        target = await get_daily_target()
        await update.message.reply_text(format_food_reply(result, totals, target))

    except Exception as e:
        logger.error("handle_photo error: %s", e, exc_info=True)
        await update.message.reply_text("⚠️ Ada masalah teknis. Coba lagi.")


# ---------------------------------------------------------------------------
# Text handler
# ---------------------------------------------------------------------------

# Map of shortcut keywords → handler function
_SHORTCUTS: dict[tuple, object] = {
    ("total", "rekap"): cmd_total,
    ("history", "riwayat", "histori"): cmd_history,
    ("hapus terakhir", "delete last", "hapus"): cmd_delete,
    ("reset", "reset hari ini"): cmd_reset,
    ("help", "bantuan", "menu"): cmd_help,
}


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle plain text: shortcut keywords or free-text food description."""
    if not is_authorized(update):
        return
    if await is_duplicate_update(update.update_id):
        logger.info("Duplicate update_id %d — skipped.", update.update_id)
        return

    text = (update.message.text or "").strip()
    text_lower = text.lower()

    # Check shortcut keywords first
    for keywords, handler in _SHORTCUTS.items():
        if text_lower in keywords:
            await handler(update, context)
            return

    # Treat as food description
    try:
        await update.message.reply_text("🔍 Menganalisis...")
        result = await analyze_food(text_input=text)

        if "error" in result:
            await update.message.reply_text(
                "⚠️ Tidak bisa menganalisis. Coba deskripsikan lebih detail.\n"
                "Contoh: nasi goreng ayam 1 porsi + telur mata sapi"
            )
            return

        await save_food_log(result, image_used=False, update_id=update.update_id)
        totals = await get_today_totals()
        target = await get_daily_target()
        await update.message.reply_text(format_food_reply(result, totals, target))

    except Exception as e:
        logger.error("handle_text error: %s", e, exc_info=True)
        await update.message.reply_text("⚠️ Ada masalah teknis. Coba lagi.")
