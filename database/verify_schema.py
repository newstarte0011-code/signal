#!/usr/bin/env python3
"""Read-only schema preflight for Signal Analyzer's SQLite database.

This script never creates, migrates, or writes to the target database.
Run it before the parser integration step.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REQUIRED_COLUMNS = {
    "channels": {"id", "title", "username"},
    "raw_messages": {
        "id", "channel_id", "telegram_message_id", "message_date",
        "current_text", "has_media", "collection_status", "edit_date",
    },
    "signals": {
        "id", "raw_message_id", "signal_index", "instrument", "direction",
        "entry_type", "entry_price", "entry_min", "entry_max", "stop_loss",
        "take_profits", "validation_status", "confidence", "parser_version",
        "updated_at",
    },
    "signal_versions": {
        "id", "signal_id", "version_number", "snapshot_json", "created_at",
    },
}


def inspect_database(path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    notes: list[str] = []
    if not path.is_file():
        return [f"Database file does not exist: {path}"], notes

    # Read-only URI ensures this preflight cannot create or mutate the DB.
    uri = path.resolve().as_uri() + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        return [f"Could not open database read-only: {exc}"], notes

    try:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        for table, required in REQUIRED_COLUMNS.items():
            if table not in tables:
                errors.append(f"Missing table: {table}")
                continue
            actual = {
                row["name"]
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            }
            missing = sorted(required - actual)
            if missing:
                errors.append(f"{table}: missing columns: {', '.join(missing)}")
            else:
                notes.append(f"{table}: OK ({len(actual)} columns found)")

        if "raw_messages" in tables:
            cols = {
                row["name"]
                for row in connection.execute('PRAGMA table_info("raw_messages")')
            }
            if "raw_text" in cols and "current_text" in cols:
                notes.append("raw_messages has both raw_text and current_text; confirm repository semantics")

        if not errors:
            notes.append("Required table/column preflight passed; this does not prove runtime SQL compatibility.")
    except sqlite3.Error as exc:
        errors.append(f"SQLite inspection failed: {exc}")
    finally:
        connection.close()
    return errors, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path, help="Path to an existing SQLite database")
    args = parser.parse_args()
    errors, notes = inspect_database(args.database)
    for note in notes:
        print(f"[OK/INFO] {note}")
    for error in errors:
        print(f"[ERROR] {error}", file=sys.stderr)
    if errors:
        print("Schema preflight FAILED. No changes were made.", file=sys.stderr)
        return 1
    print("Schema preflight PASSED. No changes were made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
