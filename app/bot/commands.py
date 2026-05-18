"""
app/bot/commands.py — All /command handlers.

Commands:
    /start, /help  → show menu
    /total         → today's macro summary
    /history       → 7-day history
    /delete        → remove last today's entry
    /reset         → 2-step delete all today (ConversationHandler)
    /target        → view / update daily targets
"""

import logging
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from app.bot.utils import DAYS_ID, fmt, is_authorized, pct
from app.core.config import WITA
from app.core.database import (
    delete_all_today,
    delete_last_today,
    get_daily_target,
    get_history,
    get_today_logs,
    get_today_totals,
    update_daily_target,
)

logger = logging.getLogger(__name__)

# ConversationHandler state constant (imported by setup.py)
WAITING_RESET_CONFIRM = 1


# ---------------------------------------------------------------------------
# /start & /help
# ---------------------------------------------------------------------------


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    await cmd_help(update, context)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    await update.message.reply_text(
        "🤖 MACRO TRACKER BOT\n\n"
        "📸 Kirim foto → analisis otomatis\n"
        "📝 Ketik nama makanan → estimasi manual\n\n"
        "📋 COMMANDS:\n"
        "/total — rekap makro hari ini\n"
        "/history — riwayat 7 hari terakhir\n"
        "/delete — hapus entry terakhir hari ini\n"
        "/reset — hapus semua entry hari ini\n"
        "/target — lihat target kalori\n"
        "/target 2000 150 200 65 — set target baru\n"
        "         (urutan: kalori protein karbo lemak)\n\n"
        "Shortcut tanpa slash: total, history, hapus"
    )


# ---------------------------------------------------------------------------
# /total
# ---------------------------------------------------------------------------


