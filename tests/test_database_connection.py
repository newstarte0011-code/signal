"""Isolated smoke tests for database/connection.py.

Run from the project root:
    python -m unittest tests.test_database_connection -v

These tests use temporary databases only; they do not touch the project's DB.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from database.connection import database_connection, database_transaction


class DatabaseConnectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="signal-db-test-")
        self.db_path = Path(self.temp_dir.name) / "test.db"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_connection_persists_committed_data(self) -> None:
        with database_transaction(self.db_path) as connection:
            connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("INSERT INTO sample(value) VALUES (?)", ("persisted",))

        with database_connection(self.db_path) as connection:
            row = connection.execute("SELECT value FROM sample WHERE id = 1").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["value"], "persisted")

    def test_transaction_rolls_back_on_exception(self) -> None:
        with database_transaction(self.db_path) as connection:
            connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")

        with self.assertRaisesRegex(RuntimeError, "force rollback"):
            with database_transaction(self.db_path) as connection:
                connection.execute("INSERT INTO sample(value) VALUES (?)", ("should-not-remain",))
                raise RuntimeError("force rollback")

        with database_connection(self.db_path) as connection:
            count = connection.execute("SELECT COUNT(*) FROM sample").fetchone()[0]
        self.assertEqual(count, 0)

    def test_foreign_keys_are_enabled(self) -> None:
        with database_connection(self.db_path) as connection:
            enabled = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        self.assertEqual(enabled, 1)


if __name__ == "__main__":
    unittest.main()
