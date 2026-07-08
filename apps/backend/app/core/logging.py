import logging
import sys


REQUEST_LOGGER_NAME = "mwobareullae.request"
PERFORMANCE_LOGGER_NAME = "mwobareullae.performance"


def configure_logging(log_level: str) -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    _configure_message_only_logger(REQUEST_LOGGER_NAME, level)
    _configure_message_only_logger(PERFORMANCE_LOGGER_NAME, level)


def _configure_message_only_logger(name: str, level: int) -> None:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    if any(getattr(handler, "_mwobareullae_message_only", False) for handler in logger.handlers):
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler._mwobareullae_message_only = True
    logger.addHandler(handler)
