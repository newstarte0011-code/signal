"""Export the latest 500 Telegram messages from each configured channel.

Save as: tests/extract_telegram_500.py
Run from the project root:
    python tests/extract_telegram_500.py

Creates one JSON file per configured channel in:
    data/json exports/
The file name is based on the channel's configured name. This script only reads
Telegram and writes JSON; it does not modify the project's SQLite database.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.telegram_channels import CHANNELS  # noqa: E402
from telegram_client.client import create_telegram_client  # noqa: E402

LIMIT_PER_CHANNEL = 500
OUTPUT_DIR = PROJECT_ROOT / "signal_analyzer" / "data" / "json exports"


def iso(value: Any) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def json_safe(value: Any) -> Any:
    """Convert Telethon values into JSON-safe values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    return str(value)


def channel_reference(channel: dict[str, Any]) -> Any:
    """Prefer public username; otherwise use configured Telegram ID."""
    username = channel.get("username")
    if username:
        return str(username).lstrip("@")
    telegram_id = channel.get("telegram_id")
    if telegram_id is not None:
        return int(telegram_id)
    raise ValueError(
        f"Channel entry has neither username nor telegram_id: {channel!r}"
    )


def channel_label(channel: dict[str, Any]) -> str:
    return str(
        channel.get("name")
        or channel.get("username")
        or channel.get("telegram_id")
        or "channel"
    ).strip()


def safe_filename(value: str) -> str:
    """Keep channel names (including Persian letters/spaces), remove Windows-invalid chars."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    # Windows reserves these device names even when they have a file extension.
    if cleaned.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        cleaned = f"_{cleaned}"
    return cleaned or "channel"


def output_path_for(channel: dict[str, Any], used_names: set[str]) -> Path:
    base = safe_filename(channel_label(channel))
    candidate = base
    # Avoid overwriting another configured channel if two entries share a name.
    if candidate.casefold() in used_names:
        suffix = channel.get("username") or channel.get("telegram_id") or "duplicate"
        candidate = f"{base}_{safe_filename(str(suffix))}"
    used_names.add(candidate.casefold())
    return OUTPUT_DIR / f"{candidate}.json"


async def export_channel(client, config: dict[str, Any]) -> dict[str, Any]:
    reference = channel_reference(config)
    label = channel_label(config)
    print(f"\n[FETCH] {label} — up to {LIMIT_PER_CHANNEL} messages")

    entity = await client.get_entity(reference)
    channel_id = getattr(entity, "id", None)
    title = getattr(entity, "title", None) or label
    username = getattr(entity, "username", None) or config.get("username")

    messages: list[dict[str, Any]] = []
    async for message in client.iter_messages(entity, limit=LIMIT_PER_CHANNEL):
        reply = getattr(message, "reply_to", None)
        media = getattr(message, "media", None)
        message_id = getattr(message, "id", None)
        messages.append({
            "telegram_message_id": message_id,
            "date_utc": iso(getattr(message, "date", None)),
            "edit_date_utc": iso(getattr(message, "edit_date", None)),
            "text": getattr(message, "message", None) or "",
            "raw_text": getattr(message, "raw_text", None) or "",
            "sender_id": getattr(message, "sender_id", None),
            "reply_to_message_id": getattr(reply, "reply_to_msg_id", None) if reply else None,
            "grouped_id": getattr(message, "grouped_id", None),
            "has_media": media is not None,
            "media_type": type(media).__name__ if media is not None else None,
            "views": getattr(message, "views", None),
            "forwards": getattr(message, "forwards", None),
            "post_author": getattr(message, "post_author", None),
            "entities": json_safe(getattr(message, "entities", None)),
            "message_link": f"https://t.me/{username}/{message_id}" if username and message_id else None,
        })

    return {
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "channel_config_name": config.get("name"),
        "channel_username": username,
        "channel_telegram_id": channel_id,
        "channel_title": title,
        "requested_limit": LIMIT_PER_CHANNEL,
        "exported_count": len(messages),
        "order": "newest_first",
        "messages": messages,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def main() -> int:
    if not CHANNELS:
        print("ERROR: config.telegram_channels.CHANNELS is empty.")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    client = create_telegram_client()
    failures = 0
    used_names: set[str] = set()

    try:
        await client.start()
        if not await client.is_user_authorized():
            print("ERROR: Telegram session is not authorized. Run the project's login flow first.")
            return 1

        print(f"Configured channels: {len(CHANNELS)}")
        print(f"Output directory: {OUTPUT_DIR}")

        for config in CHANNELS:
            label = channel_label(config)
            output_file = output_path_for(config, used_names)
            try:
                result = await export_channel(client, config)
                write_json(output_file, result)
                print(f"[OK] {label}: {result['exported_count']} messages -> {output_file.name}")
            except Exception as exc:
                failures += 1
                logging.exception("Failed to export channel %s", label)
                # Write a per-channel error file too, so each configured channel
                # always has its own JSON output and failures are easy to identify.
                write_json(output_file, {
                    "exported_at_utc": datetime.now(timezone.utc).isoformat(),
                    "channel_config_name": config.get("name"),
                    "channel_username": config.get("username"),
                    "channel_telegram_id": config.get("telegram_id"),
                    "requested_limit": LIMIT_PER_CHANNEL,
                    "exported_count": 0,
                    "messages": [],
                    "error": f"{type(exc).__name__}: {exc}",
                })
                print(f"[FAILED] {label}: {type(exc).__name__}: {exc} -> {output_file.name}")

        print("\n========== EXPORT SUMMARY ==========")
        print(f"Configured channels: {len(CHANNELS)}")
        print(f"JSON files written: {len(CHANNELS)}")
        print(f"Failed channel exports: {failures}")
        print(f"Folder: {OUTPUT_DIR}")
        if failures:
            print("Open the JSON file for each failed channel to inspect its error field.")
            return 2
        print("Export completed. One JSON file per configured channel; SQLite was not modified.")
        return 0
    finally:
        if client.is_connected():
            await client.disconnect()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nExport cancelled by user.")
        raise SystemExit(130)
