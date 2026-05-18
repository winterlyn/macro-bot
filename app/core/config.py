"""
app/core/config.py — Application settings via pydantic-settings.
All values loaded from environment variables / .env file.
"""

from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


# Timezone constant — used throughout the app
WITA = ZoneInfo("Asia/Makassar")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Gemini ────────────────────────────────────────────────────────────
    gemini_api_key: str

    # ── Telegram ──────────────────────────────────────────────────────────
    telegram_bot_token: str
    telegram_webhook_secret: str
    my_telegram_user_id: int

    # ── Railway / Deployment ──────────────────────────────────────────────
    railway_public_url: str = ""
    port: int = 8000

    # ── Database ──────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./macro_bot.db"


settings = Settings()
