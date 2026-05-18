"""
app/bot/utils.py — Shared helpers used by both commands.py and handlers.py.

Includes:
- Auth guard (_is_authorized)
- Number/percentage formatters (_fmt, _pct)
- Day name constants (DAYS_ID)
- Reply formatter (format_food_reply)
"""

from datetime import datetime

from telegram import Update

from app.core.config import settings

MY_ID = settings.my_telegram_user_id

DAYS_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def is_authorized(update: Update) -> bool:
    """Return True only if the sender is the configured owner."""
    return update.effective_user is not None and update.effective_user.id == MY_ID


# ---------------------------------------------------------------------------
# Number formatters
# ---------------------------------------------------------------------------


def fmt(n: float) -> str:
    """Display float without decimal if whole, 1 decimal otherwise."""
    return f"{n:.0f}" if n == int(n) else f"{n:.1f}"


def pct(value: float, target: float) -> str:
    """Return percentage string, or '–' if target is 0."""
    if target <= 0:
        return "–"
    return f"{round(value / target * 100)}%"


# ---------------------------------------------------------------------------
# Reply formatter
# ---------------------------------------------------------------------------


def format_food_reply(result: dict, totals: dict, target=None) -> str:
    """
    Build the Telegram reply after food analysis.

    Args:
        result:  AI analysis dict (foods_detected, total, confidence, notes)
        totals:  Today's running totals from get_today_totals()
        target:  DailyTarget ORM row (or None for defaults)
    """
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
            f"🔥 {fmt(f.get('calories', 0))} kcal",
            f"💪 Protein : {fmt(f.get('protein_g', 0))}g",
            f"🍞 Karbo   : {fmt(f.get('carbs_g', 0))}g",
            f"🧈 Lemak   : {fmt(f.get('fat_g', 0))}g",
            f"🌿 Serat   : {fmt(f.get('fiber_g', 0))}g",
        ]
    else:
        names = " + ".join(f["name"] for f in foods)
        lines.append(f"🍽 {names}\n")
        for f in foods:
            lines.append(
                f"- {f['name']} {f.get('portion', '')}".rstrip()
                + f" — {fmt(f.get('calories', 0))} kcal"
            )
        lines += [
            "",
            "📊 Sajian ini:",
            (
                f"🔥 {fmt(total.get('calories', 0))} kcal"
                f" | 💪 {fmt(total.get('protein_g', 0))}g"
                f" | 🍞 {fmt(total.get('carbs_g', 0))}g"
                f" | 🧈 {fmt(total.get('fat_g', 0))}g"
                f" | 🌿 {fmt(total.get('fiber_g', 0))}g"
            ),
        ]

    # Daily progress vs. target
    cal_t = target.calories_target if target else 2000
    p_t = target.protein_target if target else 150
    k_t = target.carbs_target if target else 200
    l_t = target.fat_target if target else 65
    cal_today = totals.get("calories", 0)

    lines += [
        "",
        f"📈 Hari ini: {fmt(cal_today)} / {fmt(cal_t)} kcal ({pct(cal_today, cal_t)})",
        (
            f"P: {fmt(totals.get('protein_g', 0))}/{fmt(p_t)}g"
            f" | K: {fmt(totals.get('carbs_g', 0))}/{fmt(k_t)}g"
            f" | L: {fmt(totals.get('fat_g', 0))}/{fmt(l_t)}g"
        ),
    ]

    if confidence == "low":
        lines += ["", "⚠️ Estimasi kasar (foto kurang jelas)"]
    if notes:
        lines.append(f"💬 {notes}")

    return "\n".join(lines)
