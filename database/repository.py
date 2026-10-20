import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from database.connection import database_connection, database_transaction

logger = logging.getLogger("database.repository")


def utc_now() -> str:
    """Return the current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def hash_text(text: Optional[str]) -> str:
    """Return a stable SHA-256 hash for message text."""
    normalized_text = text if text is not None else ""
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def create_channel(
    title: str,
    username: Optional[str] = None,
    telegram_id: Optional[int] = None,
    database_path: Optional[Path] = None,
) -> int:
    """Create a channel or update an existing channel."""
    if not title or not title.strip():
        raise ValueError("Channel title cannot be empty.")
    if telegram_id is None and not username:
        raise ValueError("Either telegram_id or username is required.")

    now = utc_now()
    normalized_username = username.lstrip("@") if username else None

    with database_transaction(database_path) as connection:
        existing = None

        if telegram_id is not None:
            existing = connection.execute(
                "SELECT id FROM channels WHERE telegram_id = ?",
                (telegram_id,),
            ).fetchone()

        if existing is None and normalized_username:
            existing = connection.execute(
                """
                SELECT id FROM channels
                WHERE LOWER(username) = LOWER(?)
                """,
                (normalized_username,),
            ).fetchone()

        if existing is not None:
            channel_id = int(existing["id"])
            connection.execute(
                """
                UPDATE channels
                SET
                    telegram_id = COALESCE(?, telegram_id),
                    username = COALESCE(?, username),
                    title = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    telegram_id,
                    normalized_username,
                    title.strip(),
                    now,
                    channel_id,
                ),
            )
            logger.debug("Channel updated: id=%s", channel_id)
            return channel_id

        cursor = connection.execute(
            """
            INSERT INTO channels (
                telegram_id, username, title,
                first_seen_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                telegram_id,
                normalized_username,
                title.strip(),
                now,
                now,
                now,
            ),
        )
        channel_id = int(cursor.lastrowid)

    logger.info("Channel created: id=%s", channel_id)
    return channel_id


def get_channel(
    channel_id: int,
    database_path: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    """Retrieve a channel by its database ID."""
    with database_connection(database_path) as connection:
        row = connection.execute(
            "SELECT * FROM channels WHERE id = ?",
            (channel_id,),
        ).fetchone()
    return dict(row) if row else None


def list_channels(
    active_only: bool = False,
    database_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """List channels ordered by ID."""
    query = "SELECT * FROM channels"
    if active_only:
        query += " WHERE is_active = 1"
    query += " ORDER BY id"

    with database_connection(database_path) as connection:
        rows = connection.execute(query).fetchall()
    return [dict(row) for row in rows]



def _ensure_reply_to_message_column(connection) -> None:
    """Apply the additive migration needed to retain Telegram reply links.

    Safe for existing databases: it only adds the nullable column when absent.
    The caller must already be inside a transaction.
    """
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(raw_messages)").fetchall()
    }
    if not columns:
        raise RuntimeError(
            "The raw_messages table does not exist. Initialize the database schema first."
        )
    if "reply_to_message_id" not in columns:
        connection.execute(
            "ALTER TABLE raw_messages ADD COLUMN reply_to_message_id INTEGER"
        )
        logger.info("Database migration applied: raw_messages.reply_to_message_id")

def _validate_message(
    telegram_message_id: int,
    message_date: str,
) -> None:
    if telegram_message_id <= 0:
        raise ValueError("telegram_message_id must be positive.")
    if not message_date:
        raise ValueError("message_date cannot be empty.")


def _save_raw_message_in_connection(
    connection,
    channel_id: int,
    telegram_message_id: int,
    message_date: str,
    text: Optional[str],
    edit_date: Optional[str],
    has_media: bool,
    reply_to_message_id: Optional[int] = None,
) -> int:
    """Insert/update one message using an already-open transaction."""
    content_hash = hash_text(text)
    now = utc_now()

    existing = connection.execute(
        """
        SELECT id, content_hash
        FROM raw_messages
        WHERE channel_id = ? AND telegram_message_id = ?
        """,
        (channel_id, telegram_message_id),
    ).fetchone()

    if existing is None:
        cursor = connection.execute(
            """
            INSERT INTO raw_messages (
                channel_id, telegram_message_id,
                message_date, collected_at, text,
                edit_date, content_hash, has_media, reply_to_message_id,
                collection_status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'collected', ?, ?)
            """,
            (
                channel_id,
                telegram_message_id,
                message_date,
                now,
                text,
                edit_date,
                content_hash,
                int(has_media),
                reply_to_message_id,
                now,
                now,
            ),
        )
        raw_message_id = int(cursor.lastrowid)

        connection.execute(
            """
            INSERT INTO message_versions (
                raw_message_id, version_number,
                text, content_hash, edit_date, observed_at
            )
            VALUES (?, 1, ?, ?, ?, ?)
            """,
            (raw_message_id, text, content_hash, edit_date, now),
        )
        logger.debug("Raw message inserted: id=%s", raw_message_id)
        return raw_message_id

    raw_message_id = int(existing["id"])

    if existing["content_hash"] == content_hash:
        connection.execute(
            """
            UPDATE raw_messages
            SET
                edit_date = COALESCE(?, edit_date),
                has_media = MAX(has_media, ?),
                reply_to_message_id = COALESCE(?, reply_to_message_id),
                updated_at = ?
            WHERE id = ?
            """,
            (edit_date, int(has_media), reply_to_message_id, now, raw_message_id),
        )
        return raw_message_id

    latest = connection.execute(
        """
        SELECT COALESCE(MAX(version_number), 0) AS version_number
        FROM message_versions
        WHERE raw_message_id = ?
        """,
        (raw_message_id,),
    ).fetchone()
    next_version = int(latest["version_number"]) + 1

    connection.execute(
        """
        INSERT INTO message_versions (
            raw_message_id, version_number,
            text, content_hash, edit_date, observed_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            raw_message_id,
            next_version,
            text,
            content_hash,
            edit_date,
            now,
        ),
    )

    connection.execute(
        """
        UPDATE raw_messages
        SET
            text = ?,
            edit_date = ?,
            content_hash = ?,
            has_media = MAX(has_media, ?),
            reply_to_message_id = COALESCE(?, reply_to_message_id),
            collection_status = 'edited',
            updated_at = ?
        WHERE id = ?
        """,
        (
            text,
            edit_date,
            content_hash,
            int(has_media),
            reply_to_message_id,
            now,
            raw_message_id,
        ),
    )
    logger.debug(
        "Message version recorded: id=%s, version=%s",
        raw_message_id,
        next_version,
    )
    return raw_message_id


