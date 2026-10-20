
import argparse
import asyncio
import logging
import subprocess
import sys
import time
from pathlib import Path

from config.settings import APP_NAME, APP_VERSION, BASE_DIR
from core.logger import setup_logging
from core.exceptions import install_exception_handler


ROOT = Path(__file__).resolve().parent

COMMANDS = {
    "parse": ROOT / "parse_signals.py",
    "export": ROOT / "export_channel_messages.py",
}

logger = logging.getLogger(__name__)


def show_status() -> int:
    """Display basic project and runtime status."""
    logger.info("Project root: %s", ROOT)
    logger.info("Python version: %s", sys.version.split()[0])
    logger.info("Python executable: %s", sys.executable)

    paths = {
        "Database": ROOT / "data" / "app.db",
        "Sessions directory": ROOT / "data" / "sessions",
        "Candles directory": ROOT / "data" / "candles",
        "Exports directory": ROOT / "data" / "exports",
        "Logs directory": ROOT / "logs",
    }

    for label, path in paths.items():
        logger.info("%s: %s [%s]", label, path,
                    "exists" if path.exists() else "missing")

    return 0


def run_script(script: Path) -> int:
    """Run an existing project script using the current Python interpreter."""
    if not script.is_file():
        logger.error("Script not found: %s", script)
        return 1

    logger.info("Running script: %s", script.name)

    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=ROOT,
            check=False,
        )
        return result.returncode
    except OSError:
        logger.exception("Could not start script: %s", script.name)
        return 1


async def run_sync() -> int:
    """Synchronize the configured Telegram channel into SQLite."""
    from config.telegram_channels import (
        TEST_CHANNEL,
        TEST_MESSAGE_LIMIT,
    )
    from telegram_client.client import create_telegram_client
    from telegram_client.history_sync import sync_channel_history

    client = create_telegram_client()

    try:
        logger.info(
            "Starting Telegram sync: channel=%s, limit=%s",
            TEST_CHANNEL,
            TEST_MESSAGE_LIMIT,
        )

        await client.start()

        result = await sync_channel_history(
            client=client,
            channel_reference=TEST_CHANNEL,
            limit=TEST_MESSAGE_LIMIT,
        )

        logger.info(
            "Telegram sync completed: channel=%s, processed=%s, "
            "batches_saved=%s, channel_db_id=%s",
            result["channel_title"],
            result["processed"],
            result["batches_saved"],
            result["channel_db_id"],
        )

        return 0

    except Exception:
        logger.exception("Telegram sync failed.")
        return 1

    finally:
        if client.is_connected():
            await client.disconnect()
            logger.info("Telegram client disconnected.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} - Telegram signal analysis",
    )

    parser.add_argument(
        "command",
        nargs="?",
        choices=("status", "parse", "export", "sync"),
        default="status",
        help="Command to run (default: status)",
    )

    return parser


def main() -> int:
    setup_logging()
    install_exception_handler()

    parser = build_parser()
    args = parser.parse_args()

    started_at = time.perf_counter()

    logger.info("%s v%s", APP_NAME, APP_VERSION)
    logger.info("Command started: %s", args.command)

    try:
        if args.command == "status":
            exit_code = show_status()

        elif args.command in COMMANDS:
            exit_code = run_script(COMMANDS[args.command])

        elif args.command == "sync":
            exit_code = asyncio.run(run_sync())

        else:
            parser.error("Unsupported command.")
            return 2

    except KeyboardInterrupt:
        logger.warning("Command interrupted by user.")
        exit_code = 130

    elapsed = time.perf_counter() - started_at
    logger.info(
        "Command finished: %s | exit_code=%s | elapsed=%.2fs",
        args.command,
        exit_code,
        elapsed,
    )

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