async def cmd_total(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    try:
        totals = await get_today_totals()
        target = await get_daily_target()

        now_wita = datetime.now(WITA)
        day_name = DAYS_ID[now_wita.weekday()]
        date_str = now_wita.strftime("%d %b")
        count = totals["entry_count"]

        last_line = ""
        if totals.get("last_timestamp"):
            ts_wita = totals["last_timestamp"].astimezone(WITA)
            last_line = (
                f"\n⏱ Terakhir: {totals['last_description']}"
                f" — {ts_wita.strftime('%H:%M')}"
            )

        await update.message.reply_text(
            f"📊 TOTAL HARI INI — {day_name}, {date_str}\n\n"
            f"🔥 Kalori  : {fmt(totals['calories'])} / {fmt(target.calories_target)} kcal"
            f" ({pct(totals['calories'], target.calories_target)})\n"
            f"💪 Protein : {fmt(totals['protein_g'])}g / {fmt(target.protein_target)}g"
            f" ({pct(totals['protein_g'], target.protein_target)})\n"
            f"🍞 Karbo   : {fmt(totals['carbs_g'])}g / {fmt(target.carbs_target)}g"
            f" ({pct(totals['carbs_g'], target.carbs_target)})\n"
            f"🧈 Lemak   : {fmt(totals['fat_g'])}g / {fmt(target.fat_target)}g"
            f" ({pct(totals['fat_g'], target.fat_target)})\n"
            f"🌿 Serat   : {fmt(totals['fiber_g'])}g / {fmt(target.fiber_target)}g"
            f" ({pct(totals['fiber_g'], target.fiber_target)})\n\n"
            f"📝 {count} entry tercatat{last_line}"
        )
    except Exception as e:
        logger.error("cmd_total error: %s", e, exc_info=True)
        await update.message.reply_text("⚠️ Ada masalah teknis. Coba lagi.")


# ---------------------------------------------------------------------------
# /history
# ---------------------------------------------------------------------------


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    try:
        history = await get_history(days=7)
        lines = ["📅 RIWAYAT 7 HARI\n"]
        days_with_data = 0
        total_cal = 0.0

        for entry in history:
            d = entry["date"]
            day_name = DAYS_ID[d.weekday()]
            date_str = d.strftime("%d/%m")
            if entry["entry_count"] > 0:
                days_with_data += 1
                total_cal += entry["calories"]
                lines.append(
                    f"{day_name:<8} {date_str}: {fmt(entry['calories'])} kcal"
                    f" | P:{fmt(entry['protein_g'])}g"
                    f" K:{fmt(entry['carbs_g'])}g"
                    f" L:{fmt(entry['fat_g'])}g"
                )
            else:
                lines.append(f"{day_name:<8} {date_str}: 0 kcal (tidak ada data)")

        lines.append("──────────────────────")
        if days_with_data > 0:
            avg = total_cal / days_with_data
            lines.append(
                f"Rata-rata: {fmt(avg)} kcal/hari ({days_with_data} hari dengan data)"
            )
        else:
            lines.append("Belum ada data minggu ini.")

        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        logger.error("cmd_history error: %s", e, exc_info=True)
        await update.message.reply_text("⚠️ Ada masalah teknis. Coba lagi.")


# ---------------------------------------------------------------------------
# /delete
# ---------------------------------------------------------------------------


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    try:
        deleted = await delete_last_today()
        if deleted:
            await update.message.reply_text(
                f"✅ Dihapus: {deleted.meal_description} ({fmt(deleted.calories)} kcal)"
            )
        else:
            await update.message.reply_text("Tidak ada entry hari ini yang bisa dihapus.")
    except Exception as e:
        logger.error("cmd_delete error: %s", e, exc_info=True)
        await update.message.reply_text("⚠️ Ada masalah teknis. Coba lagi.")


# ---------------------------------------------------------------------------
# /reset — 2-step confirmation via ConversationHandler
# ---------------------------------------------------------------------------


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 1: Ask for confirmation."""
    if not is_authorized(update):
        return ConversationHandler.END
    try:
        logs = await get_today_logs()
        count = len(logs)
        if count == 0:
            await update.message.reply_text("Tidak ada entry hari ini untuk direset.")
            return ConversationHandler.END

        context.user_data["reset_count"] = count
        await update.message.reply_text(
            f"⚠️ Yakin hapus semua {count} entry hari ini?\n"
            "Ketik RESET untuk konfirmasi, atau ketik apapun lain untuk batal."
        )
        return WAITING_RESET_CONFIRM
    except Exception as e:
        logger.error("cmd_reset error: %s", e, exc_info=True)
        await update.message.reply_text("⚠️ Ada masalah teknis. Coba lagi.")
        return ConversationHandler.END


async def reset_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 2: Process confirmation reply."""
    if not is_authorized(update):
        return ConversationHandler.END
    text = (update.message.text or "").strip()
    try:
        if text.upper() == "RESET":
            deleted_count = await delete_all_today()
            await update.message.reply_text(
                f"✅ {deleted_count} entry hari ini telah dihapus."
            )
        else:
            await update.message.reply_text("❌ Reset dibatalkan.")
    except Exception as e:
        logger.error("reset_confirm error: %s", e, exc_info=True)
        await update.message.reply_text("⚠️ Ada masalah teknis. Coba lagi.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# /target
# ---------------------------------------------------------------------------


async def cmd_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    try:
        args = context.args or []

        if not args:
            target = await get_daily_target()
            await update.message.reply_text(
                "🎯 TARGET HARIAN\n"
                f"🔥 Kalori  : {fmt(target.calories_target)} kcal\n"
                f"💪 Protein : {fmt(target.protein_target)}g\n"
                f"🍞 Karbo   : {fmt(target.carbs_target)}g\n"
                f"🧈 Lemak   : {fmt(target.fat_target)}g\n"
                f"🌿 Serat   : {fmt(target.fiber_target)}g\n\n"
                "Ubah: /target 2200 160 220 70"
            )
            return

        if len(args) < 4:
            await update.message.reply_text(
                "❌ Format salah. Contoh: /target 2000 150 200 65"
            )
            return

        try:
            calories, protein, carbs, fat = (float(a) for a in args[:4])
        except ValueError:
            await update.message.reply_text(
                "❌ Format salah. Semua nilai harus angka.\nContoh: /target 2000 150 200 65"
            )
            return

        errors = []
        if not (500 <= calories <= 5000):
            errors.append("Kalori harus 500–5000")
        if not (10 <= protein <= 500):
            errors.append("Protein harus 10–500g")
        if not (10 <= carbs <= 500):
            errors.append("Karbo harus 10–500g")
        if not (10 <= fat <= 500):
            errors.append("Lemak harus 10–500g")
        if errors:
            await update.message.reply_text("❌ " + "\n".join(errors))
            return

        await update_daily_target(calories, protein, carbs, fat)
        await update.message.reply_text("✅ Target diperbarui! /target untuk lihat detail.")

    except Exception as e:
        logger.error("cmd_target error: %s", e, exc_info=True)
        await update.message.reply_text("⚠️ Ada masalah teknis. Coba lagi.")
