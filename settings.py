from pathlib import Path
import logging
import os


# --------------------------------------------------
# Project paths
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
EXPORT_DIR = DATA_DIR / "exports"
CANDLES_DIR = DATA_DIR / "candles"

DATABASE_PATH = DATA_DIR / "app.db"
LOG_FILE_PATH = LOG_DIR / "app.log"


# --------------------------------------------------
# Logging configuration
# --------------------------------------------------

LOG_LEVEL_NAME = os.getenv("SIGNAL_ANALYZER_LOG_LEVEL", "INFO").upper()

LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

if LOG_LEVEL_NAME not in LOG_LEVELS:
    raise ValueError(
        f"Invalid log level: {LOG_LEVEL_NAME}. "
        f"Allowed values: {', '.join(LOG_LEVELS)}"
    )

LOG_LEVEL = LOG_LEVELS[LOG_LEVEL_NAME]


# --------------------------------------------------
# Application configuration
# --------------------------------------------------

APP_NAME = "Signal Analyzer"
APP_VERSION = "0.1.0"

TIMEZONE = "UTC"


# --------------------------------------------------
# Directory initialization
# --------------------------------------------------

def ensure_directories() -> None:
    """
    Create required project directories if they do not exist.
    """
    directories = (
        DATA_DIR,
        LOG_DIR,
        EXPORT_DIR,
        CANDLES_DIR,
    )

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)