import os
from dataclasses import dataclass

from dotenv import load_dotenv

from config.settings import BASE_DIR


load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class TelegramSettings:
    api_id: int
    api_hash: str
    session_name: str


def load_telegram_settings() -> TelegramSettings:
    """Load and validate Telegram API settings without exposing secrets."""
    raw_api_id = os.getenv("TELEGRAM_API_ID", "").strip()
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
    session_name = os.getenv(
        "TELEGRAM_SESSION_NAME",
        "signal_analyzer",
    ).strip()

    if not raw_api_id:
        raise ValueError("TELEGRAM_API_ID is missing from .env")

    try:
        api_id = int(raw_api_id)
    except ValueError as exc:
        raise ValueError(
            "TELEGRAM_API_ID must be an integer."
        ) from exc

    if api_id <= 0:
        raise ValueError("TELEGRAM_API_ID must be positive.")

    if not api_hash:
        raise ValueError("TELEGRAM_API_HASH is missing from .env")

    if not session_name:
        raise ValueError("TELEGRAM_SESSION_NAME cannot be empty.")

    if any(char in session_name for char in ("/", "\\", ":")):
        raise ValueError(
            "TELEGRAM_SESSION_NAME must be a simple filename."
        )

    return TelegramSettings(
        api_id=api_id,
        api_hash=api_hash,
        session_name=session_name,
    )
