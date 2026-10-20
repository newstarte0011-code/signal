
from telethon import TelegramClient
from python_socks import ProxyType

from config.settings import BASE_DIR
from telegram_client.settings import load_telegram_settings


PROXY_HOST = "127.0.0.1"
PROXY_PORT = 10809


def create_telegram_client() -> TelegramClient:
    """Create a Telegram client routed through the local SOCKS5 proxy."""
    settings = load_telegram_settings()

    session_dir = BASE_DIR / "data" / "sessions"
    session_dir.mkdir(parents=True, exist_ok=True)

    session_path = session_dir / settings.session_name

    proxy = (
        ProxyType.SOCKS5,
        PROXY_HOST,
        PROXY_PORT,
    )

    return TelegramClient(
        str(session_path),
        settings.api_id,
        settings.api_hash,
        proxy=proxy,
        timeout=20,
        request_retries=3,
        connection_retries=3,
        retry_delay=2,
        auto_reconnect=True,
    )
