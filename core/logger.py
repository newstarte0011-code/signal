import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from config.settings import (
    APP_NAME,
    LOG_FILE_PATH,
    LOG_LEVEL,
    LOG_LEVEL_NAME,
    ensure_directories,
)


LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | "
    "%(name)s | %(message)s"
)

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    log_file: Optional[Path] = None,
    level: Optional[int] = None,
) -> None:
    """
    Configure console and rotating file logging.

    Calling this function multiple times will not add
    duplicate handlers.
    """

    ensure_directories()

    selected_log_file = log_file or LOG_FILE_PATH
    selected_level = LOG_LEVEL if level is None else level

    selected_log_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    root_logger = logging.getLogger()

    # Prevent duplicate handlers when initialized repeatedly.
    if getattr(root_logger, "_signal_analyzer_configured", False):
        return

    root_logger.setLevel(selected_level)

    formatter = logging.Formatter(
        fmt=LOG_FORMAT,
        datefmt=DATE_FORMAT,
    )

    # --------------------------------------------------
    # Console handler
    # --------------------------------------------------

    console_handler = logging.StreamHandler()
    console_handler.setLevel(selected_level)
    console_handler.setFormatter(formatter)

    # --------------------------------------------------
    # Rotating file handler
    # --------------------------------------------------

    file_handler = RotatingFileHandler(
        filename=selected_log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )

    file_handler.setLevel(selected_level)
    file_handler.setFormatter(formatter)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    root_logger._signal_analyzer_configured = True

    root_logger.info(
        "%s logging initialized | level=%s | file=%s",
        APP_NAME,
        LOG_LEVEL_NAME if level is None else logging.getLevelName(level),
        selected_log_file,
    )


def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger for a project component.
    """
    return logging.getLogger(name)
