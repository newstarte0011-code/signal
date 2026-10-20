
import logging

from database.connection import database_transaction

logger = logging.getLogger("database.schema")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE,
    username TEXT,
    title TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
        CHECK (is_active IN (0, 1)),
    first_seen_at TEXT NOT NULL,
    last_checked_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    telegram_message_id INTEGER NOT NULL,
    message_date TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    text TEXT,
    edit_date TEXT,
    content_hash TEXT,
    has_media INTEGER NOT NULL DEFAULT 0
        CHECK (has_media IN (0, 1)),
    collection_status TEXT NOT NULL DEFAULT 'collected'
        CHECK (
            collection_status IN (
                'collected',
                'edited',
                'deleted_detected',
                'unavailable',
                'error'
            )
        ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (channel_id)
        REFERENCES channels(id)
        ON DELETE RESTRICT,
    UNIQUE (channel_id, telegram_message_id)
);

CREATE TABLE IF NOT EXISTS message_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_message_id INTEGER NOT NULL,
    version_number INTEGER NOT NULL,
    text TEXT,
    content_hash TEXT NOT NULL,
    edit_date TEXT,
    observed_at TEXT NOT NULL,
    FOREIGN KEY (raw_message_id)
        REFERENCES raw_messages(id)
        ON DELETE RESTRICT,
    UNIQUE (raw_message_id, version_number)
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_message_id INTEGER NOT NULL,
    signal_index INTEGER NOT NULL DEFAULT 0,
    instrument TEXT NOT NULL DEFAULT 'XAUUSD',
    direction TEXT CHECK (direction IN ('BUY', 'SELL')),
    entry_type TEXT CHECK (
        entry_type IN ('MARKET', 'LIMIT', 'STOP', 'ZONE', 'UNKNOWN')
    ),
    entry_min REAL,
    entry_max REAL,
    stop_loss REAL,
    take_profit_1 REAL,
    take_profit_2 REAL,
    take_profit_3 REAL,
    extraction_method TEXT NOT NULL DEFAULT 'rules'
        CHECK (extraction_method IN ('rules', 'ai', 'manual')),
    validation_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (
            validation_status IN ('pending', 'valid', 'invalid', 'ambiguous')
        ),
    confidence REAL
        CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    published_at TEXT NOT NULL,
    extracted_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (raw_message_id)
        REFERENCES raw_messages(id)
        ON DELETE RESTRICT,
    UNIQUE (raw_message_id, signal_index)
);

CREATE TABLE IF NOT EXISTS signal_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL,
    version_number INTEGER NOT NULL,
    source_message_edit_date TEXT,
    direction TEXT,
    entry_min REAL,
    entry_max REAL,
    stop_loss REAL,
    take_profit_1 REAL,
    take_profit_2 REAL,
    take_profit_3 REAL,
    snapshot_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    is_original INTEGER NOT NULL DEFAULT 0
        CHECK (is_original IN (0, 1)),
    notes TEXT,
    FOREIGN KEY (signal_id)
        REFERENCES signals(id)
        ON DELETE RESTRICT,
    UNIQUE (signal_id, version_number)
);

CREATE TABLE IF NOT EXISTS candles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    instrument TEXT NOT NULL DEFAULT 'XAUUSD',
    timeframe TEXT NOT NULL,
    candle_open_time TEXT NOT NULL,
    candle_close_time TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL,
    downloaded_at TEXT NOT NULL,
    CHECK (high >= low),
    CHECK (high >= open AND high >= close),
    CHECK (low <= open AND low <= close),
    UNIQUE (source, instrument, timeframe, candle_open_time)
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_name TEXT NOT NULL,
    instrument TEXT NOT NULL DEFAULT 'XAUUSD',
    candle_source TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'UTC',
    spread REAL NOT NULL DEFAULT 0,
    slippage REAL NOT NULL DEFAULT 0,
    latency_seconds INTEGER NOT NULL DEFAULT 0
        CHECK (latency_seconds >= 0),
    entry_expiry_minutes INTEGER NOT NULL DEFAULT 1440
        CHECK (entry_expiry_minutes >= 0),
    execution_rules_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    started_at TEXT,
    finished_at TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_raw_messages_channel_date
    ON raw_messages(channel_id, message_date);

CREATE INDEX IF NOT EXISTS idx_message_versions_message
    ON message_versions(raw_message_id, version_number);

CREATE INDEX IF NOT EXISTS idx_signals_validation_status
    ON signals(validation_status);

CREATE INDEX IF NOT EXISTS idx_signals_published_at
    ON signals(published_at);

CREATE INDEX IF NOT EXISTS idx_candles_instrument_time
    ON candles(instrument, timeframe, candle_open_time);

CREATE INDEX IF NOT EXISTS idx_backtest_runs_status
    ON backtest_runs(status);
"""


def _remove_message_hash_uniqueness(connection) -> None:
    """
    Remove the legacy UNIQUE(raw_message_id, content_hash) constraint
    without deleting existing message versions.
    """
    indexes = connection.execute(
        "PRAGMA index_list('message_versions')"
    ).fetchall()

    for index in indexes:
        if not index["unique"]:
            continue

        index_name = index["name"].replace('"', '""')
        columns = connection.execute(
            f'PRAGMA index_info("{index_name}")'
        ).fetchall()

        column_names = [column["name"] for column in columns]

        if column_names != ["raw_message_id", "content_hash"]:
            continue

        logger.warning(
            "Migrating message_versions to allow repeated text versions."
        )

        connection.execute(
            "ALTER TABLE message_versions "
            "RENAME TO message_versions_old"
        )

        connection.execute("""
            CREATE TABLE message_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_message_id INTEGER NOT NULL,
                version_number INTEGER NOT NULL,
                text TEXT,
                content_hash TEXT NOT NULL,
                edit_date TEXT,
                observed_at TEXT NOT NULL,
                FOREIGN KEY (raw_message_id)
                    REFERENCES raw_messages(id)
                    ON DELETE RESTRICT,
                UNIQUE (raw_message_id, version_number)
            )
        """)

        connection.execute("""
            INSERT INTO message_versions (
                id,
                raw_message_id,
                version_number,
                text,
                content_hash,
                edit_date,
                observed_at
            )
            SELECT
                id,
                raw_message_id,
                version_number,
                text,
                content_hash,
                edit_date,
                observed_at
            FROM message_versions_old
        """)

        connection.execute(
            "DROP TABLE message_versions_old"
        )

        logger.info("message_versions migration completed.")
        return


def initialize_schema(database_path=None) -> None:
    """Create all tables and indexes and apply the legacy migration."""
    statements = [
        statement.strip()
        for statement in SCHEMA_SQL.split(";")
        if statement.strip()
    ]

    with database_transaction(database_path) as connection:
        for statement in statements:
            connection.execute(statement)

        _remove_message_hash_uniqueness(connection)

    logger.info("Database schema initialized successfully.")
