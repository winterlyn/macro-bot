"""
app/core/database.py — SQLAlchemy async models + CRUD operations.
Uses aiosqlite engine. All timestamps stored as UTC, displayed as WITA.
"""

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    delete,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import WITA, settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine & Session factory
# ---------------------------------------------------------------------------

engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class FoodLog(Base):
    __tablename__ = "food_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    update_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    meal_description: Mapped[str] = mapped_column(String(500))
    calories: Mapped[float] = mapped_column(Float)
    protein_g: Mapped[float] = mapped_column(Float)
    carbs_g: Mapped[float] = mapped_column(Float)
    fat_g: Mapped[float] = mapped_column(Float)
    fiber_g: Mapped[float] = mapped_column(Float)
    image_used: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_ai_response: Mapped[str] = mapped_column(Text)


class DailyTarget(Base):
    __tablename__ = "daily_targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calories_target: Mapped[float] = mapped_column(Float, default=2000.0)
    protein_target: Mapped[float] = mapped_column(Float, default=150.0)
    carbs_target: Mapped[float] = mapped_column(Float, default=200.0)
    fat_target: Mapped[float] = mapped_column(Float, default=65.0)
    fiber_target: Mapped[float] = mapped_column(Float, default=30.0)


# ---------------------------------------------------------------------------
# DB Initialisation
# ---------------------------------------------------------------------------


async def init_db() -> None:
    """Create all tables if they do not exist. Seed default daily target if empty."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(DailyTarget))
        if result.scalar_one_or_none() is None:
            session.add(DailyTarget(id=1))
            await session.commit()
            logger.info("Seeded default DailyTarget row.")


# ---------------------------------------------------------------------------
# Helper: WITA day boundaries → UTC
# ---------------------------------------------------------------------------


def _today_utc_range() -> tuple[datetime, datetime]:
    """Return (start_utc, end_utc) covering today in WITA timezone."""
    now_wita = datetime.now(WITA)
    start_wita = now_wita.replace(hour=0, minute=0, second=0, microsecond=0)
    end_wita = start_wita + timedelta(days=1)
    return start_wita.astimezone(timezone.utc), end_wita.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def is_duplicate_update(update_id: int) -> bool:
    """Return True if this Telegram update_id was already processed."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(FoodLog.id).where(FoodLog.update_id == update_id)
        )
        return result.scalar_one_or_none() is not None


async def save_food_log(
    ai_result: dict,
    *,
    image_used: bool,
    update_id: int,
) -> FoodLog:
    """Persist a food log entry from AI analysis result."""
    total = ai_result.get("total", {})
    foods = ai_result.get("foods_detected", [])
    description = ", ".join(f["name"] for f in foods) if foods else "Unknown"
    if len(description) > 500:
        description = description[:497] + "..."

    log = FoodLog(
        update_id=update_id,
        timestamp=datetime.now(timezone.utc),
        meal_description=description,
        calories=float(total.get("calories", 0)),
        protein_g=float(total.get("protein_g", 0)),
        carbs_g=float(total.get("carbs_g", 0)),
        fat_g=float(total.get("fat_g", 0)),
        fiber_g=float(total.get("fiber_g", 0)),
        image_used=image_used,
        raw_ai_response=json.dumps(ai_result, ensure_ascii=False),
    )

    async with AsyncSessionLocal() as session:
        session.add(log)
        await session.commit()
        await session.refresh(log)
    return log


async def get_today_totals() -> dict:
    """Sum all macros logged today (WITA). Returns dict with macro totals."""
    start_utc, end_utc = _today_utc_range()
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(
                func.sum(FoodLog.calories),
                func.sum(FoodLog.protein_g),
                func.sum(FoodLog.carbs_g),
                func.sum(FoodLog.fat_g),
                func.sum(FoodLog.fiber_g),
                func.count(FoodLog.id),
                func.max(FoodLog.timestamp),
                func.max(FoodLog.meal_description),
            ).where(
                FoodLog.timestamp >= start_utc,
                FoodLog.timestamp < end_utc,
            )
        )
        row = result.one()

    return {
        "calories": row[0] or 0.0,
        "protein_g": row[1] or 0.0,
        "carbs_g": row[2] or 0.0,
        "fat_g": row[3] or 0.0,
        "fiber_g": row[4] or 0.0,
        "entry_count": row[5] or 0,
        "last_timestamp": row[6],
        "last_description": row[7],
    }


async def get_today_logs() -> list[FoodLog]:
    """Return all FoodLog entries for today (WITA), ordered newest first."""
    start_utc, end_utc = _today_utc_range()
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(FoodLog)
            .where(FoodLog.timestamp >= start_utc, FoodLog.timestamp < end_utc)
            .order_by(FoodLog.timestamp.desc())
        )
        return list(result.scalars().all())


async def delete_last_today() -> FoodLog | None:
    """Delete the most recent food log entry for today. Returns deleted entry or None."""
    start_utc, end_utc = _today_utc_range()
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(FoodLog)
            .where(FoodLog.timestamp >= start_utc, FoodLog.timestamp < end_utc)
            .order_by(FoodLog.timestamp.desc())
            .limit(1)
        )
        log = result.scalar_one_or_none()
        if log:
            await session.delete(log)
            await session.commit()
    return log


async def delete_all_today() -> int:
    """Delete all food log entries for today. Returns count of deleted rows."""
    start_utc, end_utc = _today_utc_range()
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            delete(FoodLog).where(
                FoodLog.timestamp >= start_utc,
                FoodLog.timestamp < end_utc,
            )
        )
        await session.commit()
        return result.rowcount


async def get_history(days: int = 7) -> list[dict]:
    """Return per-day summary for the last `days` days (WITA)."""
    now_wita = datetime.now(WITA)
    results = []
    for i in range(days):
        day_wita = now_wita - timedelta(days=i)
        start_wita = day_wita.replace(hour=0, minute=0, second=0, microsecond=0)
        end_wita = start_wita + timedelta(days=1)
        start_utc = start_wita.astimezone(timezone.utc)
        end_utc = end_wita.astimezone(timezone.utc)

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(
                    func.sum(FoodLog.calories),
                    func.sum(FoodLog.protein_g),
                    func.sum(FoodLog.carbs_g),
                    func.sum(FoodLog.fat_g),
                    func.sum(FoodLog.fiber_g),
                    func.count(FoodLog.id),
                ).where(
                    FoodLog.timestamp >= start_utc,
                    FoodLog.timestamp < end_utc,
                )
            )
            row = result.one()

        results.append(
            {
                "date": start_wita.date(),
                "calories": row[0] or 0.0,
                "protein_g": row[1] or 0.0,
                "carbs_g": row[2] or 0.0,
                "fat_g": row[3] or 0.0,
                "fiber_g": row[4] or 0.0,
                "entry_count": row[5] or 0,
            }
        )
    return results


async def get_daily_target() -> DailyTarget:
    """Return the single DailyTarget row (always id=1)."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(DailyTarget).where(DailyTarget.id == 1))
        return result.scalar_one()


async def update_daily_target(
    calories: float,
    protein: float,
    carbs: float,
    fat: float,
    fiber: float = 30.0,
) -> DailyTarget:
    """Update the single DailyTarget row."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(DailyTarget).where(DailyTarget.id == 1))
        target = result.scalar_one()
        target.calories_target = calories
        target.protein_target = protein
        target.carbs_target = carbs
        target.fat_target = fat
        target.fiber_target = fiber
        await session.commit()
        await session.refresh(target)
    return target
