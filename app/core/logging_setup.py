"""Logging setup using a JSON formatter."""

import logging
import sys

from pythonjsonlogger import jsonlogger


class SensitiveFilter(logging.Filter):  # pylint: disable=too-few-public-methods
    """Mask sensitive fields like tokens or secrets in logs."""

    KEYWORDS = ("token", "secret", "password")

    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover - simple
        for key in list(record.__dict__):
            if any(k in key.lower() for k in self.KEYWORDS):
                setattr(record, key, "***")
        return True


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with JSON formatting.

    Parameters
    ----------
    level: str
        Logging level for root logger.
    """

    root = logging.getLogger()
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        json_ensure_ascii=False,
    )
    handler.setFormatter(formatter)
    handler.addFilter(SensitiveFilter())
    root.handlers = [handler]
