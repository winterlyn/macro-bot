"""
bot.py — Telegram Application setup + handler registration.
Does NOT run polling. Used as a singleton imported by main.py.
"""

import logging

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from commands import (
    WAITING_RESET_CONFIRM,
    cmd_delete,
    cmd_help,
    cmd_history,
    cmd_reset,
    cmd_start,
    cmd_target,
    cmd_total,
    handle_photo,
    handle_text,
    reset_confirm,
)
from config import settings

logger = logging.getLogger(__name__)


def build_application():
    """Build and return the configured Telegram Application (no polling)."""
    application = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .build()
    )

    # /reset uses a 2-step ConversationHandler
    reset_conv = ConversationHandler(
        entry_points=[CommandHandler("reset", cmd_reset)],
        states={
            WAITING_RESET_CONFIRM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, reset_confirm)
            ]
        },
        fallbacks=[CommandHandler("reset", cmd_reset)],
        conversation_timeout=30,
    )

    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("total", cmd_total))
    application.add_handler(CommandHandler("history", cmd_history))
    application.add_handler(CommandHandler("delete", cmd_delete))
    application.add_handler(CommandHandler("target", cmd_target))
    application.add_handler(reset_conv)

    logger.info("Telegram Application built and handlers registered.")
    return application


# Singleton — imported by main.py
bot_app = build_application()
