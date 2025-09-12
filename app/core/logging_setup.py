"""Настройка логирования с использованием JSON‑форматтера."""

import logging
import sys

from pythonjsonlogger import jsonlogger


def setup_logging(level: str = "INFO") -> None:
    """Настроить корневой логгер c JSON‑форматированием.

    Параметры
    ----------
    level: str
        Уровень логирования для корневого логгера.
    """

    root = logging.getLogger()
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        json_ensure_ascii=False,
    )
    handler.setFormatter(formatter)
    root.handlers = [handler]
