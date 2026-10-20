"""Live Telegram monitor with initial history sync and periodic recovery."""

import asyncio
import logging
from datetime import timezone

from telethon import events

from config.telegram_channels import CHANNELS, get_channel_reference
from database.repository import (
    create_channel,
    mark_message_edited,
    save_raw_messages_batch,
)
from telegram_client.client import create_telegram_client
from telegram_client.history_sync import (
    resolve_channel_entity,
    sync_channel_history,
    to_utc_iso,
)

logger = logging.getLogger("telegram_client.monitor")

INITIAL_HISTORY_LIMIT = 500
RECONCILE_INTERVAL_SECONDS = 15 * 60
BATCH_SIZE = 250


def _message_payload(message) -> dict:
    """Convert a Telethon message to the repository's raw-message format."""
    message_date = getattr(message, "date", None)

    if message_date is None:
        message_date = message.date

    if message_date.tzinfo is None:
        message_date = message_date.replace(tzinfo=timezone.utc)

    reply_to_message_id = getattr(message, "reply_to_msg_id", None)

    if reply_to_message_id is None:
        reply_to_message_id = getattr(
            getattr(message, "reply_to", None),
            "reply_to_msg_id",
            None,
        )

    return {
        "telegram_message_id": message.id,
        "message_date": to_utc_iso(message_date),
        "text": getattr(message, "message", None) or "",
        "edit_date": (
            to_utc_iso(message.edit_date)
            if getattr(message, "edit_date", None)
            else None
        ),
        "has_media": getattr(message, "media", None) is not None,
        "reply_to_message_id": reply_to_message_id,
    }


async def run_monitor() -> None:
    """Synchronize configured channels and monitor new messages and edits."""
    if not CHANNELS:
        raise RuntimeError("No Telegram channels configured in CHANNELS.")

    client = create_telegram_client()
    channel_entities = {}
    channel_db_ids = {}

    try:
        await client.start()

        if not await client.is_user_authorized():
            raise RuntimeError(
                "Telegram session is not authorized. "
                "Check the existing session before running the monitor."
            )

        # Resolve all configured channels before registering event handlers.
        for channel in CHANNELS:
            reference = get_channel_reference(channel)
            entity = await resolve_channel_entity(client, channel)

            telegram_channel_id = entity.id
            title = (
                getattr(entity, "title", None)
                or channel.get("name")
                or str(reference)
            )

            db_channel_id = create_channel(
                title=title,
                username=getattr(entity, "username", None),
                telegram_id=telegram_channel_id,
            )

            channel_entities[telegram_channel_id] = entity
            channel_db_ids[telegram_channel_id] = db_channel_id

            logger.info(
                "Configured channel: name=%s telegram_id=%s db_id=%s",
                title,
                telegram_channel_id,
                db_channel_id,
            )

        async def save_event_message(event, edited: bool = False):
            message = event.message
            chat = await event.get_chat()

            if chat is None:
                logger.warning(
                    "Ignoring Telegram event without a resolved chat."
                )
                return

            telegram_channel_id = getattr(chat, "id", None)

            if telegram_channel_id not in channel_db_ids:
                logger.warning(
                    "Ignoring event from an unconfigured channel: %s",
                    telegram_channel_id,
                )
                return

            db_channel_id = channel_db_ids[telegram_channel_id]

            # Save through the existing idempotent repository/version logic.
            save_raw_messages_batch(
                db_channel_id,
                [_message_payload(message)],
            )

            if edited:
                mark_message_edited(
                    db_channel_id,
                    message.id,
                )

            logger.info(
                "Telegram message %s: channel_id=%s message_id=%s",
                "edited" if edited else "received",
                telegram_channel_id,
                message.id,
            )

        async def on_new_message(event):
            try:
                await save_event_message(event, edited=False)
            except Exception:
                logger.exception("Failed to save a new Telegram message.")

        async def on_message_edited(event):
            try:
                await save_event_message(event, edited=True)
            except Exception:
                logger.exception("Failed to save an edited Telegram message.")

        # Register listeners before history sync so new messages arriving
        # during initial synchronization are not missed. Duplicate writes
        # are handled by the repository.
        entities = list(channel_entities.values())

        client.add_event_handler(
            on_new_message,
            events.NewMessage(chats=entities),
        )
        client.add_event_handler(
            on_message_edited,
            events.MessageEdited(chats=entities),
        )

        logger.info("Live Telegram handlers registered.")

        # Initial history synchronization for each configured channel.
        for channel in CHANNELS:
            reference = get_channel_reference(channel)

            try:
                result = await sync_channel_history(
                    client,
                    channel,
                    limit=INITIAL_HISTORY_LIMIT,
                    batch_size=BATCH_SIZE,
                )
                logger.info("Initial sync result: %s", result)
            except Exception:
                logger.exception(
                    "Initial history sync failed for channel %s.",
                    reference,
                )

        logger.info(
            "Monitor running. Reconciliation interval: %s seconds.",
            RECONCILE_INTERVAL_SECONDS,
        )

        # Periodically re-fetch recent history to recover recent messages
        # after a temporary connection interruption. Repository idempotency
        # prevents duplicate records and versions.
        while True:
            await asyncio.sleep(RECONCILE_INTERVAL_SECONDS)

            for channel in CHANNELS:
                reference = get_channel_reference(channel)

                try:
                    result = await sync_channel_history(
                        client,
                        channel,
                        limit=INITIAL_HISTORY_LIMIT,
                        batch_size=BATCH_SIZE,
                    )
                    logger.info("Reconciliation result: %s", result)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Periodic sync failed for channel %s.",
                        reference,
                    )

    finally:
        if client.is_connected():
            await client.disconnect()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    try:
        asyncio.run(run_monitor())
    except KeyboardInterrupt:
        print("Telegram monitor stopped.")