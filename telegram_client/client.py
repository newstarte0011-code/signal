"""Telegram client construction and connection settings."""

import os
from pathlib import Path

from telethon import TelegramClient
from python_socks import ProxyType

from config.settings import BASE_DIR
from telegram_client.settings import load_telegram_settings


DEFAULT_PROXY_HOST = "127.0.0.1"
DEFAULT_PROXY_PORT = 10809
DEFAULT_CONNECTION_TIMEOUT = 20
DEFAULT_CONNECTION_RETRIES = 3
DEFAULT_REQUEST_RETRIES = 3
DEFAULT_RETRY_DELAY = 2


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean environment variable with validation."""
    value = os.getenv(name)

    if value is None or not value.strip():
        return default

    normalized = value.strip().lower()

    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False

    raise ValueError(
        f"{name} must be one of: true/false, yes/no, 1/0, on/off."
    )


def _build_proxy():
    """
    Build the Telethon proxy tuple.

    Proxy settings are configurable through environment variables:
      TELEGRAM_PROXY_ENABLED (default: true)
      TELEGRAM_PROXY_HOST (default: 127.0.0.1)
      TELEGRAM_PROXY_PORT (default: 10809)
      TELEGRAM_PROXY_TYPE (default: socks5; supported: socks5, socks4, http)

    The defaults preserve the project's existing local SOCKS5 proxy setup.
    Return None when the proxy is explicitly disabled.
    """
    if not _env_bool("TELEGRAM_PROXY_ENABLED", True):
        return None

    host = os.getenv(
        "TELEGRAM_PROXY_HOST",
        DEFAULT_PROXY_HOST,
    ).strip()

    raw_port = os.getenv(
        "TELEGRAM_PROXY_PORT",
        str(DEFAULT_PROXY_PORT),
    ).strip()

    proxy_type_name = os.getenv(
        "TELEGRAM_PROXY_TYPE",
        "socks5",
    ).strip().lower()

    if not host:
        raise ValueError("TELEGRAM_PROXY_HOST cannot be empty.")

    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("TELEGRAM_PROXY_PORT must be an integer.") from exc

    if not 1 <= port <= 65535:
        raise ValueError("TELEGRAM_PROXY_PORT must be between 1 and 65535.")

    proxy_types = {
        "socks5": ProxyType.SOCKS5,
        "socks4": ProxyType.SOCKS4,
        "http": ProxyType.HTTP,
    }

    if proxy_type_name not in proxy_types:
        allowed = ", ".join(sorted(proxy_types))
        raise ValueError(
            f"Unsupported TELEGRAM_PROXY_TYPE: {proxy_type_name!r}. "
            f"Supported types: {allowed}."
        )

    return (
        proxy_types[proxy_type_name],
        host,
        port,
    )


def create_telegram_client() -> TelegramClient:
    """
    Create a configured Telethon client.

    API credentials and the session name are loaded from the project's
    Telegram settings. The session database is stored under data/sessions.
    By default, the client uses the existing local SOCKS5 proxy at
    127.0.0.1:10809. Proxy configuration can be overridden with environment
    variables, or disabled explicitly using TELEGRAM_PROXY_ENABLED=false.
    """
    settings = load_telegram_settings()

    session_dir: Path = BASE_DIR / "data" / "sessions"
    session_dir.mkdir(parents=True, exist_ok=True)

    session_path = session_dir / settings.session_name
    proxy = _build_proxy()

    return TelegramClient(
        str(session_path),
        settings.api_id,
        settings.api_hash,
        proxy=proxy,
        timeout=DEFAULT_CONNECTION_TIMEOUT,
        request_retries=DEFAULT_REQUEST_RETRIES,
        connection_retries=DEFAULT_CONNECTION_RETRIES,
        retry_delay=DEFAULT_RETRY_DELAY,
        auto_reconnect=True,
    )
