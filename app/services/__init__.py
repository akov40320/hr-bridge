"""Инициализация пакета ``services``.

Пакет предоставляет отдельные вспомогательные функции для всего
приложения, такие как :func:`tg_send_with_retry`.
"""

from .telegram import tg_send_with_retry

__all__ = ["tg_send_with_retry"]
