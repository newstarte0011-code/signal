"""Real-time listener for configured Telegram signal channels.

The listener stores new messages and observed edits in the shared SQLite
database through database.repository. It does not parse trading signals;
parsing is a separate pipeline stage.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timezone
from typing import Any

from telethon import events

from config.telegram_channels import CHANNELS, get_channel_reference, validate_channels
from database.repository import create_channel, mark_message_edited, save_raw_message
from telegram_client.client import create_telegram_client
from telegram_client.history_sync import resolve_channel_entity

logger = logging.getLogger("telegram_client.listener")


def _to_utc_iso(value: Any) -> str | None:
    """Convert a Telegram datetime to a UTC ISO-8601 string."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _message_record(message: Any) -> dict[str, Any]:
    """Convert a Telethon message into the repository's expected fields."""
    message_date = _to_utc_iso(getattr(message, "date", None))
    if message_date is None:
        raise ValueError(
            f"Telegram message {getattr(message, 'id', '<unknown>')} has no date."
        )

    reply_to_message_id = getattr(message, "reply_to_msg_id", None)
    if reply_to_message_id is None:
        reply_to = getattr(message, "reply_to", None)
        reply_to_message_id = getattr(reply_to, "reply_to_msg_id", None)

    return {
        "telegram_message_id": int(message.id),
        "message_date": message_date,
        "text": getattr(message, "message", None) or "",
        "edit_date": _to_utc_iso(getattr(message, "edit_date", None)),
        "has_media": getattr(message, "media", None) is not None,
        "reply_to_message_id": reply_to_message_id,
    }


async def _prepare_channels(client, channel_configs: list[dict]) -> list[dict]:
    """Resolve configured channels and ensure their database rows exist."""
    validate_channels(channel_configs)
    prepared: list[dict] = []

    for channel_config in channel_configs:
        reference = get_channel_reference(channel_config)
        entity = await resolve_channel_entity(client, reference)
        telegram_id = getattr(entity, "id", None)
        if telegram_id is None:
            raise RuntimeError(
                f"Resolved Telegram channel has no ID: {reference!r}"
            )

        title = (
            getattr(entity, "title", None)
            or channel_config.get("name")
            or str(reference)
        )
        username = getattr(entity, "username", None) or channel_config.get("username")
        db_channel_id = create_channel(
            title=title,
            username=username,
            telegram_id=int(telegram_id),
        )
        prepared.append(
            {
                "config": channel_config,
                "reference": reference,
                "entity": entity,
                "telegram_id": int(telegram_id),
                "db_channel_id": db_channel_id,
                "title": title,
            }
        )
        logger.info(
            "Listener channel ready: title=%s telegram_id=%s db_channel_id=%s",
            title,
            telegram_id,
            db_channel_id,
        )

    return prepared


async def run_listener(
    client=None,
    channel_configs: list[dict] | None = None,
    run_until_disconnected: bool = True,
) -> None:
    """Start listening for new messages and edits on configured channels.

    Args:
        client: Optional connected or connectable Telethon client. If omitted,
            create_telegram_client() is used.
        channel_configs: Optional channel configuration list; defaults to
            config.telegram_channels.CHANNELS.
        run_until_disconnected: If True, wait for Telegram disconnection.
            Set False when embedding the listener in another async service.
    """
    own_client = client is None
    if client is None:
        client = create_telegram_client()

    configs = CHANNELS if channel_configs is None else channel_configs
    if not configs:
        raise ValueError("No Telegram channels are configured.")

    try:
        await client.start()
        prepared_channels = await _prepare_channels(client, configs)

        if not prepared_channels:
            raise ValueError("No Telegram channels could be prepared.")

        for channel_info in prepared_channels:
            entity = channel_info["entity"]
            db_channel_id = channel_info["db_channel_id"]
            channel_title = channel_info["title"]
            telegram_channel_id = channel_info["telegram_id"]

            async def on_new_message(event, *, _db_id=db_channel_id,
                                     _title=channel_title,
                                     _telegram_id=telegram_channel_id):
                message = event.message
                try:
                    record = _message_record(message)
                    save_raw_message(
                        channel_id=_db_id,
                        telegram_message_id=record["telegram_message_id"],
                        message_date=record["message_date"],
                        text=record["text"],
                        edit_date=record["edit_date"],
                        has_media=record["has_media"],
                        reply_to_message_id=record["reply_to_message_id"],
                    )
                    logger.info(
                        "New Telegram message saved: channel=%s telegram_id=%s "
                        "message_id=%s",
                        _title,
                        _telegram_id,
                        message.id,
                    )
                except Exception:
                    logger.exception(
                        "Failed to save new message: channel=%s message_id=%s",
                        _title,
                        getattr(message, "id", None),
                    )

            async def on_message_edited(event, *, _db_id=db_channel_id,
                                        _title=channel_title,
                                        _telegram_id=telegram_channel_id):
                message = event.message
                try:
                    record = _message_record(message)
                    save_raw_message(
                        channel_id=_db_id,
                        telegram_message_id=record["telegram_message_id"],
                        message_date=record["message_date"],
                        text=record["text"],
                        edit_date=record["edit_date"],
                        has_media=record["has_media"],
                        reply_to_message_id=record["reply_to_message_id"],
                    )
                    # Explicitly retain the edited status even if Telegram's
                    # edit changed metadata but not the message text.
                    try:
                        mark_message_edited(
                            channel_id=_db_id,
                            telegram_message_id=record["telegram_message_id"],
                        )
                    except ValueError:
                        # A rare edit event may arrive before the corresponding
                        # new-message event; save_raw_message above normally
                        # creates the row, so this is logged only as a warning.
                        logger.warning(
                            "Could not mark edited message: channel=%s message_id=%s",
                            _title,
                            message.id,
                        )
                    logger.info(
                        "Edited Telegram message saved: channel=%s telegram_id=%s "
                        "message_id=%s",
                        _title,
                        _telegram_id,
                        message.id,
                    )
                except Exception:
                    logger.exception(
                        "Failed to save edited message: channel=%s message_id=%s",
                        _title,
                        getattr(message, "id", None),
                    )

            client.add_event_handler(
                on_new_message,
                events.NewMessage(chats=entity),
            )
            client.add_event_handler(
                on_message_edited,
                events.MessageEdited(chats=entity),
            )

        logger.info(
            "Telegram listener started for %s channel(s).",
            len(prepared_channels),
        )

        if run_until_disconnected:
            await client.run_until_disconnected()

    except asyncio.CancelledError:
        logger.info("Telegram listener cancellation requested.")
        raise
    finally:
        if own_client and client.is_connected():
            await client.disconnect()


async def main() -> None:
    """Command-line entry point."""
    await run_listener()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(main())