def save_raw_messages_batch(
    channel_id: int,
    messages: Sequence[dict[str, Any]],
    database_path: Optional[Path] = None,
) -> list[int]:
    """
    Save multiple Telegram messages in one connection and transaction.

    Each item must contain telegram_message_id, message_date and text.
    Optional keys: edit_date and has_media.
    The batch is atomic: if any item fails, the entire batch rolls back.
    """
    if not messages:
        return []

    prepared = []
    for item in messages:
        if not isinstance(item, dict):
            raise TypeError("Each message in a batch must be a dictionary.")

        telegram_message_id = item.get("telegram_message_id")
        message_date = item.get("message_date")
        _validate_message(telegram_message_id, message_date)

        prepared.append(
            {
                "telegram_message_id": telegram_message_id,
                "message_date": message_date,
                "text": item.get("text"),
                "edit_date": item.get("edit_date"),
                "has_media": bool(item.get("has_media", False)),
                "reply_to_message_id": item.get("reply_to_message_id"),
            }
        )

    saved_ids: list[int] = []
    with database_transaction(database_path) as connection:
        channel = connection.execute(
            "SELECT id FROM channels WHERE id = ?",
            (channel_id,),
        ).fetchone()
        if channel is None:
            raise ValueError(f"Unknown channel_id: {channel_id}")

        _ensure_reply_to_message_column(connection)

        for item in prepared:
            saved_ids.append(
                _save_raw_message_in_connection(
                    connection=connection,
                    channel_id=channel_id,
                    telegram_message_id=item["telegram_message_id"],
                    message_date=item["message_date"],
                    text=item["text"],
                    edit_date=item["edit_date"],
                    has_media=item["has_media"],
                    reply_to_message_id=item["reply_to_message_id"],
                )
            )

    logger.info(
        "Message batch saved: channel_id=%s, processed=%s",
        channel_id,
        len(saved_ids),
    )
    return saved_ids


def save_raw_message(
    channel_id: int,
    telegram_message_id: int,
    message_date: str,
    text: Optional[str],
    edit_date: Optional[str] = None,
    has_media: bool = False,
    database_path: Optional[Path] = None,
    reply_to_message_id: Optional[int] = None,
) -> int:
    """Backward-compatible single-message save using the batch path."""
    result = save_raw_messages_batch(
        channel_id=channel_id,
        messages=[
            {
                "telegram_message_id": telegram_message_id,
                "message_date": message_date,
                "text": text,
                "edit_date": edit_date,
                "has_media": has_media,
                "reply_to_message_id": reply_to_message_id,
            }
        ],
        database_path=database_path,
    )
    return result[0]


def get_raw_message(
    channel_id: int,
    telegram_message_id: int,
    database_path: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    """Retrieve one message using its channel and Telegram message IDs."""
    with database_connection(database_path) as connection:
        row = connection.execute(
            """
            SELECT *
            FROM raw_messages
            WHERE channel_id = ? AND telegram_message_id = ?
            """,
            (channel_id, telegram_message_id),
        ).fetchone()
    return dict(row) if row else None


def list_raw_messages(
    channel_id: int,
    limit: int = 100,
    database_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """List messages for a channel, newest publication first."""
    if limit < 1 or limit > 10000:
        raise ValueError("limit must be between 1 and 10000.")

    with database_connection(database_path) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM raw_messages
            WHERE channel_id = ?
            ORDER BY message_date DESC, telegram_message_id DESC
            LIMIT ?
            """,
            (channel_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_message_versions(
    raw_message_id: int,
    database_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Return observed versions of a message in version order."""
    with database_connection(database_path) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM message_versions
            WHERE raw_message_id = ?
            ORDER BY version_number
            """,
            (raw_message_id,),
        ).fetchall()
    return [dict(row) for row in rows]

def mark_message_edited(channel_id: int, telegram_message_id: int) -> None:
    """Mark a Telegram message as edited for future ranking penalties."""
    from database.connection import database_transaction

    with database_transaction() as conn:
        cursor = conn.execute(
            """
            UPDATE raw_messages
            SET collection_status = 'edited',
                updated_at = CURRENT_TIMESTAMP
            WHERE channel_id = ?
              AND telegram_message_id = ?
            """,
            (channel_id, telegram_message_id),
        )

        if cursor.rowcount == 0:
            raise ValueError(
                "Cannot mark message as edited: "
                f"channel_id={channel_id}, "
                f"telegram_message_id={telegram_message_id}"
            )
