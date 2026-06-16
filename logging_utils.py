import logging
from logging.handlers import RotatingFileHandler

from .config import LOG_FILE

LOGGER = logging.getLogger("FZAstroAI")
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False

if not LOGGER.handlers:
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    )
    LOGGER.addHandler(file_handler)


def log_exception(context, error=None):
    """Write hidden UI/worker failures to the app log without breaking recovery paths."""
    try:
        if error is None:
            LOGGER.exception(str(context or "Unhandled exception"))
        else:
            LOGGER.exception("%s: %s", str(context or "Unhandled exception"), error)
    except Exception:
        pass


def log_warning(context, error=None):
    """Write expected recoverable warnings without a traceback."""
    try:
        if error is None:
            LOGGER.warning(str(context or "Warning"))
        else:
            LOGGER.warning("%s: %s", str(context or "Warning"), error)
    except Exception:
        pass


def log_debug(context, error=None):
    """Write low-level recovery details only when debug logging is enabled."""
    try:
        if error is None:
            LOGGER.debug(str(context or "Debug"))
        else:
            LOGGER.debug("%s: %s", str(context or "Debug"), error)
    except Exception:
        pass
