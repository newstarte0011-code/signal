"""Telegram channel history synchronization.

Fetches recent Telegram messages and persists them to the central SQLite
database through the repository layer.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from telethon import utils

from config.telegram_channels import get_channel_reference
from database.repository import create_channel, save_raw_messages_batch

logger = logging.getLogger("telegram_client.history_sync")


def to_utc_iso(value: datetime) -> str:
    """Convert a datetime to a UTC ISO-8601 string."""
    if not isinstance(value, datetime):
        raise TypeError("value must be a datetime instance.")

    if value.tzinfo is None:
        # Telegram normally returns timezone-aware datetimes. Treat a naive
        # datetime as UTC so persisted timestamps remain consistent.
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc).isoformat()


def _numeric_channel_id(value: Any) -> int | None:
    """Return a numeric channel ID when the reference is numeric."""
    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value

    if isinstance(value, str):
        value = value.strip()
        if value.lstrip("-").isdigit():
            return int(value)

    return None


async def resolve_channel_entity(client, channel_reference):
    """
    Resolve a channel from a username, numeric ID, or channel config dict.

    Numeric IDs are resolved against the current Telegram dialogs first,
    allowing channels without public usernames to be found when the logged-in
    account can access them.
    """
    if isinstance(channel_reference, dict):
        channel_reference = get_channel_reference(channel_reference)

    numeric_id = _numeric_channel_id(channel_reference)

    if numeric_id is None:
        reference = str(channel_reference).strip().lstrip("@")
        if not reference:
            raise ValueError("Telegram channel reference cannot be empty.")

        return await client.get_entity(reference)

    # Telegram marked channel IDs can be written as -1001234567890.
    target_ids = {numeric_id}
    if numeric_id < 0:
        marked = str(abs(numeric_id))
        if marked.startswith("100") and len(marked) > 3:
            target_ids.add(int(marked[3:]))

    # Search dialogs first, as the session may already know the channel's
    # access hash even when only its numeric ID is configured.
    try:
        async for dialog in client.iter_dialogs():
            entity = getattr(dialog, "entity", None)
            if entity is None:
                continue

            entity_id = getattr(entity, "id", None)
            try:
                marked_id = utils.get_peer_id(entity)
            except (TypeError, ValueError):
                marked_id = None

            if entity_id in target_ids or marked_id == numeric_id:
                return entity

    except Exception:
        logger.debug(
            "Could not resolve channel ID %s through dialogs.",
            numeric_id,
            exc_info=True,
        )

    # Final attempt: Telethon may already have the entity/access hash cached.
    try:
        entity = await client.get_entity(numeric_id)

        if getattr(entity, "id", None) in target_ids:
            return entity

        try:
            if utils.get_peer_id(entity) == numeric_id:
                return entity
        except (TypeError, ValueError):
            pass

    except Exception as exc:
        raise RuntimeError(
            f"Could not resolve Telegram channel ID {numeric_id}. "
            "Check that the logged-in account can access the channel and "
            "that the channel ID is correct. If possible, open the channel "
            "in Telegram with this account first so its entity is cached."
        ) from exc

    raise RuntimeError(
        "Telegram returned an entity that does not match channel ID "
        f"{numeric_id}."
    )


def _message_to_record(message) -> dict[str, Any] | None:
    """Convert one Telethon message into the repository's input format."""
    message_id = getattr(message, "id", None)
    message_date = getattr(message, "date", None)

    if not isinstance(message_id, int) or isinstance(message_id, bool) or message_id <= 0:
        logger.warning(
            "Skipping Telegram message with invalid ID: %r",
            message_id,
        )
        return None

    if message_date is None:
        logger.warning(
            "Skipping Telegram message %s: missing message date.",
            message_id,
        )
        return None

    reply_to_message_id = getattr(message, "reply_to_msg_id", None)
    if reply_to_message_id is None:
        reply_to = getattr(message, "reply_to", None)
        reply_to_message_id = getattr(reply_to, "reply_to_msg_id", None)

    edit_date = getattr(message, "edit_date", None)

    return {
        "telegram_message_id": message_id,
        "message_date": to_utc_iso(message_date),
        "text": getattr(message, "message", None) or "",
        "edit_date": to_utc_iso(edit_date) if edit_date else None,
        "has_media": getattr(message, "media", None) is not None,
        "reply_to_message_id": reply_to_message_id,
    }


async def sync_channel_history(
    client,
    channel_reference,
    limit: int = 30,
    batch_size: int = 250,
) -> dict[str, Any]:
    """
    Fetch the most recent messages from one channel and save them in batches.

    Existing messages are also passed to the repository. The repository is
    responsible for deduplication and message-version tracking.

    Args:
        client: Connected Telethon client.
        channel_reference: Telegram username, numeric ID, or channel config.
        limit: Maximum number of Telegram messages to inspect.
        batch_size: Number of messages to write per database transaction.

    Returns:
        A summary containing channel IDs, title, and processing counts.
    """
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise TypeError("limit must be an integer.")
    if not 1 <= limit <= 10000:
        raise ValueError("limit must be between 1 and 10000.")

    if not isinstance(batch_size, int) or isinstance(batch_size, bool):
        raise TypeError("batch_size must be an integer.")
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000.")

    entity = await resolve_channel_entity(client, channel_reference)

    telegram_channel_id = getattr(entity, "id", None)
    if (
        not isinstance(telegram_channel_id, int)
        or isinstance(telegram_channel_id, bool)
    ):
        raise RuntimeError(
            f"Telegram entity has no valid ID: {channel_reference!r}"
        )

    title = (
        getattr(entity, "title", None)
        or getattr(entity, "first_name", None)
        or str(channel_reference)
    )
    username = getattr(entity, "username", None)

    db_channel_id = create_channel(
        title=title,
        username=username,
        telegram_id=telegram_channel_id,
    )

    processed = 0
    skipped = 0
    batches_saved = 0
    batch: list[dict[str, Any]] = []

    async for message in client.iter_messages(entity, limit=limit):
        record = _message_to_record(message)
        if record is None:
            skipped += 1
            continue

        batch.append(record)

        if len(batch) >= batch_size:
            save_raw_messages_batch(db_channel_id, batch)
            processed += len(batch)
            batches_saved += 1
            batch = []

    if batch:
        save_raw_messages_batch(db_channel_id, batch)
        processed += len(batch)
        batches_saved += 1

    result = {
        "channel_db_id": db_channel_id,
        "telegram_channel_id": telegram_channel_id,
        "channel_title": title,
        "processed": processed,
        "skipped": skipped,
        "batches_saved": batches_saved,
    }

    logger.info(
        "History sync completed: channel=%s telegram_id=%s "
        "processed=%s skipped=%s batches=%s",
        title,
        telegram_channel_id,
        processed,
        skipped,
        batches_saved,
    )

    return result
