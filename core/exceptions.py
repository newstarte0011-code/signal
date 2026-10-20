import logging
import sys
from typing import NoReturn


logger = logging.getLogger("core.exceptions")


def handle_unhandled_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback,
) -> None:
    """
    Log uncaught exceptions before the application exits.
    """

    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(
            exc_type,
            exc_value,
            exc_traceback,
        )
        return

    logger.critical(
        "An unhandled exception occurred.",
        exc_info=(
            exc_type,
            exc_value,
            exc_traceback,
        ),
    )


def install_exception_handler() -> None:
    """
    Register the global exception handler.
    """

    sys.excepthook = handle_unhandled_exception
    logger.info("Global exception handler installed.")
