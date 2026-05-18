"""
commands.py — All Telegram command handlers + photo/text message handlers.
All handlers are async and check MY_TELEGRAM_USER_ID before processing.
"""

import logging
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from ai_analyzer import analyze_food
from config import WITA, settings
from database import (
    delete_all_today,
    delete_last_today,
    get_daily_target,
    get_history,
    get_today_logs,
    get_today_totals,
    is_duplicate_update,
    save_food_log,
    update_daily_target,
)

logger = logging.getLogger(__name__)

MY_ID = settings.my_telegram_user_id

# ConversationHandler state for /reset confirmation
WAITING_RESET_CONFIRM = 1

# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------


def _is_authorized(update: Update) -> bool:
    return update.effective_user is not None and update.effective_user.id == MY_ID


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

DAYS_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


def _pct(value: float, target: float) -> str:
    if target <= 0:
        return "–"
    return f"{round(value / target * 100)}%"


def _fmt(n: float) -> str:
    return f"{n:.0f}" if n == int(n) else f"{n:.1f}"


def format_food_reply(result: dict, totals: dict, target=None) -> str:
    """Build the reply message after food analysis."""
    foods = result.get("foods_detected", [])
    total = result.get("total", {})
    confidence = result.get("confidence", "medium")
    notes = result.get("notes", "")

    lines: list[str] = []

    if len(foods) == 1:
        f = foods[0]
        lines += [
            f"🍽 {f['name']}",
            f"Porsi: ~{f.get('portion', '?')}",
            "",
            f"🔥 {_fmt(f.get('calories', 0))} kcal",
            f"💪 Protein : {_fmt(f.get('protein_g', 0))}g",
            f"🍞 Karbo   : {_fmt(f.get('carbs_g', 0))}g",
            f"🧈 Lemak   : {_fmt(f.get('fat_g', 0))}g",
            f"🌿 Serat   : {_fmt(f.get('fiber_g', 0))}g",
        ]
    else:
        names = " + ".join(f["name"] for f in foods)
        lines.append(f"🍽 {names}\n")
        for f in foods:
            lines.append(
                f"- {f['name']} {f.get('portion', '')}".rstrip()
                + f" — {_fmt(f.get('calories', 0))} kcal"
            )
        lines += [
            "",
            "📊 Sajian ini:",
            (
                f"🔥 {_fmt(total.get('calories', 0))} kcal"
                f" | 💪 {_fmt(total.get('protein_g', 0))}g"
                f" | 🍞 {_fmt(total.get('carbs_g', 0))}g"
                f" | 🧈 {_fmt(total.get('fat_g', 0))}g"
                f" | 🌿 {_fmt(total.get('fiber_g', 0))}g"
            ),
        ]

    cal_t = target.calories_target if target else 2000
    p_t = target.protein_target if target else 150
    k_t = target.carbs_target if target else 200
    l_t = target.fat_target if target else 65
    cal_today = totals.get("calories", 0)

    lines += [
        "",
        f"📈 Hari ini: {_fmt(cal_today)} / {_fmt(cal_t)} kcal ({_pct(cal_today, cal_t)})",
        (
            f"P: {_fmt(totals.get('protein_g', 0))}/{_fmt(p_t)}g"
            f" | K: {_fmt(totals.get('carbs_g', 0))}/{_fmt(k_t)}g"
            f" | L: {_fmt(totals.get('fat_g', 0))}/{_fmt(l_t)}g"
        ),
    ]

    if confidence == "low":
        lines += ["", "⚠️ Estimasi kasar (foto kurang jelas)"]
    if notes:
        lines.append(f"💬 {notes}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Photo handler
# ---------------------------------------------------------------------------


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    if await is_duplicate_update(update.update_id):
        logger.info("Duplicate update_id %d — skipped.", update.update_id)
        return
    try:
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


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    if await is_duplicate_update(update.update_id):
        logger.info("Duplicate update_id %d — skipped.", update.update_id)
        return

    text = (update.message.text or "").strip()
    text_lower = text.lower()

    shortcuts = {
        ("total", "rekap"): cmd_total,
        ("history", "riwayat", "histori"): cmd_history,
        ("hapus terakhir", "delete last", "hapus"): cmd_delete,
        ("reset", "reset hari ini"): cmd_reset,
        ("help", "bantuan", "menu"): cmd_help,
    }
    for keywords, handler in shortcuts.items():
        if text_lower in keywords:
            await handler(update, context)
            return

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


# ---------------------------------------------------------------------------
# /start & /help
# ---------------------------------------------------------------------------


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    await cmd_help(update, context)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
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
    if not _is_authorized(update):
        return
    try:
        totals = await get_today_totals()
        target = await get_daily_target()
        now_wita = datetime.now(WITA)
        day_name = DAYS_ID[now_wita.weekday()]
        date_str = now_wita.strftime("%d %b")
        count = totals["entry_count"]
        last_ts = totals.get("last_timestamp")
        last_desc = totals.get("last_description", "")
        last_line = ""
        if last_ts:
            ts_wita = last_ts.astimezone(WITA)
            last_line = f"\n⏱ Terakhir: {last_desc} — {ts_wita.strftime('%H:%M')}"

        await update.message.reply_text(
            f"📊 TOTAL HARI INI — {day_name}, {date_str}\n\n"
            f"🔥 Kalori  : {_fmt(totals['calories'])} / {_fmt(target.calories_target)} kcal"
            f" ({_pct(totals['calories'], target.calories_target)})\n"
            f"💪 Protein : {_fmt(totals['protein_g'])}g / {_fmt(target.protein_target)}g"
            f" ({_pct(totals['protein_g'], target.protein_target)})\n"
            f"🍞 Karbo   : {_fmt(totals['carbs_g'])}g / {_fmt(target.carbs_target)}g"
            f" ({_pct(totals['carbs_g'], target.carbs_target)})\n"
            f"🧈 Lemak   : {_fmt(totals['fat_g'])}g / {_fmt(target.fat_target)}g"
            f" ({_pct(totals['fat_g'], target.fat_target)})\n"
            f"🌿 Serat   : {_fmt(totals['fiber_g'])}g / {_fmt(target.fiber_target)}g"
            f" ({_pct(totals['fiber_g'], target.fiber_target)})\n\n"
            f"📝 {count} entry tercatat{last_line}"
        )
    except Exception as e:
        logger.error("cmd_total error: %s", e, exc_info=True)
        await update.message.reply_text("⚠️ Ada masalah teknis. Coba lagi.")


# ---------------------------------------------------------------------------
# /history
# ---------------------------------------------------------------------------


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
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
                    f"{day_name:<8} {date_str}: {_fmt(entry['calories'])} kcal"
                    f" | P:{_fmt(entry['protein_g'])}g"
                    f" K:{_fmt(entry['carbs_g'])}g"
                    f" L:{_fmt(entry['fat_g'])}g"
                )
            else:
                lines.append(f"{day_name:<8} {date_str}: 0 kcal (tidak ada data)")

        lines.append("──────────────────────")
        if days_with_data > 0:
            avg = total_cal / days_with_data
            lines.append(
                f"Rata-rata: {_fmt(avg)} kcal/hari ({days_with_data} hari dengan data)"
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
    if not _is_authorized(update):
        return
    try:
        deleted = await delete_last_today()
        if deleted:
            await update.message.reply_text(
                f"✅ Dihapus: {deleted.meal_description} ({_fmt(deleted.calories)} kcal)"
            )
        else:
            await update.message.reply_text("Tidak ada entry hari ini yang bisa dihapus.")
    except Exception as e:
        logger.error("cmd_delete error: %s", e, exc_info=True)
        await update.message.reply_text("⚠️ Ada masalah teknis. Coba lagi.")


# ---------------------------------------------------------------------------
# /reset  (2-step via ConversationHandler)
# ---------------------------------------------------------------------------


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_authorized(update):
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
    if not _is_authorized(update):
        return ConversationHandler.END
    text = (update.message.text or "").strip()
    try:
        if text.upper() == "RESET":
            deleted_count = await delete_all_today()
            await update.message.reply_text(f"✅ {deleted_count} entry hari ini telah dihapus.")
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
    if not _is_authorized(update):
        return
    try:
        args = context.args or []
        if not args:
            target = await get_daily_target()
            await update.message.reply_text(
                "🎯 TARGET HARIAN\n"
                f"🔥 Kalori  : {_fmt(target.calories_target)} kcal\n"
                f"💪 Protein : {_fmt(target.protein_target)}g\n"
                f"🍞 Karbo   : {_fmt(target.carbs_target)}g\n"
                f"🧈 Lemak   : {_fmt(target.fat_target)}g\n"
                f"🌿 Serat   : {_fmt(target.fiber_target)}g\n\n"
                "Ubah: /target 2200 160 220 70"
            )
            return

        if len(args) < 4:
            await update.message.reply_text("❌ Format salah. Contoh: /target 2000 150 200 65")
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
